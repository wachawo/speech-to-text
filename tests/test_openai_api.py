#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The OpenAI-compatible routes: POST /v1/audio/transcriptions and GET /v1/models."""

import io
import queue

import pytest

# Local imports
import stt_server
from libs import config, openai_api, speech_gate
from tests.helpers import REQ_ID_RE, get_default_pool, make_wav

TRANSCRIPTIONS = "/v1/audio/transcriptions"
PARAKEET_ID = "nvidia/parakeet-tdt-0.6b-v3"

# Whisper's own segments, with every field it reports, as the real get_stt_result returns them.
WHISPER_DETAILS = [
    {
        "id": 0,
        "seek": 0,
        "start": 0.0,
        "end": 1.1,
        "text": " first phrase",
        "tokens": [50364, 700],
        "temperature": 0.0,
        "avg_logprob": -0.2,
        "compression_ratio": 1.1,
        "no_speech_prob": 0.01,
    }
]


def post_transcription(client, wav=None, filename="sample.wav", headers=None, **fields):
    """POST an upload to /v1/audio/transcriptions with the given form fields; returns the response."""
    data = {"file": (io.BytesIO(make_wav() if wav is None else wav), filename)}
    data.update(fields)
    return client.post(TRANSCRIPTIONS, data=data, content_type="multipart/form-data", headers=headers or {})


def assert_openai_error(resp, status, message, error_type, param):
    """Assert an OpenAI-shaped error body: the category, its type, the field at fault, its slug and the id."""
    assert resp.status_code == status
    body = resp.get_json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["message"] == message
    assert error["type"] == error_type
    assert error["param"] == param
    assert error["code"] == "_".join(message.lower().split())
    assert REQ_ID_RE.match(error["request_id"])
    assert resp.headers["X-Request-Id"] == error["request_id"]


def record_transcriber_calls(monkeypatch, module, details=None):
    """Replace a stub module's get_stt_result with one that records its arguments; returns the call list.

    `details`, when given, are returned as Whisper's `segment_details`.
    """
    calls = []
    original = module.get_stt_result

    def recording_get_stt_result(bio, model=None, device=None, language=None, prompt=None):
        """Record the call, then answer as the stub does, plus the details the test chose."""
        calls.append({"model": model, "language": language, "prompt": prompt})
        result = dict(original(bio, model=model, device=device, language=language, prompt=prompt))
        if details is not None:
            result["segment_details"] = details
        return result

    monkeypatch.setattr(module, "get_stt_result", recording_get_stt_result)
    return calls


def test_json_is_the_default_format(client):
    """Without response_format the answer is `{text}` and nothing else, with the request id in a header."""
    resp = post_transcription(client)
    assert resp.status_code == 200
    assert resp.get_json() == {"text": "stub transcription"}
    assert REQ_ID_RE.match(resp.headers["X-Request-Id"])


def test_text_format_is_a_plain_body(client):
    """`text` answers the transcription itself as text/plain."""
    resp = post_transcription(client, response_format="text")
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    assert resp.get_data(as_text=True) == "stub transcription"


def test_verbose_json_carries_whisper_segments_as_whisper_gives_them(client, stt_module, monkeypatch):
    """verbose_json: the task, the full language name, the duration from the header and Whisper's own segments."""
    record_transcriber_calls(monkeypatch, stt_module, details=WHISPER_DETAILS)

    def get_language_name(code):
        """Stand in for stt.get_language_name(), which the stub module lacks."""
        return {"en": "english"}.get(code)

    monkeypatch.setattr(stt_module, "get_language_name", get_language_name, raising=False)
    resp = post_transcription(client, wav=make_wav(duration_ms=250), response_format="verbose_json")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["task"] == "transcribe"
    assert body["language"] == "english"
    assert body["duration"] == pytest.approx(0.25)
    assert body["text"] == "stub transcription"
    assert body["segments"] == WHISPER_DETAILS


def test_verbose_json_builds_one_segment_from_parakeet_words(multi_client):
    """Parakeet reports no details and no language: one segment of its words, nothing invented."""
    resp = post_transcription(multi_client, model=PARAKEET_ID, response_format="verbose_json")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["language"] is None
    assert body["text"] == "parakeet transcription"
    assert body["segments"] == [
        {
            "id": 0,
            "seek": 0,
            "start": 0.0,
            "end": 2.4,
            "text": " parakeet first parakeet second",
            "tokens": [],
            "temperature": 0.0,
            "avg_logprob": None,
            "compression_ratio": None,
            "no_speech_prob": None,
        }
    ]


def test_a_phrase_segment_of_no_words_is_no_segment():
    """Silence gives an empty segment list, not one segment with empty text."""
    assert openai_api.build_phrase_segment([]) == []
    assert openai_api.build_phrase_segment([{"start": 0.0, "end": 0.2, "text": " "}]) == []


@pytest.mark.parametrize("response_format", ["srt", "vtt", "xml"])
def test_a_format_this_service_does_not_produce_is_refused(client, response_format):
    """srt and vtt are OpenAI formats nothing here writes; the 400 names the field."""
    resp = post_transcription(client, response_format=response_format)
    assert_openai_error(resp, 400, "Unsupported response format", "invalid_request_error", "response_format")


@pytest.mark.parametrize("temperature", ["0", "0.0", " "])
def test_temperature_zero_or_absent_is_accepted(client, temperature):
    """Decoding is deterministic at 0, so 0 and an empty value are the only temperatures served."""
    assert post_transcription(client, temperature=temperature).status_code == 200


def test_a_nonzero_temperature_is_refused(client):
    """A temperature the decode would not honour is a 400 rather than a silent change of meaning."""
    resp = post_transcription(client, temperature="0.2")
    assert_openai_error(resp, 400, "Unsupported temperature", "invalid_request_error", "temperature")


def test_a_temperature_that_is_not_a_number_is_invalid(client):
    """Not a number is a different category from a number that is not 0."""
    resp = post_transcription(client, temperature="warm")
    assert_openai_error(resp, 400, "Invalid temperature", "invalid_request_error", "temperature")


@pytest.mark.parametrize("field", ["timestamp_granularities[]", "timestamp_granularities"])
def test_segment_granularity_is_accepted_under_both_spellings(client, field):
    """Segment times exist; both the SDK's list spelling and the bare one are read."""
    assert post_transcription(client, **{field: "segment"}).status_code == 200


def test_word_granularity_is_refused(client):
    """Word times would need word_timestamps=True, which changes the transcription; the 400 says so."""
    resp = post_transcription(client, **{"timestamp_granularities[]": "word"})
    assert_openai_error(resp, 400, "Unsupported timestamp granularity", "invalid_request_error", "timestamp_granularities")


def test_the_prompt_reaches_the_transcriber(client, stt_module, monkeypatch):
    """`prompt` becomes Whisper's initial prompt, trimmed; an empty one is no prompt at all."""
    calls = record_transcriber_calls(monkeypatch, stt_module)
    assert post_transcription(client, prompt="  Kubernetes, gRPC  ").status_code == 200
    assert post_transcription(client, prompt="   ").status_code == 200
    assert [call["prompt"] for call in calls] == ["Kubernetes, gRPC", None]


@pytest.mark.parametrize("prompt", ["<|endoftext|>", "before <|en|> after", "<|0.00|>"])
def test_a_prompt_holding_a_special_token_is_refused(client, stt_module, monkeypatch, prompt):
    """tiktoken refuses to encode a special token, so it is the client's 400 and never reaches the model."""
    calls = record_transcriber_calls(monkeypatch, stt_module)
    resp = post_transcription(client, prompt=prompt)
    assert_openai_error(resp, 400, "Invalid prompt", "invalid_request_error", "prompt")
    assert calls == []


def test_the_model_and_language_are_resolved_as_on_api_stt(multi_client, stt_module, monkeypatch):
    """A model id picks its pool and the language is checked against that model, exactly as /api/stt does."""
    calls = record_transcriber_calls(monkeypatch, stt_module)
    resp = post_transcription(multi_client, model="small.en-stub", language="Russian")
    assert resp.status_code == 200
    assert calls[0]["model"] == {"stub_model": "small.en-stub"}
    assert calls[0]["language"] == "ru"


def test_openai_model_names_are_not_ours(client):
    """`whisper-1` is OpenAI's name, not one this server loaded; GET /v1/models lists what to send."""
    resp = post_transcription(client, model="whisper-1")
    assert_openai_error(resp, 400, "Invalid model", "invalid_request_error", "model")


def test_a_language_the_model_does_not_take_is_refused(multi_client):
    """An English-only checkpoint named by the request is held to its own list."""
    resp = post_transcription(multi_client, model="tiny.en", language="ru")
    assert_openai_error(resp, 400, "Unsupported language", "invalid_request_error", "language")


def test_no_file_is_no_audio_data(client):
    """A form without `file` is the shared category in OpenAI's shape, pointing at the field."""
    resp = client.post(TRANSCRIPTIONS, data={"model": "small.en-stub"}, content_type="multipart/form-data")
    assert_openai_error(resp, 400, "No audio data", "invalid_request_error", "file")


def test_an_upload_that_is_not_audio_is_invalid(client):
    """A payload pydub cannot decode is a 400, and the model is never borrowed."""
    resp = post_transcription(client, wav=b"not an audio file at all", filename="garbage.bin")
    assert_openai_error(resp, 400, "Invalid audio data", "invalid_request_error", "file")
    assert get_default_pool().qsize() == 1


def test_an_exhausted_pool_is_a_server_error(client, monkeypatch):
    """No model within STT_QUEUE_TIMEOUT is a 503 of type server_error, not a hang."""

    def raise_queue_empty(*args, **kwargs):
        """Stand in for Queue.get() and report the pool as exhausted."""
        raise queue.Empty

    monkeypatch.setattr(get_default_pool(), "get", raise_queue_empty)
    resp = post_transcription(client)
    assert_openai_error(resp, 503, "Service Unavailable", "server_error", None)


def test_a_failed_decode_is_a_500_and_gives_the_model_back(client, stt_module, monkeypatch):
    """The exception stays in the log; the client gets the category, and the instance returns to its pool."""

    def raise_runtime_error(bio, model=None, device=None, language=None, prompt=None):
        """Stand in for stt.get_stt_result() and fail."""
        raise RuntimeError("transcription exploded")

    monkeypatch.setattr(stt_module, "get_stt_result", raise_runtime_error)
    resp = post_transcription(client)
    assert_openai_error(resp, 500, "Transcription failed", "server_error", None)
    assert "exploded" not in resp.get_data(as_text=True)
    assert get_default_pool().qsize() == 1


def test_a_served_request_gives_the_model_back(client):
    """Every success releases its instance, so the next request finds the pool full."""
    for unused_attempt in range(3):
        assert post_transcription(client).status_code == 200
    assert get_default_pool().qsize() == 1


def test_the_token_is_required_when_tokens_are_set(client, monkeypatch):
    """Behind STT_TOKENS like /api/stt: no token is an authentication_error, a valid one is served."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    assert_openai_error(post_transcription(client), 401, "Unauthorized", "authentication_error", None)
    assert post_transcription(client, headers={"Authorization": "Bearer secret"}).status_code == 200


def test_an_upload_over_the_limit_is_413_in_openai_shape(client, monkeypatch):
    """The size limit holds on /v1 too, and its error drops the `limit_mb` the OpenAI body has no room for."""
    monkeypatch.setitem(stt_server.app.config, "MAX_CONTENT_LENGTH", 1024)
    resp = post_transcription(client, wav=b"\0" * 4096)
    assert_openai_error(resp, 413, "Payload Too Large", "invalid_request_error", "file")


def test_unknown_v1_paths_and_methods_answer_in_openai_shape(client):
    """The app-wide 404 and 405 take OpenAI's shape under /v1; a 405 still names the allowed method."""
    assert_openai_error(client.get("/v1/audio/translations"), 404, "Not Found", "invalid_request_error", None)
    resp = client.get(TRANSCRIPTIONS)
    assert_openai_error(resp, 405, "Method Not Allowed", "invalid_request_error", None)
    assert "POST" in resp.headers["Allow"]


def test_the_api_routes_keep_their_own_error_shape(client):
    """The OpenAI body is for /v1 only: the web UI reads the flat one from /api."""
    body = client.post("/api/stt").get_json()
    assert set(body) == {"error", "request_id"}


@pytest.mark.parametrize(("model_id", "words"), [("small.en-stub", False), (PARAKEET_ID, True)])
def test_the_speech_gate_filters_the_text(multi_client, monkeypatch, model_id, words):
    """With the gate on the text is rebuilt from the kept segments, and Parakeet's are judged as words."""
    seen = []

    def keep_first_segment(wav_bio, segments, request_id="-", words=False):
        """Stand in for speech_gate.gate_wav: record how it was called, keep only the first segment."""
        seen.append(words)
        return segments[:1]

    monkeypatch.setattr(config, "SPEECH_GATE", True)
    monkeypatch.setattr(speech_gate, "gate_wav", keep_first_segment)
    resp = post_transcription(multi_client, model=model_id)
    assert resp.status_code == 200
    assert resp.get_json()["text"] == ("first phrase" if not words else "parakeet first")
    assert seen == [words]


def test_models_lists_the_loaded_model(client):
    """A single-model deployment lists its one model by the id /api/models uses."""
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    assert resp.get_json() == {
        "object": "list",
        "data": [{"id": "small.en-stub", "object": "model", "created": 0, "owned_by": "whisper"}],
    }
    assert REQ_ID_RE.match(resp.headers["X-Request-Id"])


def test_models_lists_every_loaded_model_with_its_backend(multi_client):
    """Several models: one row each, in STT_MODELS order, owned by their backend."""
    data = multi_client.get("/v1/models").get_json()["data"]
    assert [(row["id"], row["owned_by"]) for row in data] == [
        ("small.en-stub", "whisper"),
        ("tiny.en", "whisper"),
        (PARAKEET_ID, "parakeet"),
    ]


def test_models_needs_the_token_like_api_models(client, monkeypatch):
    """The model list is configuration, so it is behind the token like /api/models."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    assert_openai_error(client.get("/v1/models"), 401, "Unauthorized", "authentication_error", None)
    assert client.get("/v1/models", headers={"Authorization": "Bearer secret"}).status_code == 200

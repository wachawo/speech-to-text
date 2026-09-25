#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POST /api/stt and /api/transcript with several models loaded: `model` picks the pool."""

import io
import queue
import re

import pytest

from libs import config, model_pool
from tests.helpers import make_wav

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def record_models(module, monkeypatch) -> list:
    """Swap a backend's get_stt_result for one that records which instance it was handed."""
    seen: list = []
    original = module.get_stt_result

    def record_model(bio, model=None, device=None, language=None):
        """Stand in for get_stt_result(), remembering the instance before answering like the stub."""
        seen.append(model)
        return original(bio, model=model, device=device, language=language)

    monkeypatch.setattr(module, "get_stt_result", record_model)
    return seen


def pool_sizes() -> dict[str, int]:
    """How many idle instances each model's pool holds right now."""
    return {model_id: pool.qsize() for model_id, pool in model_pool.MODEL_POOLS.items()}


def post_wav(client, query="", data=None):
    """POST a short WAV to /api/stt as multipart, with optional extra form fields."""
    fields = {"file": (io.BytesIO(make_wav(duration_ms=50)), "sample.wav"), **(data or {})}
    return client.post(f"/api/stt{query}", data=fields, content_type="multipart/form-data")


def test_without_model_the_default_serves(multi_client, stt_module, monkeypatch):
    """A request that names no model is served by the default one and says which it was."""
    seen = record_models(stt_module, monkeypatch)
    resp = post_wav(multi_client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body) == {"text", "elapsed", "model", "language"}
    assert body["model"] == "small.en-stub"
    assert seen == [{"stub_model": "small.en-stub"}]


def test_query_model_borrows_from_that_models_pool(multi_client, stt_module, monkeypatch):
    """`?model=tiny.en` hands the backend a tiny.en instance, and an English-only model reports `en`."""
    seen = record_models(stt_module, monkeypatch)
    body = post_wav(multi_client, "?model=tiny.en").get_json()
    assert seen == [{"stub_model": "tiny.en"}]
    assert body["model"] == "tiny.en"
    assert body["language"] == "en"


def test_form_field_model_works(multi_client):
    """The multipart field `model` is read like the query string."""
    assert post_wav(multi_client, data={"model": "tiny.en"}).get_json()["model"] == "tiny.en"


def test_the_query_string_beats_the_form_field(multi_client):
    """With both present the query string wins, exactly as for `language`."""
    assert post_wav(multi_client, "?model=tiny.en", {"model": "parakeet"}).get_json()["model"] == "tiny.en"


def test_an_empty_query_yields_to_the_form_then_to_the_default(multi_client):
    """`?model=` is "not given": the form field applies, and without one the default model."""
    assert post_wav(multi_client, "?model=", {"model": "tiny.en"}).get_json()["model"] == "tiny.en"
    assert post_wav(multi_client, "?model=").get_json()["model"] == "small.en-stub"


def test_parakeet_is_routed_to_its_own_module(multi_client):
    """The bare backend name selects Parakeet, whose stub answers with its own text and no language."""
    body = post_wav(multi_client, "?model=parakeet").get_json()
    assert body["text"] == "stub parakeet transcription"
    assert body["model"] == "nvidia/parakeet-tdt-0.6b-v3"
    assert body["language"] is None


def test_an_unknown_model_is_a_400_that_borrows_nothing(multi_client):
    """A name nobody knows is refused with the generic body, and every pool is left as it was."""
    before = pool_sizes()
    resp = post_wav(multi_client, "?model=nope")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Invalid model"
    assert set(body) == {"error", "request_id"}
    assert REQ_ID_RE.match(body["request_id"])
    assert pool_sizes() == before


def test_a_known_model_that_is_not_loaded_is_a_400(multi_client):
    """Nothing is ever loaded lazily: a real model this server did not load is refused."""
    resp = post_wav(multi_client, "?model=medium")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Model not loaded"


def test_the_model_is_checked_before_the_audio(multi_client):
    """An unknown model with undecodable audio reports the model, which is checked first."""
    resp = multi_client.post(
        "/api/stt?model=nope",
        data={"file": (io.BytesIO(b"not audio"), "garbage.bin")},
        content_type="multipart/form-data",
    )
    assert resp.get_json()["error"] == "Invalid model"


def test_missing_audio_is_reported_before_the_model(multi_client):
    """No body at all is `No audio data`, whatever the model says."""
    resp = multi_client.post("/api/stt?model=nope")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "No audio data"


def test_the_token_is_checked_before_anything(multi_client, monkeypatch):
    """Without the token an unknown model is still just a 401."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    assert post_wav(multi_client, "?model=nope").status_code == 401


def test_an_exhausted_pool_is_a_503_for_that_model_only(multi_client, monkeypatch):
    """When the chosen model has nothing free the request waits on it alone; the default is untouched."""

    def raise_queue_empty(*args, **kwargs):
        """Stand in for Queue.get() and report the pool as exhausted."""
        raise queue.Empty

    monkeypatch.setattr(model_pool.MODEL_POOLS["tiny.en"], "get", raise_queue_empty)
    resp = post_wav(multi_client, "?model=tiny.en")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Service Unavailable"
    assert model_pool.MODEL_POOLS["small.en-stub"].qsize() == 1


def test_a_failure_returns_the_instance_to_its_own_pool(multi_client, stt_module, monkeypatch):
    """A crash on tiny.en gives a 500 and puts the instance back in tiny.en's pool, not the default's."""

    def raise_runtime_error(bio, model=None, device=None, language=None):
        """Stand in for get_stt_result() and fail."""
        raise RuntimeError("transcription exploded")

    monkeypatch.setattr(stt_module, "get_stt_result", raise_runtime_error)
    resp = post_wav(multi_client, "?model=tiny.en")
    assert resp.status_code == 500
    assert "transcription exploded" not in resp.get_data(as_text=True)
    assert pool_sizes() == {"small.en-stub": 1, "tiny.en": 2, "nvidia/parakeet-tdt-0.6b-v3": 1}


@pytest.fixture
def multi_diarize_client(multi_client, monkeypatch):
    """Several models plus a one-slot diarizer pool, for /api/transcript."""
    pool: queue.Queue = queue.Queue()
    pool.put("diarizer-sentinel")
    monkeypatch.setattr(model_pool, "DIARIZER_POOL", pool)
    monkeypatch.setattr(config, "DIARIZE_ENABLED", True)
    monkeypatch.setattr(config, "DIARIZE_POOL_SIZE", 1)
    return multi_client


def test_transcript_uses_the_chosen_model(multi_diarize_client, stt_module, monkeypatch):
    """/api/transcript hands the backend a tiny.en instance, names it in the response, and returns both instances."""
    seen: list = []
    original = stt_module.get_stt_segments

    def record_segments(bio, model=None, device=None, language=None):
        """Stand in for get_stt_segments(), remembering the instance before answering like the stub."""
        seen.append(model)
        return original(bio, model=model, device=device, language=language)

    monkeypatch.setattr(stt_module, "get_stt_segments", record_segments)
    resp = multi_diarize_client.post("/api/transcript?model=tiny.en", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen == [{"stub_model": "tiny.en"}]
    assert resp.get_json()["model"] == "tiny.en"
    assert pool_sizes()["tiny.en"] == 2
    assert model_pool.DIARIZER_POOL.qsize() == 1


def test_transcript_refuses_an_unknown_model_before_borrowing(multi_diarize_client, diarize_module, monkeypatch):
    """A bad model costs neither a diarization nor a transcription instance."""
    calls: list = []

    def record_diarization(bio, diarizer=None, threshold=None):
        """Stand in for diarize_wav() and remember that it ran."""
        calls.append(diarizer)
        return []

    monkeypatch.setattr(diarize_module, "diarize_wav", record_diarization)
    resp = multi_diarize_client.post("/api/transcript?model=nope", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Invalid model"
    assert calls == []
    assert model_pool.DIARIZER_POOL.qsize() == 1

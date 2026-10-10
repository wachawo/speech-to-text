#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POST /api/transcript - who said what, and the pool discipline that gets it there."""

import io
import queue
import re

from libs import model_pool
from tests.helpers import make_wav

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def assert_error_shape(body):
    """Assert the response carries exactly the generic error category and a request id."""
    assert set(body.keys()) == {"error", "request_id"}
    assert REQ_ID_RE.match(body["request_id"])


def post_audio(client):
    """POST a short silent WAV to /api/transcript as a multipart upload."""
    return client.post(
        "/api/transcript",
        data={"file": (io.BytesIO(make_wav(duration_ms=50)), "meeting.wav")},
        content_type="multipart/form-data",
    )


def refuse_borrowing(monkeypatch, name, borrowed):
    """Replace model_pool.<name> with one that records being called and answers as an exhausted pool.

    Pool sizes after the response cannot show the order things happened in: a model borrowed and
    given back too early leaves the pool just as full as one never borrowed. The record can.
    """

    def record_borrowing(timeout=None):
        """Stand in for an acquire function: note the call and report the pool as exhausted."""
        borrowed.append(name)
        raise queue.Empty

    monkeypatch.setattr(model_pool, name, record_borrowing)


def test_disabled_build_refuses(client):
    """Without diarization there is nobody to attribute to, so the route refuses."""
    resp = post_audio(client)
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Diarization disabled"
    assert_error_shape(resp.get_json())


def test_returns_attributed_segments_and_the_raw_turns(diarize_client):
    """Both views are returned: the join, and what the diarizer actually said."""
    body = post_audio(diarize_client).get_json()
    assert [s["speaker"] for s in body["segments"]] == [0, 1]
    assert body["turns"] == [
        {"speaker": 0, "start": 0.0, "end": 1.2},
        {"speaker": 1, "start": 1.0, "end": 2.5},
    ]
    assert body["speakers"] == 2
    assert "elapsed" in body


def test_text_is_the_whole_transcript(diarize_client):
    """The unattributed transcript is present, so a caller who distrusts the join still has it."""
    body = post_audio(diarize_client).get_json()
    assert body["text"] == "first phrase second phrase"


def test_overlapping_speech_is_flagged(diarize_client):
    """The stub turns overlap between 1.0 and 1.2, and the join says so rather than hiding it."""
    body = post_audio(diarize_client).get_json()
    assert any(segment["overlap"] for segment in body["segments"])


def test_no_body(diarize_client):
    """A request with neither a file field nor a body is a 400."""
    resp = diarize_client.post("/api/transcript")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "No audio data"


def test_unknown_language_refused_before_any_model_is_borrowed(diarize_client, monkeypatch):
    """The language is resolved first, so a bad one costs no model and no decode."""
    borrowed: list[str] = []
    refuse_borrowing(monkeypatch, "acquire_model", borrowed)
    refuse_borrowing(monkeypatch, "acquire_diarizer", borrowed)
    resp = diarize_client.post("/api/transcript?language=zz", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Invalid language"
    assert borrowed == []


def test_the_diarizer_is_released_before_a_transcription_model_is_borrowed(
    diarize_client, monkeypatch, stt_module, diarize_module
):
    """No request holds one of each: each model runs while the other pool is full."""
    free: dict[str, int] = {}
    diarize_wav = diarize_module.diarize_wav
    get_stt_segments = stt_module.get_stt_segments

    def diarize_and_count(bio, diarizer=None, threshold=None):
        """Stand in for diarize.diarize_wav() and note how many transcription models are free."""
        free["models while diarizing"] = model_pool.MODEL_POOL.qsize()
        return diarize_wav(bio, diarizer=diarizer, threshold=threshold)

    def transcribe_and_count(bio, model=None, device=None, language=None):
        """Stand in for stt.get_stt_segments() and note how many diarizers are free."""
        free["diarizers while transcribing"] = model_pool.DIARIZER_POOL.qsize()
        return get_stt_segments(bio, model=model, device=device, language=language)

    monkeypatch.setattr(diarize_module, "diarize_wav", diarize_and_count)
    monkeypatch.setattr(stt_module, "get_stt_segments", transcribe_and_count)

    assert post_audio(diarize_client).status_code == 200
    assert free == {"models while diarizing": 1, "diarizers while transcribing": 1}


def test_both_instances_are_returned_to_their_pools(diarize_client):
    """A served request leaves both pools exactly as it found them."""
    post_audio(diarize_client)
    assert model_pool.MODEL_POOL.qsize() == 1
    assert model_pool.DIARIZER_POOL.qsize() == 1


def test_a_transcription_failure_still_returns_the_diarizer(diarize_client, monkeypatch, stt_module):
    """The diarizer is released before transcription starts, so its failure cannot strand it."""
    free: list[int] = []

    def raise_runtime_error(bio, model=None, device=None, language=None):
        """Stand in for stt.get_stt_segments(), note how many diarizers are free, and fail."""
        free.append(model_pool.DIARIZER_POOL.qsize())
        raise RuntimeError("transcription exploded")

    monkeypatch.setattr(stt_module, "get_stt_segments", raise_runtime_error)

    resp = post_audio(diarize_client)
    assert resp.status_code == 500
    assert resp.get_json()["error"] == "Transcription failed"
    assert "transcription exploded" not in resp.get_data(as_text=True)
    assert free == [1]
    assert model_pool.MODEL_POOL.qsize() == 1
    assert model_pool.DIARIZER_POOL.qsize() == 1


def test_diarizer_pool_exhausted(diarize_client, monkeypatch):
    """No free diarizer is a 503, and no transcription model is borrowed for nothing."""

    def raise_queue_empty(*args, **kwargs):
        """Stand in for Queue.get() and report the pool as exhausted."""
        raise queue.Empty

    monkeypatch.setattr(model_pool.DIARIZER_POOL, "get", raise_queue_empty)
    borrowed: list[str] = []
    refuse_borrowing(monkeypatch, "acquire_model", borrowed)

    resp = post_audio(diarize_client)
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "Service Unavailable"
    assert borrowed == []

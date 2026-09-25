#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POST /api/stt - error paths, success path, leak regression."""

import io
import queue
import re

from tests.helpers import get_default_pool, make_wav

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def assert_error_shape(body):
    """Assert the response carries exactly the generic error category and a request id."""
    assert set(body.keys()) == {"error", "request_id"}
    assert REQ_ID_RE.match(body["request_id"])


def raise_runtime_error(bio, model=None, device=None, language=None):
    """Stand in for stt.get_stt_result() and fail, to exercise the 500 path."""
    raise RuntimeError("transcription exploded")


def test_no_body(client):
    """A request with neither a file field nor a body is a 400."""
    resp = client.post("/api/stt")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "No audio data"
    assert_error_shape(body)


def test_invalid_audio(client):
    """A payload pydub cannot decode is a 400, not a 500."""
    resp = client.post(
        "/api/stt",
        data={"file": (io.BytesIO(b"not an audio file at all"), "garbage.bin")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Invalid audio data"
    assert_error_shape(body)


def test_success_multipart(client):
    """A multipart upload returns the transcription and the elapsed time."""
    wav = make_wav(duration_ms=50)
    resp = client.post(
        "/api/stt",
        data={"file": (io.BytesIO(wav), "sample.wav")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["text"] == "stub transcription"
    assert "elapsed" in body


def test_success_raw_body(client):
    """A raw audio/* body is accepted just like a multipart upload."""
    wav = make_wav(duration_ms=50)
    resp = client.post("/api/stt", data=wav, content_type="audio/wav")
    assert resp.status_code == 200
    assert resp.get_json()["text"] == "stub transcription"


def test_pool_exhausted(client, monkeypatch):
    """When no model frees up in time the request is a 503, not a hang."""

    def raise_queue_empty(*args, **kwargs):
        """Stand in for Queue.get() and report the pool as exhausted."""
        raise queue.Empty

    monkeypatch.setattr(get_default_pool(), "get", raise_queue_empty)

    wav = make_wav(duration_ms=50)
    resp = client.post(
        "/api/stt",
        data={"file": (io.BytesIO(wav), "sample.wav")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["error"] == "Service Unavailable"
    assert_error_shape(body)


def test_transcription_failure_no_leak(client, monkeypatch, stt_module):
    """A backend failure returns a generic 500 without leaking the exception."""
    monkeypatch.setattr(stt_module, "get_stt_result", raise_runtime_error)

    wav = make_wav(duration_ms=50)
    resp = client.post(
        "/api/stt",
        data={"file": (io.BytesIO(wav), "sample.wav")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "Transcription failed"
    assert_error_shape(body)
    assert "transcription exploded" not in resp.get_data(as_text=True)
    assert "RuntimeError" not in resp.get_data(as_text=True)


def test_model_returned_to_pool_after_failure(client, monkeypatch, stt_module):
    """A failing transcription still returns its model, so the pool cannot drain."""
    monkeypatch.setattr(stt_module, "get_stt_result", raise_runtime_error)

    wav = make_wav(duration_ms=50)
    client.post(
        "/api/stt",
        data={"file": (io.BytesIO(wav), "sample.wav")},
        content_type="multipart/form-data",
    )
    assert get_default_pool().qsize() == 1

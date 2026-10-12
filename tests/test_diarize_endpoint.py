#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POST /api/diarize - the disabled build, the error paths and the segment body."""

import io
import queue
import re

from libs import config, model_pool
from tests.helpers import make_wav

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def assert_error_shape(body):
    """Assert the response carries exactly the generic error category and a request id."""
    assert set(body.keys()) == {"error", "request_id"}
    assert REQ_ID_RE.match(body["request_id"])


def post_audio(client):
    """POST a short silent WAV to /api/diarize as a multipart upload."""
    return client.post(
        "/api/diarize",
        data={"file": (io.BytesIO(make_wav(duration_ms=50)), "meeting.wav")},
        content_type="multipart/form-data",
    )


def raise_runtime_error(bio, diarizer=None, threshold=None):
    """Stand in for diarize.diarize_wav() and fail, to exercise the 500 path."""
    raise RuntimeError("diarization exploded")


def test_disabled_build_refuses(client):
    """With DIARIZE_ENABLED false the endpoint is a 503 and says nothing else."""
    resp = post_audio(client)
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["error"] == "Diarization disabled"
    assert_error_shape(body)


def test_no_body(diarize_client):
    """A request with neither a file field nor a body is a 400."""
    resp = diarize_client.post("/api/diarize")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "No audio data"
    assert_error_shape(body)


def test_invalid_audio(diarize_client):
    """A payload pydub cannot decode is a 400, not a 500."""
    resp = diarize_client.post(
        "/api/diarize",
        data={"file": (io.BytesIO(b"not an audio file at all"), "garbage.bin")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Invalid audio data"
    assert_error_shape(body)


def test_success_returns_segments(diarize_client):
    """A decodable upload returns the speaker turns, the speaker count and the elapsed time."""
    resp = post_audio(diarize_client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["segments"] == [
        {"speaker": 0, "start": 0.0, "end": 1.2},
        {"speaker": 1, "start": 1.0, "end": 2.5},
    ]
    assert body["speakers"] == 2
    assert "elapsed" in body


def test_success_raw_body(diarize_client):
    """A raw audio/* body is accepted just like a multipart upload."""
    resp = diarize_client.post("/api/diarize", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert resp.get_json()["speakers"] == 2


def test_pool_exhausted(diarize_client, monkeypatch):
    """When no diarizer frees up in time the request is a 503, not a hang."""

    def raise_queue_empty(*args, **kwargs):
        """Stand in for Queue.get() and report the pool as exhausted."""
        raise queue.Empty

    monkeypatch.setattr(model_pool.DIARIZER_POOL, "get", raise_queue_empty)

    resp = post_audio(diarize_client)
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["error"] == "Service Unavailable"
    assert_error_shape(body)


def test_failure_no_leak(diarize_client, monkeypatch, diarize_module):
    """A backend failure returns a generic 500 without leaking the exception."""
    monkeypatch.setattr(diarize_module, "diarize_wav", raise_runtime_error)

    resp = post_audio(diarize_client)
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "Diarization failed"
    assert_error_shape(body)
    assert "diarization exploded" not in resp.get_data(as_text=True)
    assert "RuntimeError" not in resp.get_data(as_text=True)


def test_diarizer_returned_to_pool_after_failure(diarize_client, monkeypatch, diarize_module):
    """A failing diarization still returns its instance, so the pool cannot drain."""
    monkeypatch.setattr(diarize_module, "diarize_wav", raise_runtime_error)

    post_audio(diarize_client)
    assert model_pool.DIARIZER_POOL.qsize() == 1


def test_health_reports_diarization_off(client):
    """The health body says diarization is off and offers no diarizer counters."""
    body = client.get("/api/health").get_json()
    assert body["diarize"] is False
    assert "diarize_pool_size" not in body
    assert "diarize_available" not in body


def test_health_reports_diarization_on(diarize_client):
    """With diarization on the health body gains its pool counters."""
    body = diarize_client.get("/api/health").get_json()
    assert body["diarize"] is True
    assert body["diarize_pool_size"] == 1
    assert body["diarize_available"] == 1


def test_requires_token_when_configured(diarize_client, monkeypatch):
    """With STT_TOKENS set the endpoint is behind the same auth as /api/stt."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    assert post_audio(diarize_client).status_code == 401


def test_valid_token_is_accepted(diarize_client, monkeypatch):
    """A configured token gets through to the segments."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    resp = diarize_client.post(
        "/api/diarize",
        data={"file": (io.BytesIO(make_wav(duration_ms=50)), "meeting.wav")},
        content_type="multipart/form-data",
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200


def test_backend_receives_the_converted_wav_and_the_pooled_diarizer(diarize_client, monkeypatch, diarize_module):
    """The route must hand over the converted buffer and the borrowed instance, not the raw upload."""
    seen = {}

    def capture(bio, diarizer=None, threshold=None):
        """Stand in for diarize_wav and record what the route passed."""
        seen["header"] = bio.read(4)
        seen["diarizer"] = diarizer
        return []

    monkeypatch.setattr(diarize_module, "diarize_wav", capture)

    resp = diarize_client.post(
        "/api/diarize",
        data={"file": (io.BytesIO(make_wav(duration_ms=50)), "meeting.mp3")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    # convert_to_wav always hands on a RIFF WAV, whatever the upload claimed to be.
    assert seen["header"] == b"RIFF"
    assert seen["diarizer"] == "diarizer-sentinel"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POST /api/stt — error paths, success path, leak regression."""

import io
import queue
import re

from tests.conftest import make_wav

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _assert_error_shape(body):
    assert set(body.keys()) == {"error", "request_id"}
    assert REQ_ID_RE.match(body["request_id"])


def test_no_body(client):
    resp = client.post("/api/stt")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "No audio data"
    _assert_error_shape(body)


def test_invalid_audio(client):
    resp = client.post(
        "/api/stt",
        data={"file": (io.BytesIO(b"not an audio file at all"), "garbage.bin")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Invalid audio data"
    _assert_error_shape(body)


def test_success_multipart(client):
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
    wav = make_wav(duration_ms=50)
    resp = client.post("/api/stt", data=wav, content_type="audio/wav")
    assert resp.status_code == 200
    assert resp.get_json()["text"] == "stub transcription"


def test_pool_exhausted(client, monkeypatch):
    import stt_server

    def _empty(*args, **kwargs):
        raise queue.Empty

    monkeypatch.setattr(stt_server.MODEL_POOL, "get", _empty)

    wav = make_wav(duration_ms=50)
    resp = client.post(
        "/api/stt",
        data={"file": (io.BytesIO(wav), "sample.wav")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["error"] == "Service Unavailable"
    _assert_error_shape(body)


def test_transcription_failure_no_leak(client, monkeypatch, stt_module):
    secret = "INTERNAL-TRACEBACK-MARKER-9876"

    def _boom(bio, model=None, device=None):
        raise RuntimeError(secret)

    monkeypatch.setattr(stt_module, "get_stt_bio", _boom)

    wav = make_wav(duration_ms=50)
    resp = client.post(
        "/api/stt",
        data={"file": (io.BytesIO(wav), "sample.wav")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "Transcription failed"
    _assert_error_shape(body)
    assert secret not in resp.get_data(as_text=True)
    assert "RuntimeError" not in resp.get_data(as_text=True)


def test_model_returned_to_pool_after_failure(client, monkeypatch, stt_module):
    import stt_server

    def _boom(bio, model=None, device=None):
        raise RuntimeError("x")

    monkeypatch.setattr(stt_module, "get_stt_bio", _boom)

    wav = make_wav(duration_ms=50)
    client.post(
        "/api/stt",
        data={"file": (io.BytesIO(wav), "sample.wav")},
        content_type="multipart/form-data",
    )
    assert stt_server.MODEL_POOL.qsize() == 1

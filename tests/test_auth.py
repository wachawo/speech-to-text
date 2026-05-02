#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optional static-token auth via STT_TOKENS / Authorization: Bearer."""

import io
import re

from tests.conftest import make_wav

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _post_audio(client, headers=None):
    wav = make_wav(duration_ms=50)
    return client.post(
        "/api/stt",
        data={"file": (io.BytesIO(wav), "sample.wav")},
        content_type="multipart/form-data",
        headers=headers or {},
    )


def test_no_tokens_allows_all(client):
    resp = _post_audio(client)
    assert resp.status_code == 200
    assert resp.get_json()["text"] == "stub transcription"


def test_missing_token_when_required(client, monkeypatch):
    import stt_server

    monkeypatch.setattr(stt_server, "STT_TOKENS", {"secret"})
    resp = _post_audio(client)
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["error"] == "Unauthorized"
    assert REQ_ID_RE.match(body["request_id"])
    assert set(body.keys()) == {"error", "request_id"}


def test_invalid_token(client, monkeypatch):
    import stt_server

    monkeypatch.setattr(stt_server, "STT_TOKENS", {"secret"})
    resp = _post_audio(client, headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Unauthorized"


def test_invalid_scheme(client, monkeypatch):
    import stt_server

    monkeypatch.setattr(stt_server, "STT_TOKENS", {"secret"})
    resp = _post_audio(client, headers={"Authorization": "Basic c2VjcmV0"})
    assert resp.status_code == 401


def test_valid_token(client, monkeypatch):
    import stt_server

    monkeypatch.setattr(stt_server, "STT_TOKENS", {"secret"})
    resp = _post_audio(client, headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert resp.get_json()["text"] == "stub transcription"


def test_health_does_not_require_token(client, monkeypatch):
    import stt_server

    monkeypatch.setattr(stt_server, "STT_TOKENS", {"secret"})
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"

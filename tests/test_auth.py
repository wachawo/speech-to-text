#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optional static-token auth via STT_TOKENS / Authorization: Bearer."""

import io
import re

from libs import config
from libs.auth import is_valid_token
from tests.helpers import make_wav

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def post_audio(client, headers=None):
    """POST a short silent WAV to /api/stt with the given headers."""
    wav = make_wav(duration_ms=50)
    return client.post(
        "/api/stt",
        data={"file": (io.BytesIO(wav), "sample.wav")},
        content_type="multipart/form-data",
        headers=headers or {},
    )


def test_no_tokens_allows_all(client):
    """An empty STT_TOKENS means auth is disabled and any request is served."""
    resp = post_audio(client)
    assert resp.status_code == 200
    assert resp.get_json()["text"] == "stub transcription"


def test_missing_token_when_required(client, monkeypatch):
    """A configured token turns a header-less request into a 401 with the generic body."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    resp = post_audio(client)
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["error"] == "Unauthorized"
    assert REQ_ID_RE.match(body["request_id"])
    assert set(body.keys()) == {"error", "request_id"}


def test_invalid_token(client, monkeypatch):
    """A bearer token that is not in STT_TOKENS is rejected."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    resp = post_audio(client, headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Unauthorized"


def test_invalid_scheme(client, monkeypatch):
    """Only the Bearer scheme is accepted, even when the credentials would match."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    resp = post_audio(client, headers={"Authorization": "Basic c2VjcmV0"})
    assert resp.status_code == 401


def test_valid_token(client, monkeypatch):
    """A token present in STT_TOKENS is served normally."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    resp = post_audio(client, headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert resp.get_json()["text"] == "stub transcription"


def test_health_does_not_require_token(client, monkeypatch):
    """Healthchecks stay open so docker-compose keeps working with auth enabled."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_non_ascii_token_is_rejected_not_crashed(client, monkeypatch):
    """A bearer with non-ASCII characters is a plain 401, not a TypeError from hmac.compare_digest."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    resp = post_audio(client, headers={"Authorization": "Bearer caf\u00e9"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Unauthorized"


def test_health_with_non_ascii_token_stays_open(client, monkeypatch):
    """The open health endpoint answers 200 with the non-detailed body whatever the Authorization header holds."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    resp = client.get("/api/health", headers={"Authorization": "Bearer caf\u00e9"})
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "pool_size": 1, "available": 1, "diarize": False}


def test_non_ascii_configured_token_matches_itself(monkeypatch):
    """A token with non-ASCII characters in STT_TOKENS is compared like any other, byte for byte."""
    monkeypatch.setattr(config, "STT_TOKENS", {"caf\u00e9"})
    assert is_valid_token("caf\u00e9")
    assert not is_valid_token("cafe")
    assert not is_valid_token("")


def test_a_lone_surrogate_token_matches_nothing(monkeypatch):
    """A JSON string may hold a lone surrogate no encoding carries; it is an invalid token, not a crash."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    assert not is_valid_token("\ud800")
    assert not is_valid_token("secret\udfff")

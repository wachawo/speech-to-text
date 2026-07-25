#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POST /api/stt — per-request ``language`` option."""

import io
import re

from tests.conftest import make_wav

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def capture_language(stt_module, monkeypatch) -> dict:
    """Swap get_stt_bio for a stub that records the language it was called with."""
    seen = {}

    def record_language(bio, model=None, device=None, language=None):
        """Stand in for stt.get_stt_bio() and remember the language argument."""
        seen["language"] = language
        return "stub transcription"

    monkeypatch.setattr(stt_module, "get_stt_bio", record_language)
    return seen


def test_language_query_passed(client, stt_module, monkeypatch):
    """?language=ru reaches the backend unchanged."""
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post("/api/stt?language=ru", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen["language"] == "ru"


def test_language_form_field_passed(client, stt_module, monkeypatch):
    """A multipart ``language`` field works the same as the query string."""
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post(
        "/api/stt",
        data={"file": (io.BytesIO(make_wav()), "sample.wav"), "language": "ru"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert seen["language"] == "ru"


def test_language_default_none(client, stt_module, monkeypatch):
    """Without the option the backend receives None and applies WHISPER_LANGUAGE."""
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post("/api/stt", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen["language"] is None


def test_language_auto_passed(client, stt_module, monkeypatch):
    """``auto`` is lower-cased and forwarded; autodetect is resolved in libs/stt.py."""
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post("/api/stt?language=AUTO", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen["language"] == "auto"


def test_language_empty_is_none(client, stt_module, monkeypatch):
    """An empty value is treated as "not given"."""
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post("/api/stt?language=", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen["language"] is None


def test_invalid_language_400(client):
    """Anything that is not an ISO-like code or ``auto`` is rejected before Whisper sees it."""
    resp = client.post("/api/stt?language=russian", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Invalid language"
    assert set(body.keys()) == {"error", "request_id"}
    assert REQ_ID_RE.match(body["request_id"])

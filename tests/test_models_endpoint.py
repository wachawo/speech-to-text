#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GET /api/models - the capability catalogue a client reads to know what the server has."""

import re

from libs import config, model_pool

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def rows_by_backend(body):
    """Index the catalogue rows by their backend name."""
    return {row["backend"]: row for row in body["models"]}


def test_lists_whisper_with_its_languages(client):
    """The transcription backend is reported with a per-backend language list."""
    body = client.get("/api/models").get_json()
    assert body["default"] == "whisper"
    whisper_row = rows_by_backend(body)["whisper"]
    assert whisper_row["languages"] == ["en", "ru"]
    assert whisper_row["accepts_language"] is True
    assert whisper_row["default"] is True


def test_pool_state_promotes_status_to_loaded(client):
    """A model waiting in the pool reads as loaded, not merely installed."""
    whisper_row = rows_by_backend(client.get("/api/models").get_json())["whisper"]
    assert whisper_row["status"] == "loaded"


def test_empty_pool_falls_back_to_the_backend_status(client, monkeypatch):
    """With nothing loaded the row reports what the backend itself said."""
    monkeypatch.setattr(model_pool.MODEL_POOL, "empty", lambda: True)
    whisper_row = rows_by_backend(client.get("/api/models").get_json())["whisper"]
    assert whisper_row["status"] == "installed"


def test_diarizer_absent_when_disabled(client):
    """A deployment with diarization off does not advertise a diarizer at all."""
    body = client.get("/api/models").get_json()
    assert "diarize" not in rows_by_backend(body)


def test_diarizer_listed_when_enabled(diarize_client):
    """With diarization on the row appears, with no languages and the speaker ceiling."""
    body = diarize_client.get("/api/models").get_json()
    diarizer_row = rows_by_backend(body)["diarize"]
    assert diarizer_row["status"] == "loaded"
    assert diarizer_row["languages"] is None
    assert diarizer_row["accepts_language"] is False
    assert diarizer_row["max_speakers"] == 8


def test_languages_are_never_merged_across_backends(diarize_client):
    """Each row carries its own list; a union would be wrong for every backend on its own."""
    body = diarize_client.get("/api/models").get_json()
    assert "languages" not in body
    assert {row["backend"] for row in body["models"]} == {"whisper", "parakeet", "diarize"}


def test_an_inactive_transcriber_is_listed_but_not_default(client):
    """Parakeet appears in the catalogue even when Whisper is the one serving requests."""
    parakeet_row = rows_by_backend(client.get("/api/models").get_json())["parakeet"]
    assert parakeet_row["default"] is False
    assert parakeet_row["status"] == "absent"


def test_a_self_detecting_backend_says_it_takes_no_language(client):
    """accepts_language is what stops ?language= from being a promise nothing keeps."""
    parakeet_row = rows_by_backend(client.get("/api/models").get_json())["parakeet"]
    assert parakeet_row["accepts_language"] is False
    assert parakeet_row["languages_source"].startswith("model card")


def test_switching_the_backend_moves_the_default(client, monkeypatch):
    """STT_BACKEND selects which row is the default and which the catalogue reports."""
    monkeypatch.setattr(config, "STT_BACKEND", "parakeet")
    body = client.get("/api/models").get_json()
    assert body["default"] == "parakeet"
    assert rows_by_backend(body)["parakeet"]["default"] is True
    assert rows_by_backend(body)["whisper"]["default"] is False


def test_an_unknown_backend_name_falls_back(client, monkeypatch):
    """A typo in STT_BACKEND serves Whisper and says so, rather than failing to start."""
    monkeypatch.setattr(config, "STT_BACKEND", "parrakeet")
    assert client.get("/api/models").get_json()["default"] == "whisper"


def test_a_backend_that_cannot_describe_itself_is_skipped(client, monkeypatch, stt_module):
    """One broken optional backend must not take the whole catalogue down."""

    def raise_runtime_error():
        """Stand in for describe_backend() and fail."""
        raise RuntimeError("describe exploded")

    monkeypatch.setattr(stt_module, "describe_backend", raise_runtime_error)

    resp = client.get("/api/models")
    assert resp.status_code == 200
    body = resp.get_json()
    # The broken row is gone and the others survived it.
    assert "whisper" not in rows_by_backend(body)
    assert "parakeet" in rows_by_backend(body)
    assert "describe exploded" not in resp.get_data(as_text=True)


def test_requires_a_token_when_configured(client, monkeypatch):
    """The catalogue publishes configuration, so it sits behind the same token as the rest."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    assert client.get("/api/models").status_code == 401
    body = client.get("/api/models").get_json()
    assert set(body.keys()) == {"error", "request_id"}
    assert REQ_ID_RE.match(body["request_id"])

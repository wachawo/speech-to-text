#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GET /api/models - the capability catalogue a client reads to know what the server has."""

import queue
import re

from libs import config, model_pool
from tests.helpers import get_default_pool

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def rows_by_backend(body):
    """Index the catalogue rows by their backend name."""
    return {row["backend"]: row for row in body["models"]}


def rows_by_id(body):
    """Index the catalogue rows by their model id."""
    return {row["id"]: row for row in body["models"]}


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
    monkeypatch.setattr(get_default_pool(), "qsize", lambda: 0)
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

    def raise_runtime_error(model_name=None):
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


def test_every_loaded_model_has_its_own_row(multi_client):
    """Three loaded models are three selectable rows, each with its own pool counters."""
    rows = rows_by_id(multi_client.get("/api/models").get_json())
    expected = {"small.en-stub": 1, "tiny.en": 2, "nvidia/parakeet-tdt-0.6b-v3": 1}
    for model_id, size in expected.items():
        assert rows[model_id]["status"] == "loaded"
        assert rows[model_id]["selectable"] is True
        assert rows[model_id]["pool_size"] == size
        assert rows[model_id]["available"] == size


def test_exactly_one_row_is_the_default(multi_client):
    """`default_model` names the one default row, and `default` stays that row's backend."""
    body = multi_client.get("/api/models").get_json()
    defaults = [row for row in body["models"] if row["default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == body["default_model"] == "small.en-stub"
    assert body["default"] == defaults[0]["backend"]


def test_each_model_row_carries_its_own_languages(multi_client):
    """An English-only model and a multilingual one sit side by side, and nothing is merged."""
    body = multi_client.get("/api/models").get_json()
    rows = rows_by_id(body)
    assert rows["tiny.en"]["languages"] == ["en"]
    assert rows["small.en-stub"]["languages"] == ["en", "ru"]
    assert "languages" not in body


def test_a_busy_model_stays_loaded(multi_client, monkeypatch):
    """Every instance in flight empties the queue, and the model is no less loaded for it."""
    monkeypatch.setitem(model_pool.MODEL_POOLS, "tiny.en", queue.Queue())
    monkeypatch.setitem(model_pool.MODELS_LOADED, "tiny.en", 2)
    row = rows_by_id(multi_client.get("/api/models").get_json())["tiny.en"]
    assert row["status"] == "loaded"
    assert row["available"] == 0


def test_an_unconfigured_backend_is_not_selectable(client):
    """In a single-model deployment the Parakeet row describes, but a request cannot pick it."""
    rows = rows_by_backend(client.get("/api/models").get_json())
    assert rows["parakeet"]["selectable"] is False
    assert rows["parakeet"]["pool_size"] == 0
    assert rows["whisper"]["selectable"] is True


def test_one_broken_model_does_not_hide_the_others(multi_client, monkeypatch, stt_module):
    """A model that cannot describe itself is skipped alone, and its error stays in the log."""
    original = stt_module.describe_backend

    def describe_or_fail(model_name=None):
        """Stand in for describe_backend() and fail for tiny.en only."""
        if model_name == "tiny.en":
            raise RuntimeError("describe exploded")
        return original(model_name)

    monkeypatch.setattr(stt_module, "describe_backend", describe_or_fail)
    resp = multi_client.get("/api/models")
    rows = rows_by_id(resp.get_json())
    assert "tiny.en" not in rows
    assert {"small.en-stub", "nvidia/parakeet-tdt-0.6b-v3"} <= set(rows)
    assert "describe exploded" not in resp.get_data(as_text=True)


def test_a_path_entry_never_reaches_the_catalogue(client, monkeypatch):
    """A file-path entry is listed under its basename; the host directory appears nowhere."""
    monkeypatch.setattr(config, "STT_MODELS", config.parse_model_list("whisper:/opt/models/Custom.pt@1"))
    monkeypatch.setattr(model_pool, "MODEL_POOLS", {"Custom": queue.Queue()})
    resp = client.get("/api/models")
    row = rows_by_id(resp.get_json())["Custom"]
    assert row["model"] == "Custom"
    assert "/opt/models" not in resp.get_data(as_text=True)

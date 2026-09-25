#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Health endpoint."""

# Local imports
from libs import config


def test_health_ok(client):
    """The endpoint reports the configured pool size and how many models are free."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["pool_size"] == 1
    assert body["available"] == 1
    assert body["default_model"] == "small.en-stub"
    assert body["models"] == {"small.en-stub": {"backend": "whisper", "pool_size": 1, "available": 1}}


def test_health_reports_every_model_and_the_default_on_top(multi_client):
    """With several models the top-level counters are the default model's, and each model has its own."""
    body = multi_client.get("/api/health").get_json()
    assert body["default_model"] == "small.en-stub"
    assert body["pool_size"] == 1
    assert body["available"] == 1
    assert body["models"] == {
        "small.en-stub": {"backend": "whisper", "pool_size": 1, "available": 1},
        "tiny.en": {"backend": "whisper", "pool_size": 2, "available": 2},
        "nvidia/parakeet-tdt-0.6b-v3": {"backend": "parakeet", "pool_size": 1, "available": 1},
    }
    assert "diarize_pool_size" not in body


def test_health_hides_the_model_list_from_a_caller_without_the_token(client, monkeypatch):
    """With auth on, the open endpoint keeps its legacy counters and leaves the configuration to token holders."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    body = client.get("/api/health").get_json()
    assert body == {"status": "ok", "pool_size": 1, "available": 1, "diarize": False}
    wrong = client.get("/api/health", headers={"Authorization": "Bearer wrong"}).get_json()
    assert "models" not in wrong


def test_health_shows_the_model_list_to_a_token_holder(client, monkeypatch):
    """A caller that /api/models would serve also gets `default_model` and `models` from health."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    body = client.get("/api/health", headers={"Authorization": "Bearer secret"}).get_json()
    assert body["default_model"] == "small.en-stub"
    assert set(body["models"]) == {"small.en-stub"}

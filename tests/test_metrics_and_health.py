#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GET /metrics and the deep health check: what an operator watches, and what it costs to ask."""

import queue

import stt_server
from libs import config, model_pool


def scrape(client) -> str:
    """The metrics page as text."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/plain")
    return response.get_data(as_text=True)


def test_metrics_count_requests_by_route_not_path(client):
    """A request is counted under its route's rule; an unknown path under one shared label."""
    client.get("/api/models")
    client.get("/api/does-not-exist-12345")
    text = scrape(client)
    assert 'stt_requests_total{method="GET",route="/api/models",status="200"}' in text
    assert 'route="unmatched"' in text
    assert "does-not-exist-12345" not in text


def test_metrics_count_errors_by_category(client):
    """An error response is counted under the category the client received."""
    client.post("/api/stt")
    assert 'stt_errors_total{category="No audio data"}' in scrape(client)


def test_metrics_report_pools_and_sessions_at_scrape_time(client):
    """Pool sizes and running live sessions are read when scraped."""
    text = scrape(client)
    assert "stt_pool_pool_size 1.0" in text
    assert "stt_pool_available 1.0" in text
    assert 'stt_stream_sessions_active{source="any"} 0.0' in text


def test_metrics_need_no_token(client, monkeypatch):
    """Like /api/health, the scrape stays open when STT_TOKENS is set."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    assert client.get("/metrics").status_code == 200


def test_plain_health_does_no_model_work(client, monkeypatch, stt_module):
    """Without ?deep the health check never touches a model."""

    def fail_if_called(*args, **kwargs):
        """The plain check must not transcribe."""
        raise AssertionError("transcribed during a plain health check")

    monkeypatch.setattr(stt_module, "get_stt_segments", fail_if_called)
    body = client.get("/api/health").get_json()
    assert "deep" not in body and body["status"] == "ok"


def test_deep_health_runs_the_transcriber_once(client):
    """?deep=1 pushes silence through the transcriber, returns the model, and reports ok."""
    response = client.get("/api/health?deep=1")
    assert response.status_code == 200
    assert response.get_json()["deep"] == {"transcriber": "ok"}
    assert model_pool.MODEL_POOL.qsize() == 1


def test_deep_health_reports_a_busy_pool_as_busy(client, monkeypatch):
    """A pool with no free model is busy, not broken: still 200."""
    monkeypatch.setattr(model_pool, "MODEL_POOL", queue.Queue())
    monkeypatch.setattr(stt_server, "DEEP_CHECK_TIMEOUT", 0.01)
    response = client.get("/api/health?deep=1")
    assert response.status_code == 200
    assert response.get_json()["deep"] == {"transcriber": "busy"}


def test_deep_health_reports_a_failing_model_with_503(client, monkeypatch, stt_module):
    """A model that raises is a failed check: 503, and the model still goes back to the pool."""

    def broken_segments(bio, model=None, device=None, language=None):
        """Fail like a CUDA error would."""
        raise RuntimeError("CUDA error: device-side assert triggered")

    monkeypatch.setattr(stt_module, "get_stt_segments", broken_segments)
    response = client.get("/api/health?deep=1")
    assert response.status_code == 503
    assert response.get_json()["status"] == "failed"
    assert model_pool.MODEL_POOL.qsize() == 1


def test_deep_health_checks_the_diarizer_when_enabled(diarize_client):
    """With diarization on, the diarizer is exercised too."""
    body = diarize_client.get("/api/health?deep=1").get_json()
    assert body["deep"] == {"transcriber": "ok", "diarizer": "ok"}


def test_deep_health_needs_the_token_when_tokens_are_set(client, monkeypatch):
    """Deep checks cost GPU work: with STT_TOKENS set they need a token; the plain check does not."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health?deep=1").status_code == 401
    authorized = client.get("/api/health?deep=1", headers={"Authorization": "Bearer secret"})
    assert authorized.status_code == 200


def test_the_asgi_app_is_exported_for_gunicorn():
    """`stt_server:asgi_app` exists for `gunicorn --worker-class uvicorn_worker.UvicornWorker`."""
    assert callable(stt_server.asgi_app)

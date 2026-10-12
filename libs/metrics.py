#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prometheus metrics for GET /metrics: requests, errors, pools, per-model latency, live sessions, dropped text.

Counters are process-local. Under gunicorn every worker keeps its own and a scrape reaches one of
them, which is fine for the default single-process deployment and says so in the README.
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

logger = logging.getLogger(__name__)

# Requests by the route's rule, not its path: a path label would grow a series per 404 probe.
REQUESTS = Counter("stt_requests_total", "HTTP requests answered", ["route", "method", "status"])
REQUEST_SECONDS = Histogram(
    "stt_request_seconds",
    "Time to answer an HTTP request",
    ["route"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600),
)
ERRORS = Counter("stt_errors_total", "Error responses by category", ["category"])
STREAM_SESSIONS = Counter("stt_stream_sessions_total", "Live sessions started", ["source"])
DROPPED_SEGMENTS = Counter("stt_speech_gate_dropped_total", "Transcribed segments dropped as not spoken")
SKIPPED_SECONDS = Counter("stt_stream_skipped_seconds_total", "Queued live audio shed by a session that fell behind")
JOBS = Counter("stt_jobs_total", "Background jobs by the status they reached", ["status"])

# Series labelled with a model id live in a registry of their own: the ids name the deployment's
# models, so render() adds this registry only to a scrape that LIVE_STATE["detailed"] lets see them.
MODEL_REGISTRY = CollectorRegistry()

# Fine at the short end, where a 1-3 s phrase is decoded in 0.08-0.5 s, and up to the default
# STT_QUEUE_TIMEOUT, so a wait that ran out still lands below +Inf.
MODEL_SECONDS_BUCKETS = (0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.75, 1, 2.5, 5, 10, 30, 60, 120)
INFERENCE_SECONDS = Histogram(
    "stt_model_inference_seconds",
    "Time one model call took to transcribe its audio",
    ["model", "backend"],
    buckets=MODEL_SECONDS_BUCKETS,
    registry=MODEL_REGISTRY,
)
WAIT_SECONDS = Histogram(
    "stt_model_wait_seconds",
    "Time spent waiting for a free instance of a model, whether one came or not",
    ["model"],
    buckets=MODEL_SECONDS_BUCKETS,
    registry=MODEL_REGISTRY,
)
WAIT_TIMEOUTS = Counter(
    "stt_model_wait_timeouts_total",
    "Waits for a free instance of a model that gave up",
    ["model"],
    registry=MODEL_REGISTRY,
)

# Filled in by the modules that own the numbers, so this one imports none of them. `detailed` says
# whether the scrape being answered may see series labelled with model ids.
LIVE_STATE: dict[str, Any] = {
    "pools": lambda: {},
    "sessions": lambda: 0,
    "url_sessions": lambda: 0,
    "detailed": lambda: False,
}

# The labelled per-model gauges, by the key of each model's entry in the pool status they report.
MODEL_POOL_GAUGES = {"pool_size": "stt_model_pool_size", "available": "stt_model_pool_available"}

UNMATCHED_ROUTE = "unmatched"


def observe_request(route: str | None, method: str, status: int, seconds: float) -> None:
    """Count one answered request and its duration."""
    label = route or UNMATCHED_ROUTE
    REQUESTS.labels(route=label, method=method, status=str(status)).inc()
    REQUEST_SECONDS.labels(route=label).observe(seconds)


def count_error(category: str) -> None:
    """Count one error response by its category, the same string the client receives."""
    ERRORS.labels(category=category).inc()


def observe_wait(model_id: str, seconds: float, served: bool) -> None:
    """Record one wait for an instance of a model, counting it as given up when none came."""
    WAIT_SECONDS.labels(model=model_id).observe(seconds)
    if not served:
        WAIT_TIMEOUTS.labels(model=model_id).inc()


@contextmanager
def measure_inference(model_id: str, backend: str) -> Iterator[None]:
    """Time the model call made inside the block; a call that raises is not recorded."""
    start_time = time.monotonic()
    yield
    INFERENCE_SECONDS.labels(model=model_id, backend=backend).observe(time.monotonic() - start_time)


def collect_model_pools(models: dict[str, Any]) -> list:
    """One labelled family per pool figure, with a series for every loaded model."""
    families = []
    for key, name in MODEL_POOL_GAUGES.items():
        family = GaugeMetricFamily(
            name, f"Model pool of each loaded model: {key.replace('_', ' ')}", labels=["model", "backend"]
        )
        for model_id, pool in models.items():
            family.add_metric([model_id, pool["backend"]], pool[key])
        families.append(family)
    return families


def collect_live_gauges() -> list:
    """The gauges read at scrape time: pool sizes and free instances, running live sessions.

    The unlabelled stt_pool_* gauges describe the default model's pool and the diarizer, as they
    did before several models could be loaded; stt_model_pool_size and stt_model_pool_available
    carry every model the pool status lists under `models`, labelled with its id and backend, and
    are empty when it lists none - stt_server lists them only to a scrape that may see them.
    """
    pools = LIVE_STATE["pools"]()
    families = []
    for name, value in pools.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        family = GaugeMetricFamily(f"stt_pool_{name}", f"Model pool: {name.replace('_', ' ')}")
        family.add_metric([], value)
        families.append(family)
    families.extend(collect_model_pools(pools.get("models") or {}))
    sessions = GaugeMetricFamily("stt_stream_sessions_active", "Live sessions running now", labels=["source"])
    sessions.add_metric(["any"], LIVE_STATE["sessions"]())
    sessions.add_metric(["url"], LIVE_STATE["url_sessions"]())
    families.append(sessions)
    return families


class LiveGauges(Collector):
    """The scrape-time gauges as a prometheus_client collector - a framework subclass, the one kind of
    class this project allows: the registry keeps collectors in a dict and calls their collect()."""

    def collect(self):
        """Hand the registry the gauges as they are at this scrape."""
        return collect_live_gauges()


def register_live_gauges() -> None:
    """Register the scrape-time gauges once per process."""
    try:
        REGISTRY.register(LiveGauges())
    except ValueError as exc:
        # Registering twice in one process raises this; so does a name that collides with another
        # metric's, which would silently drop the gauges - hence a warning, not a debug line.
        logger.warning("Live gauges not registered: %s", exc)


def render() -> tuple[bytes, str]:
    """The current metrics in the Prometheus text format, with its content type.

    The per-model latency series follow the rule of the per-model gauges: a scrape that may not
    see model ids gets none of them, not even their HELP lines, rather than a total under some
    placeholder label - stt_request_seconds already gives it latency by route.
    """
    body = generate_latest(REGISTRY)
    if LIVE_STATE["detailed"]():
        body += generate_latest(MODEL_REGISTRY)
    return body, CONTENT_TYPE_LATEST


def main():
    """No-op entry point: this module is imported for its metrics."""
    pass


if __name__ == "__main__":
    main()

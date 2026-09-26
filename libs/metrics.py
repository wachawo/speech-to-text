#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prometheus metrics for GET /metrics: requests, errors, pools, live sessions, dropped text.

Counters are process-local. Under gunicorn every worker keeps its own and a scrape reaches one of
them, which is fine for the default single-process deployment and says so in the README.
"""

import logging
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest
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

# Filled in by the modules that own the numbers, so this one imports none of them.
LIVE_STATE: dict[str, Any] = {"pools": lambda: {}, "sessions": lambda: 0, "url_sessions": lambda: 0}

UNMATCHED_ROUTE = "unmatched"


def observe_request(route: str | None, method: str, status: int, seconds: float) -> None:
    """Count one answered request and its duration."""
    label = route or UNMATCHED_ROUTE
    REQUESTS.labels(route=label, method=method, status=str(status)).inc()
    REQUEST_SECONDS.labels(route=label).observe(seconds)


def count_error(category: str) -> None:
    """Count one error response by its category, the same string the client receives."""
    ERRORS.labels(category=category).inc()


def collect_live_gauges() -> list:
    """The gauges read at scrape time: pool sizes and free instances, running live sessions."""
    pools = LIVE_STATE["pools"]()
    families = []
    for name, value in pools.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        family = GaugeMetricFamily(f"stt_pool_{name}", f"Model pool: {name.replace('_', ' ')}")
        family.add_metric([], value)
        families.append(family)
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
    """The current metrics in the Prometheus text format, with its content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def main():
    """No-op entry point: this module is imported for its metrics."""
    pass


if __name__ == "__main__":
    main()

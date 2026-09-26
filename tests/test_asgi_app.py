#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stt_server.build_asgi_app: HTTP goes to Flask, /api/stream to the live handler, any other socket is refused."""

import asyncio
import json

import pytest

# Local imports
import stt_server
from libs import config, live


@pytest.fixture
def asgi_app(monkeypatch):
    """The ASGI app uvicorn would serve, over the real Flask app, with diarization pinned off."""
    monkeypatch.setattr(config, "DIARIZE_ENABLED", False)
    return stt_server.build_asgi_app(stt_server.app.wsgi_app)


@pytest.fixture
def stream_calls(monkeypatch):
    """Replace the live handler with a recorder; returns the (scope, receive, send) of every call."""
    calls: list = []

    async def record_stream(scope, receive, send):
        """Stand in for live.handle_stream."""
        calls.append((scope, receive, send))

    monkeypatch.setattr(live, "handle_stream", record_stream)
    return calls


async def request_http(asgi_app, path: str) -> tuple[int, bytes]:
    """Send one GET through the ASGI app and return the status and body."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    sent: list[dict] = []

    async def receive():
        """The request has no body."""
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        """Record what the app sent."""
        sent.append(message)

    await asyncio.wait_for(asgi_app(scope, receive, send), timeout=10)
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return status, body


async def open_socket(asgi_app, path: str) -> dict:
    """Open one websocket through the ASGI app; returns the scope, the callables, and what was sent."""
    scope = {"type": "websocket", "path": path, "headers": []}
    sent: list[dict] = []

    async def receive():
        """The handshake request, and nothing after it."""
        return {"type": "websocket.connect"}

    async def send(message):
        """Record what the app sent."""
        sent.append(message)

    await asyncio.wait_for(asgi_app(scope, receive, send), timeout=10)
    return {"scope": scope, "receive": receive, "send": send, "sent": sent}


def test_http_goes_to_flask_with_the_full_path(asgi_app):
    """/api/health answers through the ASGI app, which proves Flask saw the path unstripped."""
    status, body = asyncio.run(request_http(asgi_app, "/api/health"))
    assert status == 200
    assert json.loads(body)["status"] == "ok"


def test_http_on_the_stream_path_is_not_the_live_handler(asgi_app, stream_calls):
    """A plain GET on /api/stream is an HTTP request like any other: Flask answers it, not the socket handler."""
    status, body = asyncio.run(request_http(asgi_app, live.STREAM_PATH))
    assert status == 404
    assert set(json.loads(body)) == {"error", "request_id"}
    assert stream_calls == []


def test_the_stream_socket_goes_to_the_live_handler(asgi_app, stream_calls):
    """A websocket on /api/stream is handed, untouched, to live.handle_stream."""
    opened = asyncio.run(open_socket(asgi_app, live.STREAM_PATH))
    assert stream_calls == [(opened["scope"], opened["receive"], opened["send"])]
    assert opened["sent"] == []


@pytest.mark.parametrize("path", ["/api/streams", "/stream", "/api/health", "/"])
def test_any_other_socket_is_refused_before_accept(asgi_app, stream_calls, path):
    """A websocket anywhere else is closed without an accept, which the server turns into a 403."""
    opened = asyncio.run(open_socket(asgi_app, path))
    assert opened["sent"] == [{"type": "websocket.close", "code": live.CLOSE_POLICY}]
    assert stream_calls == []

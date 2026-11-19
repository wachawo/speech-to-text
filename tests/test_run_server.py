#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stt_server.run_server: debug mode runs the Flask dev server without the Werkzeug debugger."""

# Local imports
import stt_server
from libs import config


def test_debug_mode_runs_flask_without_the_werkzeug_debugger(monkeypatch):
    """STT_DEBUG serves through app.run with the reloader's debug mode on and the debugger console off."""
    flask_calls = []
    uvicorn_calls = []

    def record_flask_run(*args, **kwargs):
        """Stand in for app.run, which would block serving."""
        flask_calls.append((args, kwargs))

    def record_uvicorn_run(*args, **kwargs):
        """Stand in for uvicorn.run, which debug mode must not reach."""
        uvicorn_calls.append((args, kwargs))

    monkeypatch.setattr(config, "STT_DEBUG", True)
    monkeypatch.setattr(config, "STT_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "STT_PORT", 5051)
    monkeypatch.setattr(stt_server.app, "run", record_flask_run)
    monkeypatch.setattr(stt_server.uvicorn, "run", record_uvicorn_run)
    stt_server.run_server()
    assert len(flask_calls) == 1
    unused_args, kwargs = flask_calls[0]
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 5051
    assert kwargs["debug"] is True
    assert kwargs["use_debugger"] is False
    assert uvicorn_calls == []

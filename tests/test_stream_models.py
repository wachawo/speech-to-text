#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""/api/stream: the optional `model` of the start message, and the pool every phrase borrows from."""

import asyncio
import json

import numpy as np
import pytest

# Local imports
from libs import config, live, model_pool, stream
from tests.helpers import get_default_pool


def check(start):
    """Run check_start on a start message with no handshake headers."""
    return live.check_start({"headers": []}, {"type": "start", **start})


def test_without_model_the_default_serves(multi_client):
    """An old client that never names a model gets the default model, exactly as before."""
    error, options = check({})
    assert error is None
    assert options["spec"]["id"] == "small.en-stub"
    assert options["language"] is None


@pytest.mark.parametrize(
    ("requested", "model_id"),
    [
        ("tiny.en", "tiny.en"),
        ("TINY.EN", "tiny.en"),
        ("whisper:tiny.en", "tiny.en"),
        ("parakeet", "nvidia/parakeet-tdt-0.6b-v3"),
    ],
)
def test_a_named_model_is_chosen(multi_client, requested, model_id):
    """The start message names a model the way /api/stt does: id, alias, backend:model or backend."""
    error, options = check({"model": requested})
    assert error is None
    assert options["spec"]["id"] == model_id


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        ({"model": "nope"}, "Invalid model"),
        ({"model": "medium"}, "Model not loaded"),
        ({"model": 5}, "Invalid start message"),
        ({"model": "tiny.en", "language": "ru"}, "Unsupported language"),
        ({"model": "parakeet", "language": "de"}, "Unsupported language"),
        ({"model": "tiny.en", "language": "zz"}, "Invalid language"),
    ],
)
def test_refusals(multi_client, start, expected):
    """A bad model, or a language the chosen model does not take, refuses the session."""
    assert check(start) == (expected, {})


def test_an_explicit_language_is_checked_against_the_chosen_model(multi_client):
    """English on an English-only model passes; a Russian hint on Parakeet passes as a hint."""
    assert check({"model": "tiny.en", "language": "en"})[1]["language"] == "en"
    assert check({"model": "parakeet", "language": "ru"})[0] is None


def test_the_token_is_checked_before_the_model(multi_client, monkeypatch):
    """Without a valid token a client learns nothing about which models exist."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    assert check({"model": "nope"}) == ("Unauthorized", {})


def test_a_lone_surrogate_token_is_unauthorized(client, monkeypatch):
    """`"\\ud800"` in the start message is refused as Unauthorized instead of crashing the handshake."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    start = json.loads('{"type": "start", "token": "\\ud800"}')
    assert live.check_start({"headers": []}, start) == ("Unauthorized", {})


def test_an_old_client_is_checked_as_before(client):
    """Without `model` only the shape of the language is checked, exactly as before model selection."""
    error, options = check({"language": "de"})
    assert error is None
    assert options["language"] == "de"
    assert check({"language": "german"})[1]["language"] == "de"
    assert check({"language": "zz"}) == ("Invalid language", {})


def test_a_named_model_limits_the_language(client):
    """Naming the default model explicitly does check the code against its list."""
    assert check({"model": "small.en-stub", "language": "de"}) == ("Unsupported language", {})


def test_an_utterance_borrows_from_the_chosen_models_pool(multi_client, stt_module, monkeypatch):
    """The instance comes from tiny.en's pool, goes back there, and the default pool is untouched."""
    used = []

    def record_segments(bio, model=None, device=None, language=None):
        """Remember which instance transcribed."""
        used.append(model)
        return [{"start": 0.0, "end": 0.5, "text": " hello"}]

    monkeypatch.setattr(stt_module, "get_stt_segments", record_segments)
    buffer = stream.new_buffer()
    stream.append_samples(buffer, np.zeros(stream.SAMPLE_RATE, dtype=np.int16))
    unused_error, options = check({"model": "tiny.en"})
    segments = stream.transcribe_utterance(buffer, {"start": 0, "end": stream.SAMPLE_RATE}, None, options["spec"])
    assert segments == [{"start": 0.0, "end": 0.5, "text": "hello"}]
    assert used == [{"stub_model": "tiny.en"}]
    assert model_pool.MODEL_POOLS["tiny.en"].qsize() == 2
    assert get_default_pool().qsize() == 1


def test_a_parakeet_session_is_transcribed_by_parakeet(multi_client, parakeet_module, monkeypatch):
    """The backend follows the model, not STT_BACKEND."""
    used = []

    def record_segments(bio, model=None, device=None, language=None):
        """Remember that Parakeet was asked."""
        used.append(model)
        return []

    monkeypatch.setattr(parakeet_module, "get_stt_segments", record_segments)
    buffer = stream.new_buffer()
    stream.append_samples(buffer, np.zeros(stream.SAMPLE_RATE, dtype=np.int16))
    unused_error, options = check({"model": "parakeet"})
    stream.transcribe_utterance(buffer, {"start": 0, "end": stream.SAMPLE_RATE}, None, options["spec"])
    assert used == [{"stub_model": "nvidia/parakeet-tdt-0.6b-v3"}]


def run_stream(messages):
    """Drive handle_stream with the given client messages; returns what it sent, decoded."""
    sent = []

    async def receive():
        """The next client message, then silence as if the client were waiting."""
        if messages:
            return messages.pop(0)
        await asyncio.sleep(3600)

    async def send(message):
        """Keep every server message."""
        sent.append(message)

    asyncio.run(live.handle_stream({"type": "websocket", "path": live.STREAM_PATH, "headers": []}, receive, send))
    return [
        json.loads(message["text"]) if message["type"] == "websocket.send" else message
        for message in sent
        if message["type"] in ("websocket.send", "websocket.close")
    ]


def speech_frames(seconds):
    """Loud 16 kHz PCM16 audio as one binary message, which the pause detector takes for speech."""
    count = int(seconds * stream.SAMPLE_RATE)
    tone = (0.3 * 32767 * np.sin(2 * np.pi * 220 * np.arange(count) / stream.SAMPLE_RATE)).astype("<i2")
    return {"type": "websocket.receive", "bytes": tone.tobytes()}


def start_message(**fields):
    """A start message as the client sends it."""
    return {"type": "websocket.receive", "text": json.dumps({"type": "start", **fields})}


def test_an_unknown_model_is_one_error_and_a_close(multi_client):
    """The error has the shape of every HTTP error body and closes as unsupported data."""
    events = run_stream([{"type": "websocket.connect"}, start_message(model="nope")])
    assert events[0]["type"] == "error"
    assert events[0]["error"] == "Invalid model"
    assert set(events[0]) == {"type", "error", "request_id"}
    assert events[1] == {"type": "websocket.close", "code": live.CLOSE_UNSUPPORTED}


def test_a_session_on_a_named_model(multi_client, stt_module, monkeypatch):
    """`ready` names the model, every phrase is transcribed by it, and its pool is whole afterwards."""
    used = []

    def record_segments(bio, model=None, device=None, language=None):
        """Remember which instance transcribed the phrase."""
        used.append(model)
        return [{"start": 0.0, "end": 0.8, "text": " hello"}]

    monkeypatch.setattr(stt_module, "get_stt_segments", record_segments)
    events = run_stream(
        [
            {"type": "websocket.connect"},
            start_message(model="tiny.en", language="en"),
            speech_frames(1.0),
            {"type": "websocket.receive", "text": json.dumps({"type": "stop"})},
        ]
    )
    ready = events[0]
    assert (ready["type"], ready["model"], ready["backend"], ready["language"]) == ("ready", "tiny.en", "whisper", "en")
    segments = [event for event in events if event.get("type") == "segment"]
    assert [segment["text"] for segment in segments] == ["hello"]
    assert used == [{"stub_model": "tiny.en"}]
    assert events[-2]["type"] == "done"
    assert events[-1] == {"type": "websocket.close", "code": live.CLOSE_NORMAL}
    assert model_pool.MODEL_POOLS["tiny.en"].qsize() == 2
    assert get_default_pool().qsize() == 1


def test_ready_names_the_default_model_without_one(client):
    """A session that names no model is told which one serves it."""
    events = run_stream(
        [
            {"type": "websocket.connect"},
            start_message(),
            {"type": "websocket.receive", "text": json.dumps({"type": "stop"})},
        ]
    )
    assert (events[0]["type"], events[0]["model"]) == ("ready", "small.en-stub")
    assert events[1]["type"] == "done"

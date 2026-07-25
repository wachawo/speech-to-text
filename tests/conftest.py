#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test fixtures: stub libs.stt before stt_server is imported, expose a Flask test client."""

import io
import os
import queue
import sys
import types
import wave

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import libs  # noqa: E402  (the real package; only libs.stt below is replaced)


def fake_get_model():
    """Stand in for stt.get_model() — the tests never load real Whisper weights."""
    return object()


def fake_get_stt_bio(bio, model=None, device=None, language=None):
    """Stand in for stt.get_stt_bio() with a fixed transcription."""
    return "stub transcription"


# Replace only libs.stt so the tests need neither torch nor whisper installed.
# Must run before stt_server (and therefore libs.model_pool) is imported anywhere.
fake_stt = types.ModuleType("libs.stt")
fake_stt.get_model = fake_get_model
fake_stt.get_stt_bio = fake_get_stt_bio
sys.modules["libs.stt"] = fake_stt
libs.stt = fake_stt

import stt_server  # noqa: E402  (must follow the libs.stt stub)
from libs import config, model_pool  # noqa: E402  (must follow the libs.stt stub)


@pytest.fixture
def client(monkeypatch):
    """Flask test client backed by a one-slot model pool holding a sentinel model."""
    pool: queue.Queue = queue.Queue()
    pool.put("model-sentinel")
    monkeypatch.setattr(model_pool, "MODEL_POOL", pool)
    monkeypatch.setattr(config, "MODEL_POOL_SIZE", 1)
    return stt_server.app.test_client()


@pytest.fixture
def stt_module():
    """The stubbed libs.stt module, so a test can swap get_stt_bio for its own."""
    return fake_stt


def make_wav(duration_ms: int = 100, sample_rate: int = 16000) -> bytes:
    """Build a valid silent 16-bit mono PCM WAV using stdlib wave."""
    n_frames = int(sample_rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()

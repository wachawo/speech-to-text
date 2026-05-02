#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test fixtures: stub libs.stt before importing stt_server, expose Flask test client."""

import io
import os
import queue
import sys
import types
import wave

import pytest

# Stub libs.stt so tests don't need torch/whisper installed.
# Must run before stt_server is imported anywhere.
fake_stt = types.ModuleType("libs.stt")


def _fake_get_model():
    return object()


def _fake_get_stt_bio(bio, model=None, device=None):
    return "stub transcription"


fake_stt.get_model = _fake_get_model
fake_stt.get_stt_bio = _fake_get_stt_bio

if "libs" not in sys.modules:
    sys.modules["libs"] = types.ModuleType("libs")
sys.modules["libs.stt"] = fake_stt

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import stt_server  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    pool: queue.Queue = queue.Queue()
    pool.put("model-sentinel")
    monkeypatch.setattr(stt_server, "MODEL_POOL", pool)
    monkeypatch.setattr(stt_server, "MODEL_POOL_SIZE", 1)
    return stt_server.app.test_client()


@pytest.fixture
def stt_module():
    return fake_stt


def make_wav(duration_ms: int = 100, sample_rate: int = 16000) -> bytes:
    """Build a valid silent 16-bit mono PCM WAV using stdlib wave."""
    n_frames = int(sample_rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test helpers that must not live in conftest.py, which pytest would then execute twice."""

import io
import queue
import re
import wave

import numpy as np

# Local imports
from libs import config, model_pool, registry

# The live stream's format: signed 16-bit mono PCM at 16 kHz.
STREAM_RATE = 16000

# Every error body carries a request id of 12 lower-case hex digits.
REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


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


def assert_error_shape(body):
    """Assert the response carries exactly the generic error category and a request id."""
    assert set(body.keys()) == {"error", "request_id"}
    assert REQ_ID_RE.match(body["request_id"])


def make_tone(seconds: float, amplitude: float = 0.3, frequency: float = 440.0) -> np.ndarray:
    """A sine tone as int16 samples at the stream rate, far above the pause detector's speech floor."""
    count = int(round(seconds * STREAM_RATE))
    times = np.arange(count) / STREAM_RATE
    return (amplitude * 32767 * np.sin(2 * np.pi * frequency * times)).astype(np.int16)


def make_silence(seconds: float) -> np.ndarray:
    """Digital silence as int16 samples at the stream rate."""
    return np.zeros(int(round(seconds * STREAM_RATE)), dtype=np.int16)


def make_model_sentinel(model_id: str) -> dict:
    """The stub instance a fixture pool holds for one model, the same shape the stub get_model returns."""
    return {"stub_model": model_id}


def get_default_pool() -> queue.Queue:
    """The queue of the model a request without `model` borrows from."""
    return model_pool.MODEL_POOLS[registry.get_default_model_id()]


def use_legacy_model(monkeypatch, backend, model_id):
    """Switch the single-model deployment to another backend or checkpoint, with a pool to match."""
    monkeypatch.setattr(config, "STT_BACKEND", backend)
    monkeypatch.setattr(config, "WHISPER_MODEL" if backend == "whisper" else "PARAKEET_MODEL", model_id)
    pool = model_pool.get_model_pool(model_id)
    pool.put(make_model_sentinel(model_id))

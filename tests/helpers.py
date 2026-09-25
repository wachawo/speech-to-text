#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test helpers that must not live in conftest.py, which pytest would then execute twice."""

import io
import queue
import wave

# Local imports
from libs import model_pool, registry


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


def make_model_sentinel(model_id: str) -> dict:
    """The stub instance a fixture pool holds for one model, the same shape the stub get_model returns."""
    return {"stub_model": model_id}


def get_default_pool() -> queue.Queue:
    """The queue of the model a request without `model` borrows from."""
    return model_pool.MODEL_POOLS[registry.get_default_model_id()]

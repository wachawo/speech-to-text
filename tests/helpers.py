#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test helpers that must not live in conftest.py, which pytest would then execute twice."""

import io
import wave

import numpy as np

# The live stream's format: signed 16-bit mono PCM at 16 kHz.
STREAM_RATE = 16000


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


def make_tone(seconds: float, amplitude: float = 0.3, frequency: float = 440.0) -> np.ndarray:
    """A sine tone as int16 samples at the stream rate, far above the pause detector's speech floor."""
    count = int(round(seconds * STREAM_RATE))
    times = np.arange(count) / STREAM_RATE
    return (amplitude * 32767 * np.sin(2 * np.pi * frequency * times)).astype(np.int16)


def make_silence(seconds: float) -> np.ndarray:
    """Digital silence as int16 samples at the stream rate."""
    return np.zeros(int(round(seconds * STREAM_RATE)), dtype=np.int16)

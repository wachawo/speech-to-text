#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Streaming diarization in the REAL libs/diarize.py: turns from per-frame activity, and the chunk loop.

torch is not installed in CI. advance_stream imports it inside the function and touches only
`torch.inference_mode`, so these tests put a minimal fake module in sys.modules for their own
duration; the model and processor are fakes that follow the chunk-size contract of the real pair.
"""

import contextlib
import importlib.util
import os
import sys
import types
from unittest import mock

import numpy as np
import pytest

# Local imports
from libs import config

MODULE_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)), "libs", "diarize.py")

SPEAKERS = 8
HOP = 160
N_FFT = 400
FRAMES_PER_STEP = 100
FIRST_CHUNK = 16000
CHUNK = 16400
LOOK_BACK = N_FFT // 2


def load_real_diarize():
    """Load libs/diarize.py from its file, bypassing the stub the rest of the suite keeps in sys.modules."""
    spec = importlib.util.spec_from_file_location("libs_diarize_stream_real", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_activity(frames: int, spans: dict[int, list[tuple[int, int]]]) -> np.ndarray:
    """A `(frames, 8)` bool array with each speaker active over the given `[start, end)` frame spans."""
    activity = np.zeros((frames, SPEAKERS), dtype=bool)
    for speaker, ranges in spans.items():
        for start, end in ranges:
            activity[start:end, speaker] = True
    return activity


def build_state(*chunks: np.ndarray) -> dict:
    """A stream state holding the given activity chunks, as advance_stream leaves it."""
    return {"activity": list(chunks), "frames": sum(chunk.shape[0] for chunk in chunks)}


def build_fake_logits(probabilities: np.ndarray) -> mock.MagicMock:
    """Stand in for a `(1, frames, 8)` logits tensor through `.sigmoid() > threshold`, `[0]`, `.cpu().numpy()`."""
    logits = mock.MagicMock()

    def compare_probabilities(threshold):
        """What `probabilities > threshold` is, reachable as `[0].cpu().numpy()`."""
        decisions = probabilities > threshold
        return {0: types.SimpleNamespace(cpu=lambda: types.SimpleNamespace(numpy=lambda: decisions[0]))}

    logits.sigmoid.return_value.__gt__.side_effect = compare_probabilities
    return logits


def build_fake_diarizer(inference: dict) -> tuple:
    """A (processor, model) pair that follows the streaming chunk contract and records every call.

    The model returns one frame per HOP samples, at most FRAMES_PER_STEP, and makes speaker
    `call % 8` active in every frame of its `call`th chunk. Its speaker cache is the call number.
    """
    calls: list[dict] = []

    def processor(samples, sampling_rate=None, is_streaming=None, is_first_audio_chunk=None, is_last_audio_chunk=None):
        """Record one chunk and turn it into the inputs the model takes."""
        calls.append(
            {
                "size": samples.size,
                "dtype": samples.dtype,
                "peak": float(np.abs(samples).max()) if samples.size else 0.0,
                "sampling_rate": sampling_rate,
                "streaming": is_streaming,
                "first": is_first_audio_chunk,
                "last": is_last_audio_chunk,
            }
        )
        return types.SimpleNamespace(to=lambda device, dtype=None: {"input_values": samples})

    processor.feature_extractor = types.SimpleNamespace(hop_length=HOP, n_fft=N_FFT)
    processor.num_samples_first_audio_chunk = FIRST_CHUNK
    processor.num_samples_per_audio_chunk = CHUNK
    processor.num_mel_frames_per_step = FRAMES_PER_STEP
    processor.audio_chunk_start = lambda frame: frame * HOP - LOOK_BACK
    processor.calls = calls

    def model(input_values=None, speaker_cache=None):
        """Score one chunk, remembering which cache it was handed and whether inference mode was on."""
        call = len(calls) - 1
        calls[call]["cache_in"] = speaker_cache
        calls[call]["inference_mode"] = inference["active"]
        frames = min(FRAMES_PER_STEP, input_values.size // HOP)
        probabilities = np.full((1, frames, SPEAKERS), 0.2)
        probabilities[0, :, call % SPEAKERS] = 0.9
        return types.SimpleNamespace(logits=build_fake_logits(probabilities), speaker_cache=f"cache-{call}")

    model.device = "cpu"
    model.dtype = "float32"
    return processor, model


def build_reader(total: int, reads: list) -> object:
    """A read_samples callback over a quiet int16 signal, recording each range it is asked for."""

    def read_samples(start: int, end: int) -> np.ndarray:
        """The samples in [start, end), clipped to what has arrived."""
        reads.append((start, end))
        start = max(0, start)
        end = min(end, total)
        return np.full(max(0, end - start), 16384, dtype=np.int16)

    return read_samples


@pytest.fixture
def real_diarize():
    """The real diarization module, loaded from its file."""
    return load_real_diarize()


@pytest.fixture
def inference():
    """Whether the fake torch's inference mode is currently entered."""
    return {"active": False}


@pytest.fixture
def fake_torch(monkeypatch, inference):
    """A `torch` module with only inference_mode, installed for one test and removed after it."""

    @contextlib.contextmanager
    def inference_mode():
        """Mark inference mode as entered for the duration of the block."""
        inference["active"] = True
        try:
            yield
        finally:
            inference["active"] = False

    module = types.ModuleType("torch")
    module.inference_mode = inference_mode
    monkeypatch.setitem(sys.modules, "torch", module)
    monkeypatch.setattr(config, "DIARIZE_THRESHOLD", 0.5)
    return module


def run_advance(real_diarize, state, diarizer, total, until, final, reads=None):
    """Call advance_stream over a signal of `total` samples."""
    reads = [] if reads is None else reads
    real_diarize.advance_stream(state, build_reader(total, reads), total, diarizer, until, final)
    return reads


def test_turn_edges_become_times(real_diarize):
    """Each run of active frames is one turn, at 10 ms a frame."""
    state = build_state(build_activity(100, {0: [(10, 30)], 3: [(50, 51)]}))
    assert real_diarize.stream_turns(state, 0.0, 1.0) == [
        {"speaker": 0, "start": 0.1, "end": 0.3},
        {"speaker": 3, "start": 0.5, "end": 0.51},
    ]


def test_one_speaker_can_have_several_turns(real_diarize):
    """A pause inside one speaker's activity splits it into two turns."""
    state = build_state(build_activity(100, {2: [(0, 10), (20, 30)]}))
    assert real_diarize.stream_turns(state, 0.0, 1.0) == [
        {"speaker": 2, "start": 0.0, "end": 0.1},
        {"speaker": 2, "start": 0.2, "end": 0.3},
    ]


def test_the_window_clips_turns_across_chunk_boundaries(real_diarize):
    """A turn spanning three chunks is cut to the window, which itself spans chunk boundaries."""
    activity = build_activity(100, {1: [(25, 65)]})
    state = build_state(activity[:30], activity[30:60], activity[60:])
    assert real_diarize.stream_turns(state, 0.4, 0.6) == [{"speaker": 1, "start": 0.4, "end": 0.61}]
    assert real_diarize.stream_turns(state, 0.0, 1.0) == [{"speaker": 1, "start": 0.25, "end": 0.65}]


def test_overlapping_speakers_are_two_turns(real_diarize):
    """Two speakers active at once are two turns over the same seconds, sorted by start."""
    state = build_state(build_activity(100, {4: [(30, 80)], 0: [(0, 50)]}))
    assert real_diarize.stream_turns(state, 0.0, 1.0) == [
        {"speaker": 0, "start": 0.0, "end": 0.5},
        {"speaker": 4, "start": 0.3, "end": 0.8},
    ]


def test_windows_outside_the_frames_are_empty(real_diarize):
    """No frames yet, a window past them, or an inverted window: no turns, and no crash."""
    assert real_diarize.stream_turns(real_diarize.new_stream_state(), 0.0, 10.0) == []
    state = build_state(build_activity(100, {0: [(0, 100)]}))
    assert real_diarize.stream_turns(state, 5.0, 6.0) == []
    assert real_diarize.stream_turns(state, 0.8, 0.2) == []
    assert real_diarize.stream_turns(state, -3.0, 0.05) == [{"speaker": 0, "start": 0.0, "end": 0.06}]


def test_advance_stops_once_the_frames_cover_until(real_diarize, fake_torch, inference):
    """Only as many chunks as it takes to reach `until`, even with far more audio waiting."""
    processor, model = build_fake_diarizer(inference)
    state = real_diarize.new_stream_state()
    reads = run_advance(real_diarize, state, (processor, model), total=5 * FIRST_CHUNK, until=24000, final=False)
    assert reads == [(0, FIRST_CHUNK), (FRAMES_PER_STEP * HOP - LOOK_BACK, FRAMES_PER_STEP * HOP - LOOK_BACK + CHUNK)]
    assert state["frames"] == 2 * FRAMES_PER_STEP
    assert state["frame"] == 2 * FRAMES_PER_STEP
    assert state["next_start"] == 2 * FRAMES_PER_STEP * HOP - LOOK_BACK
    assert state["finished"] is False
    assert [call["first"] for call in processor.calls] == [True, False]
    assert [call["last"] for call in processor.calls] == [False, False]
    assert all(call["inference_mode"] for call in processor.calls)
    assert inference["active"] is False
    # Scaled from int16 to the float waveform the processor expects.
    assert processor.calls[0]["dtype"] == np.float32
    assert processor.calls[0]["peak"] == pytest.approx(0.5)
    assert processor.calls[0]["sampling_rate"] == real_diarize.TARGET_SAMPLE_RATE
    assert processor.calls[0]["streaming"] is True


def test_advance_does_nothing_when_until_is_already_covered(real_diarize, fake_torch, inference):
    """A caller that already has the frames it needs costs no model call."""
    processor, model = build_fake_diarizer(inference)
    state = real_diarize.new_stream_state()
    assert run_advance(real_diarize, state, (processor, model), total=5 * FIRST_CHUNK, until=0, final=True) == []
    assert state == real_diarize.new_stream_state()


def test_advance_waits_for_a_whole_chunk_until_the_stream_is_final(real_diarize, fake_torch, inference):
    """A chunk that has not fully arrived is left for later; the cache carries over to the next call."""
    processor, model = build_fake_diarizer(inference)
    state = real_diarize.new_stream_state()
    diarizer = (processor, model)
    run_advance(real_diarize, state, diarizer, total=20000, until=10**9, final=False)
    assert len(processor.calls) == 1
    assert state["frames"] == FRAMES_PER_STEP
    assert state["first"] is False
    assert state["finished"] is False

    run_advance(real_diarize, state, diarizer, total=40000, until=10**9, final=False)
    assert len(processor.calls) == 2
    assert state["frames"] == 2 * FRAMES_PER_STEP
    assert [call["cache_in"] for call in processor.calls] == [None, "cache-0"]
    assert state["cache"] == "cache-1"
    # Speaker `call % 8` was active in each chunk, and the chunks are kept in order.
    assert state["activity"][0][:, 0].all() and not state["activity"][0][:, 1:].any()
    assert state["activity"][1][:, 1].all() and not state["activity"][1][:, [0, *range(2, SPEAKERS)]].any()


def test_advance_takes_the_tail_as_the_last_chunk_when_final(real_diarize, fake_torch, inference):
    """Once the stream is over, the remainder goes in as a short last chunk and the state is finished."""
    processor, model = build_fake_diarizer(inference)
    state = real_diarize.new_stream_state()
    reads = run_advance(real_diarize, state, (processor, model), total=20000, until=10**9, final=True)
    tail_start = FRAMES_PER_STEP * HOP - LOOK_BACK
    assert reads == [(0, FIRST_CHUNK), (tail_start, 20000)]
    assert [call["last"] for call in processor.calls] == [False, True]
    assert processor.calls[1]["size"] == 20000 - tail_start
    assert state["frames"] == FRAMES_PER_STEP + (20000 - tail_start) // HOP
    assert state["finished"] is True

    # A finished stream is left alone.
    run_advance(real_diarize, state, (processor, model), total=20000, until=10**9, final=True)
    assert len(processor.calls) == 2


def test_advance_takes_a_short_stream_as_one_first_and_last_chunk(real_diarize, fake_torch, inference):
    """A stream shorter than the first chunk is still diarized when it ends."""
    processor, model = build_fake_diarizer(inference)
    state = real_diarize.new_stream_state()
    run_advance(real_diarize, state, (processor, model), total=8000, until=10**9, final=False)
    assert processor.calls == []
    run_advance(real_diarize, state, (processor, model), total=8000, until=10**9, final=True)
    assert [(call["first"], call["last"], call["size"]) for call in processor.calls] == [(True, True, 8000)]
    assert state["finished"] is True


def test_advance_skips_a_tail_shorter_than_one_window(real_diarize, fake_torch, inference):
    """A remainder shorter than n_fft yields no frame, so it is not sent to the model at all."""
    processor, model = build_fake_diarizer(inference)
    state = real_diarize.new_stream_state()
    total = FRAMES_PER_STEP * HOP - LOOK_BACK + N_FFT - 100
    run_advance(real_diarize, state, (processor, model), total=total, until=10**9, final=True)
    assert len(processor.calls) == 1
    assert state["frames"] == FRAMES_PER_STEP
    assert state["finished"] is True


def test_threshold_decides_activity(real_diarize, fake_torch, inference, monkeypatch):
    """A probability counts as speech only above DIARIZE_THRESHOLD."""
    processor, model = build_fake_diarizer(inference)
    monkeypatch.setattr(config, "DIARIZE_THRESHOLD", 0.95)
    state = real_diarize.new_stream_state()
    run_advance(real_diarize, state, (processor, model), total=FIRST_CHUNK, until=10**9, final=False)
    assert state["frames"] == FRAMES_PER_STEP
    assert not state["activity"][0].any()


def test_advanced_frames_read_back_as_turns(real_diarize, fake_torch, inference):
    """What advance_stream stores, stream_turns reads at 10 ms a frame: 100 frames per second of audio."""
    processor, model = build_fake_diarizer(inference)
    state = real_diarize.new_stream_state()
    run_advance(real_diarize, state, (processor, model), total=40000, until=10**9, final=False)
    assert real_diarize.stream_turns(state, 0.0, 2.0) == [
        {"speaker": 0, "start": 0.0, "end": 1.0},
        {"speaker": 1, "start": 1.0, "end": 2.0},
    ]

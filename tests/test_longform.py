#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Long recordings in pieces: cut at pauses, one borrowed model per piece, speakers across the file."""

import queue
import threading
import time

import numpy as np
import pytest

from libs import config, longform, model_pool, speech_gate, stream
from tests.helpers import make_silence, make_tone

RATE = longform.SAMPLE_RATE


@pytest.fixture
def small_chunks(monkeypatch):
    """Pieces of 10 s with a 2 s search window, so a test needs seconds of audio, not minutes."""
    monkeypatch.setattr(longform, "CHUNK_SECONDS", 10)
    monkeypatch.setattr(longform, "CUT_SEARCH_SECONDS", 2)


@pytest.fixture
def counting_pool(monkeypatch, stt_module):
    """A one-slot model pool, and a transcriber that records the length of every piece it was given."""
    pool: queue.Queue = queue.Queue()
    pool.put("model-sentinel")
    monkeypatch.setattr(model_pool, "MODEL_POOL", pool)
    monkeypatch.setattr(config, "STT_BACKEND", "whisper")
    pieces = []

    def record_segments(bio, model=None, device=None, language=None):
        """One segment spanning the piece; checks the model really was borrowed."""
        assert pool.qsize() == 0, "the model must be out of the pool while a piece is transcribed"
        samples = np.frombuffer(bio.getvalue()[44:], dtype="<i2")
        length = samples.size / RATE
        pieces.append(round(length, 2))
        return [{"start": 0.0, "end": length, "text": f" piece {len(pieces)}"}]

    monkeypatch.setattr(stt_module, "get_stt_segments", record_segments)
    return pool, pieces


def speech_with_pauses(seconds_each: float, count: int, pause: float) -> np.ndarray:
    """Tone bursts separated by silence: stand-ins for phrases and the pauses between them."""
    parts = []
    for unused_index in range(count):
        parts.extend([make_tone(seconds_each), make_silence(pause)])
    return np.concatenate(parts)


def test_a_short_file_is_one_piece(small_chunks):
    """Nothing to cut when the file fits in a piece."""
    samples = make_tone(8.0)
    assert longform.plan_chunks(samples, None) == [(0, samples.size)]


def test_cuts_land_in_the_pauses_the_detector_found(small_chunks):
    """With speech ranges, every cut is inside a gap between two ranges, near each 10 s mark."""
    samples = speech_with_pauses(3.0, 8, 1.0)
    ranges = [(index * 4.0, index * 4.0 + 3.0) for index in range(8)]
    chunks = longform.plan_chunks(samples, ranges)
    assert chunks[0][0] == 0 and chunks[-1][1] == samples.size
    # The pauses: between two phrases, and the silence after the last one.
    pauses = [(stop, start) for (unused_a, stop), (start, unused_b) in zip(ranges[:-1], ranges[1:], strict=True)]
    pauses.append((ranges[-1][1], samples.size / RATE))
    for (unused_start, end), (next_start, unused_end) in zip(chunks[:-1], chunks[1:], strict=True):
        assert end == next_start
        cut = end / RATE
        assert any(stop <= cut <= start for stop, start in pauses), cut


def test_without_a_detector_cuts_land_in_the_quietest_frame(small_chunks):
    """No ranges: the cut near 10 s falls in the silence, not in the tone."""
    samples = np.concatenate([make_tone(9.5), make_silence(1.0), make_tone(9.5), make_silence(0.5), make_tone(5.0)])
    first_cut = longform.plan_chunks(samples, None)[0][1] / RATE
    assert 9.5 <= first_cut <= 10.5


def test_each_piece_borrows_the_model_and_gives_it_back(small_chunks, counting_pool):
    """Every piece is transcribed with the model out of the pool, and it is back after each one."""
    pool, pieces = counting_pool
    samples = speech_with_pauses(3.0, 8, 1.0)
    segments = longform.transcribe_long(samples, None, None, "job")
    assert len(pieces) == len(longform.plan_chunks(samples, None)) > 1
    assert pool.qsize() == 1
    # Times are in file time, one segment per piece here, in order.
    starts = [segment["start"] for segment in segments]
    assert starts == sorted(starts) and starts[0] == 0.0 and starts[1] > 0


def test_a_piece_with_no_speech_never_borrows_the_model(small_chunks, counting_pool):
    """With speech ranges, a silent piece is skipped outright."""
    pool, pieces = counting_pool
    samples = np.concatenate([make_tone(9.0), make_silence(1.0), make_silence(9.0), make_silence(5.0)])
    segments = longform.transcribe_long(samples, None, [(0.0, 9.0)], "job")
    assert len(pieces) == 1 and [segment["text"] for segment in segments] == [" piece 1"]


def test_diarization_runs_the_whole_file_in_steps(monkeypatch):
    """The diarizer is advanced step by step to the end of the file, then its turns are read."""
    steps = []

    def record_advance(state, buffer, until, final):
        """Stand in for stream.advance_diarization."""
        steps.append((until, final))
        state["finished"] = final

    monkeypatch.setattr(longform, "DIARIZE_STEP_SECONDS", 10)
    monkeypatch.setattr(stream, "advance_diarization", record_advance)
    monkeypatch.setattr(longform.diarize, "new_stream_state", lambda: {"finished": False}, raising=False)
    monkeypatch.setattr(
        longform.diarize, "stream_turns", lambda state, start, end: [{"speaker": 0, "start": 0.0, "end": 25.0}], raising=False
    )
    turns = longform.diarize_long(make_tone(25.0))
    assert steps == [(10 * RATE, False), (20 * RATE, False), (25 * RATE, True)]
    assert turns == [{"speaker": 0, "start": 0.0, "end": 25.0}]


@pytest.mark.parametrize("mode", ["text", "speakers", "turns"])
def test_each_mode_answers_in_the_shape_of_its_endpoint(mode, tmp_path, monkeypatch, counting_pool):
    """text like /api/stt plus segments, speakers like /api/transcript, turns like /api/diarize."""
    monkeypatch.setattr(longform, "diarize_long", lambda samples: [{"speaker": 0, "start": 0.0, "end": 3.0}])
    path = tmp_path / "audio.wav"
    path.write_bytes(stream.encode_wav(make_tone(3.0)).getvalue())
    result = longform.run(mode, str(path), None, "job")
    expected = {
        "text": {"text", "segments", "seconds"},
        "speakers": {"segments", "turns", "speakers", "text", "seconds"},
        "turns": {"segments", "speakers", "seconds"},
    }[mode]
    assert set(result) == expected and result["seconds"] == 3.0


def test_the_speech_gate_vets_every_piece(tmp_path, monkeypatch, counting_pool):
    """With the gate on, a file with no speech comes back empty and the model is never borrowed."""
    monkeypatch.setattr(config, "SPEECH_GATE", True)
    monkeypatch.setattr(speech_gate, "detect_speech", lambda samples: [])
    pool, pieces = counting_pool
    path = tmp_path / "audio.wav"
    path.write_bytes(stream.encode_wav(make_tone(5.0)).getvalue())
    assert longform.run("text", str(path), None, "job")["text"] == ""
    assert pieces == []


def test_background_work_steps_aside_for_a_waiting_request(monkeypatch):
    """After releasing, a job waits while somebody else is waiting, and no longer than the limit."""
    monkeypatch.setattr(model_pool, "WAITING", {"model": 0, "diarizer": 0})
    model_pool.count_waiting("model", 1)
    released = threading.Timer(0.2, lambda: model_pool.count_waiting("model", -1))
    released.start()
    started = time.monotonic()
    model_pool.yield_to_waiters("model")
    assert 0.15 < time.monotonic() - started < 2.0
    monkeypatch.setattr(model_pool, "YIELD_LIMIT_SECONDS", 0.1)
    model_pool.count_waiting("model", 1)
    started = time.monotonic()
    model_pool.yield_to_waiters("model")
    assert time.monotonic() - started < 1.0


def test_acquire_counts_the_caller_as_waiting_while_it_waits(monkeypatch):
    """A caller blocked in acquire_model is counted; once served, it no longer is."""
    pool: queue.Queue = queue.Queue()
    monkeypatch.setattr(model_pool, "MODEL_POOL", pool)
    monkeypatch.setattr(model_pool, "WAITING", {"model": 0, "diarizer": 0})
    got = []
    waiter = threading.Thread(target=lambda: got.append(model_pool.acquire_model(timeout=5)))
    waiter.start()
    deadline = time.monotonic() + 2
    while model_pool.WAITING["model"] == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert model_pool.WAITING["model"] == 1
    pool.put("model")
    waiter.join(timeout=5)
    assert got == ["model"] and model_pool.WAITING["model"] == 0

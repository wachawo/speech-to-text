#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Long recordings in pieces: transcribe and diarize a file of any length without holding a model.

A synchronous request transcribes a file in one call and holds a pooled model for all of it. For an
hour of audio that is a minute or more during which every other request - a phone call's phrase
included - waits for the only model. Here the file is cut into pieces of about CHUNK_SECONDS at a
pause, each piece borrows the model and gives it back, and diarization runs the model's streaming
mode across the whole file with its speaker cache, so speaker numbers stay the same from the first
minute to the last while the diarizer, too, is released between steps. After each piece the job
steps aside for anyone already waiting: the pool's queue would otherwise hand the model straight back.
"""

import logging
import time
from typing import Any

import numpy as np
import soundfile as sf

# Local imports
from libs import align, backends, config, diarize, model_pool, speech_gate, stream

logger = logging.getLogger(__name__)

SAMPLE_RATE = stream.SAMPLE_RATE

# Pieces of about a minute, cut at a pause: a piece takes the GPU about 8 s, which is the longest a
# phone call's phrase can wait behind a job. Five-minute pieces made that 40 s, and with the pool's
# unfair queue a request waited through several of them - 205 s measured on the deployment host.
CHUNK_SECONDS = 60

# A cut is moved to the widest pause found this far either side of the nominal boundary.
CUT_SEARCH_SECONDS = 10

# How much audio the diarizer takes per borrow of the pooled instance.
DIARIZE_STEP_SECONDS = 60

# Frame used to find the quietest moment when there is no voice detector to find a pause.
QUIET_FRAME = SAMPLE_RATE * 30 // 1000


def load_samples(path: str) -> np.ndarray:
    """A 16 kHz mono WAV file as int16 samples."""
    samples, rate = sf.read(path, dtype="int16")
    if rate != SAMPLE_RATE:
        raise ValueError(f"Expected {SAMPLE_RATE} Hz audio, got {rate} Hz")
    if samples.ndim == 2:
        samples = samples.mean(axis=1).astype(np.int16)
    return samples


def find_pause(samples: np.ndarray, ranges: list[tuple[float, float]] | None, around: int) -> int:
    """The sample to cut at near `around`: the middle of the widest pause within CUT_SEARCH_SECONDS.

    With speech ranges, a pause is a gap between two of them. Without, the quietest 30 ms frame of
    the window stands in for one.
    """
    low = max(0, around - CUT_SEARCH_SECONDS * SAMPLE_RATE)
    high = min(samples.size, around + CUT_SEARCH_SECONDS * SAMPLE_RATE)
    if ranges is not None:
        edges = [0.0] + [edge for start, end in ranges for edge in (start, end)] + [samples.size / SAMPLE_RATE]
        gaps = [(edges[index], edges[index + 1]) for index in range(0, len(edges) - 1, 2)]
        best = None
        for gap_start, gap_end in gaps:
            start, end = max(gap_start * SAMPLE_RATE, low), min(gap_end * SAMPLE_RATE, high)
            if end > start and (best is None or end - start > best[1] - best[0]):
                best = (start, end)
        if best is not None:
            return int((best[0] + best[1]) / 2)
    frames = [
        (float(np.abs(samples[offset : offset + QUIET_FRAME].astype(np.int32)).mean()), offset)
        for offset in range(low, max(low + 1, high - QUIET_FRAME), QUIET_FRAME)
    ]
    return min(frames)[1] + QUIET_FRAME // 2 if frames else around


def plan_chunks(samples: np.ndarray, ranges: list[tuple[float, float]] | None) -> list[tuple[int, int]]:
    """Consecutive `(start, end)` sample ranges covering the file, cut at pauses near every CHUNK_SECONDS."""
    chunk = CHUNK_SECONDS * SAMPLE_RATE
    cuts = [0]
    while samples.size - cuts[-1] > chunk + CUT_SEARCH_SECONDS * SAMPLE_RATE:
        cut = find_pause(samples, ranges, cuts[-1] + chunk)
        cuts.append(cut if cut > cuts[-1] else cuts[-1] + chunk)
    cuts.append(samples.size)
    return list(zip(cuts[:-1], cuts[1:], strict=True))


def shift_ranges(ranges: list[tuple[float, float]] | None, start: float, end: float) -> list[tuple[float, float]] | None:
    """The speech ranges inside [start, end], moved to start at zero; None stays None."""
    if ranges is None:
        return None
    return [(max(0.0, begin - start), min(end, finish) - start) for begin, finish in ranges if finish > start and begin < end]


def transcribe_long(
    samples: np.ndarray, language: str | None, ranges: list[tuple[float, float]] | None, request_id: str
) -> list[dict[str, Any]]:
    """Transcribe a whole file piece by piece; segments come back in file time.

    A piece with no detected speech is skipped without borrowing the model.
    """
    segments: list[dict[str, Any]] = []
    for start, end in plan_chunks(samples, ranges):
        offset, length = start / SAMPLE_RATE, (end - start) / SAMPLE_RATE
        local_ranges = shift_ranges(ranges, offset, offset + length)
        if local_ranges is not None and speech_gate.spoken_seconds(local_ranges) < stream.MIN_VOICED_SECONDS:
            continue
        model = model_pool.acquire_model()
        try:
            found = backends.transcriber().get_stt_segments(
                stream.encode_wav(samples[start:end]), model=model, language=language
            )
        finally:
            model_pool.release_model(model)
        model_pool.yield_to_waiters("model")
        for segment in speech_gate.keep_spoken(found, local_ranges, request_id, length):
            seg_start = float(segment["start"])
            if seg_start >= length or not segment["text"].strip():
                continue
            segments.append(
                {
                    "start": round(offset + seg_start, 2),
                    "end": round(offset + min(float(segment["end"]), length), 2),
                    "text": segment["text"],
                }
            )
    return segments


def diarize_long(samples: np.ndarray) -> list[dict[str, Any]]:
    """Diarize a whole file with the model's streaming mode, one DIARIZE_STEP_SECONDS at a time."""
    state = diarize.new_stream_state()
    buffer = stream.new_buffer()
    stream.append_samples(buffer, samples)
    step = DIARIZE_STEP_SECONDS * SAMPLE_RATE
    until = step
    while not state["finished"]:
        final = until >= samples.size
        stream.advance_diarization(state, buffer, min(until, samples.size), final)
        model_pool.yield_to_waiters("diarizer")
        until += step
    return diarize.stream_turns(state, 0.0, samples.size / SAMPLE_RATE + 1.0)


def run(mode: str, wav_path: str, language: str | None, request_id: str) -> dict[str, Any]:
    """Process one job's audio in the requested mode; the result has the shape of the matching endpoint.

    Each stage's duration goes to the log: on a long file they are minutes, and which one it was
    matters when a job is slower than expected.
    """
    samples = load_samples(wav_path)
    duration = round(samples.size / SAMPLE_RATE, 2)
    ranges = None
    if config.SPEECH_GATE and mode != "turns":
        started = time.monotonic()
        ranges = speech_gate.find_speech(samples.astype(np.float32) / 32768.0, request_id)
        logger.info(
            "[%s] Voice detection: %.1fs of speech in %.1fs (%.1fs)",
            request_id,
            speech_gate.spoken_seconds(ranges or []),
            duration,
            time.monotonic() - started,
        )
    turns: list[dict[str, Any]] = []
    if mode in ("turns", "speakers"):
        started = time.monotonic()
        turns = diarize_long(samples)
        logger.info("[%s] Diarization: %d turns (%.1fs)", request_id, len(turns), time.monotonic() - started)
    if mode == "turns":
        return {"segments": turns, "speakers": len({turn["speaker"] for turn in turns}), "seconds": duration}
    started = time.monotonic()
    segments = transcribe_long(samples, language, ranges, request_id)
    logger.info("[%s] Transcription: %d segments (%.1fs)", request_id, len(segments), time.monotonic() - started)
    text = "".join(segment["text"] for segment in segments).strip()
    if mode == "speakers":
        attributed = align.attribute_segments(segments, turns)
        return {
            "segments": attributed,
            "turns": turns,
            "speakers": align.count_speakers(attributed),
            "text": text,
            "seconds": duration,
        }
    return {"text": text, "segments": segments, "seconds": duration}


def main():
    """No-op entry point: libs/jobs.py runs this module's pipeline."""
    pass


if __name__ == "__main__":
    main()

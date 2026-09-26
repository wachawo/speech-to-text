#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keep only transcribed text that was actually spoken: a voice detector vets Whisper's segments.

Where there is no speech and no silence either - a tone, music, noise, a ringback - Whisper answers
with the credits of the YouTube subtitles it was trained on - a Russian "subtitles by DimaTorzok"
line, "to be continued...", "Thank you for watching." Its own confidence is no help: on the test
corpus `no_speech_prob` was 0.00 even on digital silence, and the hallucinations came with the
highest log-probabilities of the whole run. So a separate voice detector, Silero VAD, decides
where speech is, and a segment that is mostly outside speech is dropped. Credit lines that no
person ever says are dropped wherever they appear, which covers music with vocals, where the
detector does hear a voice.
"""

import io
import logging
import re
import threading
import time
import traceback
from typing import Any

import numpy as np
import soundfile as sf

# Local imports
from libs import metrics

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# Tuned on the corpus in ROADMAP A1: with these settings no segment of real speech fell below the
# share below, and every hallucination on tone, noise, silence, ringback and music did.
VAD_THRESHOLD = 0.35
VAD_MIN_SPEECH_MS = 100

# The detector runs over this much audio per turn of its lock; see detect_speech.
VAD_WINDOW_SECONDS = 30

# Two ranges this close across a window edge are one stretch of speech.
WINDOW_JOIN_SECONDS = 0.1

# A segment needs at least this share of its time inside detected speech to be kept.
MIN_SPEECH_SHARE = 0.3

# Whole-segment credit lines from subtitled video. Only lines nobody says in a conversation are
# listed: "to be continued..." or "Thank you for watching" can be real speech, and the voice
# detector already removes them where they are not. The Russian lines are the model's literal
# output and must match it, so they are written as escapes: "subtitles created / made / prepared
# by DimaTorzok" in its usual verb forms, and "subtitle editor ... proofreader ...".
CREDIT_PATTERNS = (
    r"\u0441\u0443\u0431\u0442\u0438\u0442\u0440\u044b (\u0441\u043e\u0437\u0434\u0430\u0432\u0430\u043b|\u0441\u0434\u0435\u043b\u0430\u043b|\u0434\u0435\u043b\u0430\u043b|\u043f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u0438\u043b)[a-z\u0430-\u044f\u0451]* dimatorzok",
    r"\u0440\u0435\u0434\u0430\u043a\u0442\u043e\u0440 \u0441\u0443\u0431\u0442\u0438\u0442\u0440\u043e\u0432 .* \u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043e\u0440 .*",
    r"subtitles by the amara\.org community",
)
CREDIT_LINES = re.compile("|".join(f"(?:{pattern})" for pattern in CREDIT_PATTERNS))

VAD_MODEL: Any = None
VAD_LOCK = threading.Lock()

# Set after the detector failed once, so a missing silero-vad is one error in the log, not one
# per request. Transcripts are then passed through unfiltered.
VAD_BROKEN = False


def load_vad() -> Any:
    """Load Silero VAD once per process. Imported here, not at module scope: it pulls in torch."""
    global VAD_MODEL
    with VAD_LOCK:
        if VAD_MODEL is None:
            from silero_vad import load_silero_vad

            VAD_MODEL = load_silero_vad()
            logger.info("Speech gate ready (Silero VAD)")
    return VAD_MODEL


def detect_speech(samples: np.ndarray) -> list[tuple[float, float]]:
    """Speech ranges in seconds in 16 kHz mono float32 samples.

    Serialised by a lock: the detector keeps recurrent state between chunks and resets it per call,
    so two requests sharing it at once would read each other's state. The audio is taken in windows
    of VAD_WINDOW_SECONDS with the lock held for one window at a time: a background job running the
    detector over an hour of audio would otherwise hold it for minutes, and every short request
    behind it would wait that long - measured at 198 s on the deployment host.
    """
    import torch
    from silero_vad import get_speech_timestamps

    model = load_vad()
    window = VAD_WINDOW_SECONDS * SAMPLE_RATE
    ranges: list[tuple[float, float]] = []
    for offset in range(0, max(1, samples.shape[0]), window):
        piece = np.ascontiguousarray(samples[offset : offset + window], dtype=np.float32)
        waiting_since = time.monotonic()
        with VAD_LOCK:
            waited = time.monotonic() - waiting_since
            if waited > 1.0:
                logger.info("Waited %.1fs for the voice detector", waited)
            found = get_speech_timestamps(
                torch.from_numpy(piece),
                model,
                sampling_rate=SAMPLE_RATE,
                threshold=VAD_THRESHOLD,
                min_speech_duration_ms=VAD_MIN_SPEECH_MS,
                return_seconds=True,
            )
        base = offset / SAMPLE_RATE
        for item in found:
            begin, finish = base + float(item["start"]), base + float(item["end"])
            # Speech that runs across a window edge comes back as two touching ranges: one again.
            if ranges and begin - ranges[-1][1] < WINDOW_JOIN_SECONDS:
                ranges[-1] = (ranges[-1][0], finish)
            else:
                ranges.append((begin, finish))
    return ranges


def find_speech(samples: np.ndarray, request_id: str = "-") -> list[tuple[float, float]] | None:
    """Speech ranges, or None when the detector is unavailable and nothing should be filtered.

    A quality filter must not take transcription down with it: a failure is logged once and the
    text goes out as the transcriber produced it.
    """
    global VAD_BROKEN
    if VAD_BROKEN:
        return None
    try:
        return detect_speech(samples)
    except Exception as exc:
        VAD_BROKEN = True
        logger.error(
            "[%s] Speech gate unavailable, transcripts go out unfiltered: %s: %s\n%s",
            request_id,
            type(exc).__name__,
            exc,
            traceback.format_exc(),
        )
        return None


def spoken_seconds(ranges: list[tuple[float, float]]) -> float:
    """Total seconds of detected speech."""
    return sum(end - start for start, end in ranges)


def speech_share(segment: dict[str, Any], ranges: list[tuple[float, float]], duration: float | None = None) -> float:
    """The share of a segment's time that falls inside detected speech.

    With `duration`, the segment is first cut at the end of the audio: Whisper decodes a window
    padded to 30 s and often ends the last segment far past the audio, and measured over that
    padding a phrase spoken from start to finish reads as mostly silence.
    """
    seg_start = float(segment["start"])
    seg_end = float(segment["end"]) if duration is None else min(float(segment["end"]), duration)
    length = seg_end - seg_start
    if length <= 0:
        return 0.0
    covered = sum(max(0.0, min(seg_end, end) - max(seg_start, start)) for start, end in ranges)
    return covered / length


def is_credit_line(text: str) -> bool:
    """Whether the whole segment is a subtitle credit line."""
    normalized = " ".join(text.lower().split()).strip(" .!")
    return bool(CREDIT_LINES.fullmatch(normalized))


def keep_spoken(
    segments: list[dict[str, Any]],
    ranges: list[tuple[float, float]] | None,
    request_id: str = "-",
    duration: float | None = None,
) -> list[dict[str, Any]]:
    """The segments that were spoken: enough of their time in speech, and not a credit line.

    With no ranges (the detector is unavailable) every segment is kept. `duration` is the length
    of the audio in seconds; see speech_share.
    """
    if ranges is None:
        return segments
    kept = []
    for segment in segments:
        share = speech_share(segment, ranges, duration)
        if share < MIN_SPEECH_SHARE or is_credit_line(segment["text"]):
            logger.info("[%s] Dropped as not spoken (speech %.0f%%): %r", request_id, share * 100, segment["text"].strip()[:80])
            metrics.DROPPED_SEGMENTS.inc()
            continue
        kept.append(segment)
    return kept


def gate_wav(wav_bio: io.BytesIO, segments: list[dict[str, Any]], request_id: str = "-") -> list[dict[str, Any]]:
    """Keep the segments of a 16 kHz mono WAV buffer that were spoken; the buffer is rewound."""
    wav_bio.seek(0)
    samples, unused_rate = sf.read(wav_bio, dtype="float32")
    wav_bio.seek(0)
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    return keep_spoken(segments, find_speech(samples, request_id), request_id, samples.shape[0] / SAMPLE_RATE)


def main():
    """No-op entry point: this module is imported for its filter."""
    pass


if __name__ == "__main__":
    main()

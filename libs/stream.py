#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live transcription core: buffer streamed PCM, cut it into utterances at pauses, transcribe each one.

Synchronous on purpose, with no asyncio in it: libs/live.py owns the socket and calls the blocking
parts from a worker thread. State is plain dicts, one per session.
"""

import io
import logging
import wave
from typing import Any

import numpy as np

# Local imports
from libs import align, backends, config, diarize, model_pool, speech_gate

logger = logging.getLogger(__name__)

# What a client streams: raw signed 16-bit little-endian mono PCM at 16 kHz, the same format
# libs/audio.py produces for an upload, so both paths hand the transcriber identical audio.
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2

# The pause detector works on 30 ms frames, the usual unit for energy-based voice detection.
FRAME_SAMPLES = SAMPLE_RATE * 30 // 1000

# A frame is speech when it is this far above the running noise floor, and never below the
# absolute floor: -45 dBFS, under which nothing a microphone picks up is worth transcribing.
NOISE_RATIO = 3.0
MIN_SPEECH_RMS = 10 ** (-45 / 20)

# An utterance ends after this much silence. Long enough to ride over the gap between two words,
# short enough that a handover to another speaker usually starts a new utterance.
PAUSE_SECONDS = 0.6

# Kept on both sides of the detected speech, because the detector triggers a frame late and
# releases a frame early, and a clipped first consonant is a misheard first word.
PRE_ROLL_SECONDS = 0.2
POST_ROLL_SECONDS = 0.15

# Speech that never pauses (music, a crowd, a broadcast) is still cut, at the quietest frame of
# the last few seconds rather than mid-word, so text keeps arriving.
MAX_UTTERANCE_SECONDS = 15.0
CUT_SEARCH_SECONDS = 3.0

# Less voiced audio than this is a click or a cough. Whisper answers such a fragment with a
# confident hallucination ("Thank you."), so it is dropped instead of transcribed.
MIN_VOICED_SECONDS = 0.25


def new_buffer() -> dict[str, Any]:
    """An empty sample buffer: chunks in arrival order, the absolute index of the first kept sample."""
    return {"chunks": [], "base": 0, "total": 0}


def append_samples(buffer: dict[str, Any], samples: np.ndarray) -> None:
    """Append int16 samples. A list of chunks, not one array, so an append never copies the stream."""
    if samples.size:
        buffer["chunks"].append(samples)
        buffer["total"] += int(samples.size)


def read_samples(buffer: dict[str, Any], start: int, end: int) -> np.ndarray:
    """The int16 samples in [start, end), by absolute index. Samples already trimmed read as absent."""
    start = max(start, buffer["base"])
    end = min(end, buffer["total"])
    if end <= start:
        return np.zeros(0, dtype=np.int16)
    parts = []
    position = buffer["base"]
    for chunk in list(buffer["chunks"]):
        chunk_end = position + chunk.size
        if chunk_end > start and position < end:
            parts.append(chunk[max(0, start - position) : min(chunk.size, end - position)])
        if chunk_end >= end:
            break
        position = chunk_end
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)


def trim_samples(buffer: dict[str, Any], keep_from: int) -> None:
    """Drop whole chunks that end before `keep_from`, so a long session does not keep every sample."""
    while buffer["chunks"] and buffer["base"] + buffer["chunks"][0].size <= keep_from:
        buffer["base"] += buffer["chunks"][0].size
        buffer["chunks"].pop(0)


def new_segmenter() -> dict[str, Any]:
    """Pause-detector state: the next frame to look at, and the utterance in progress if any."""
    return {
        "position": 0,
        "noise": MIN_SPEECH_RMS / NOISE_RATIO,
        "in_speech": False,
        "speech_start": 0,
        "last_voiced_end": 0,
        "voiced_samples": 0,
        "frame_levels": [],
        "cut_floor": 0,
    }


def measure_rms(frame: np.ndarray) -> float:
    """Root mean square of an int16 frame, on the [-1, 1] scale."""
    scaled = frame.astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(scaled * scaled)))


def is_voiced(segmenter: dict[str, Any], level: float) -> bool:
    """Classify one frame, and let the noise floor follow the room while nobody speaks.

    The floor falls fast and rises slowly: a quiet moment is trusted at once, while a rising level
    is more often somebody starting to talk than the room getting louder.
    """
    voiced = level > max(MIN_SPEECH_RMS, segmenter["noise"] * NOISE_RATIO)
    if level < segmenter["noise"]:
        segmenter["noise"] = 0.9 * segmenter["noise"] + 0.1 * level
    elif not voiced:
        segmenter["noise"] = 0.995 * segmenter["noise"] + 0.005 * level
    return voiced


def close_utterance(segmenter: dict[str, Any], end: int) -> dict[str, int] | None:
    """End the utterance in progress at `end`; None when it held too little speech to be worth it."""
    utterance = {"start": segmenter["speech_start"], "end": end}
    enough = segmenter["voiced_samples"] >= MIN_VOICED_SECONDS * SAMPLE_RATE
    segmenter["in_speech"] = False
    segmenter["voiced_samples"] = 0
    segmenter["frame_levels"] = []
    segmenter["cut_floor"] = end
    return utterance if enough else None


def find_quiet_cut(segmenter: dict[str, Any], frame_end: int) -> int:
    """Where to cut an utterance that has run too long: the quietest frame of its last few seconds."""
    earliest = frame_end - int(CUT_SEARCH_SECONDS * SAMPLE_RATE)
    candidates = [(level, start) for start, level in segmenter["frame_levels"] if start >= earliest]
    if not candidates:
        return frame_end
    level, start = min(candidates)
    return start + FRAME_SAMPLES // 2


def advance_segmenter(segmenter: dict[str, Any], buffer: dict[str, Any], final: bool = False) -> list[dict[str, int]]:
    """Consume every whole frame that has arrived and return the utterances that closed.

    Each utterance is `{"start", "end"}` in absolute samples. With `final` the stream is over: the
    utterance in progress is closed instead of waiting for a pause that will never come.
    """
    closed: list[dict[str, int]] = []
    pause = int(PAUSE_SECONDS * SAMPLE_RATE)
    while segmenter["position"] + FRAME_SAMPLES <= buffer["total"]:
        frame_start = segmenter["position"]
        frame_end = frame_start + FRAME_SAMPLES
        segmenter["position"] = frame_end
        level = measure_rms(read_samples(buffer, frame_start, frame_end))
        voiced = is_voiced(segmenter, level)

        if not segmenter["in_speech"]:
            if voiced:
                segmenter["in_speech"] = True
                segmenter["speech_start"] = max(segmenter["cut_floor"], frame_start - int(PRE_ROLL_SECONDS * SAMPLE_RATE))
                segmenter["last_voiced_end"] = frame_end
                segmenter["voiced_samples"] = FRAME_SAMPLES
                segmenter["frame_levels"] = [(frame_start, level)]
            continue

        segmenter["frame_levels"].append((frame_start, level))
        if voiced:
            segmenter["last_voiced_end"] = frame_end
            segmenter["voiced_samples"] += FRAME_SAMPLES
        if frame_end - segmenter["last_voiced_end"] >= pause:
            end = min(buffer["total"], segmenter["last_voiced_end"] + int(POST_ROLL_SECONDS * SAMPLE_RATE))
            utterance = close_utterance(segmenter, end)
            if utterance:
                closed.append(utterance)
        elif frame_end - segmenter["speech_start"] >= MAX_UTTERANCE_SECONDS * SAMPLE_RATE:
            cut = find_quiet_cut(segmenter, frame_end)
            carried_levels = [(start, level) for start, level in segmenter["frame_levels"] if start >= cut]
            utterance = close_utterance(segmenter, cut)
            if utterance:
                closed.append(utterance)
            # The speaker has not stopped: the next utterance starts right at the cut.
            segmenter["in_speech"] = True
            segmenter["speech_start"] = cut
            segmenter["last_voiced_end"] = frame_end
            segmenter["voiced_samples"] = frame_end - cut
            segmenter["frame_levels"] = carried_levels

    if final and segmenter["in_speech"]:
        utterance = close_utterance(segmenter, buffer["total"])
        if utterance:
            closed.append(utterance)
    return closed


def cut_utterance(segmenter: dict[str, Any], at: int) -> dict[str, int] | None:
    """Close the utterance in progress at sample `at` and go on with a new one from there.

    For a cut the pause detector cannot see, such as a speaker change without a pause. Nothing
    happens unless an utterance is open and `at` falls inside it. Returns the closed utterance,
    or None when there was nothing to cut or it held too little speech.
    """
    if not segmenter["in_speech"] or not segmenter["speech_start"] < at < segmenter["position"]:
        return None
    carried_levels = [(start, level) for start, level in segmenter["frame_levels"] if start >= at]
    voiced_after = sum(FRAME_SAMPLES for start, level in carried_levels)
    utterance = close_utterance(segmenter, at)
    segmenter["in_speech"] = True
    segmenter["speech_start"] = at
    segmenter["last_voiced_end"] = max(segmenter["last_voiced_end"], at)
    segmenter["voiced_samples"] = voiced_after
    segmenter["frame_levels"] = carried_levels
    return utterance


def encode_wav(samples: np.ndarray) -> io.BytesIO:
    """Wrap int16 samples in a WAV container, the input every transcriber module reads."""
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(samples.astype("<i2").tobytes())
    bio.seek(0)
    return bio


def transcribe_utterance(
    buffer: dict[str, Any], utterance: dict[str, int], language: str | None, request_id: str = "-"
) -> list[dict[str, Any]]:
    """Transcribe one utterance with a pooled model and return its segments in stream time.

    The model is borrowed for this utterance only and returned at once: the pool is shared with
    every upload, and a session that held a model for its whole length would starve them all.
    With the speech gate on, an utterance with no detected speech in it is not transcribed at all
    - the pause detector cuts on loudness, so a tone or a jingle reaches here, and Whisper would
    answer it with a subtitle credit - and the segments of the rest are vetted against the same
    speech ranges. Raises queue.Empty when no model frees up in time.
    """
    samples = read_samples(buffer, utterance["start"], utterance["end"])
    length = samples.size / SAMPLE_RATE
    ranges = None
    if config.SPEECH_GATE:
        ranges = speech_gate.find_speech(samples.astype(np.float32) / 32768.0, request_id)
        if ranges is not None and speech_gate.spoken_seconds(ranges) < MIN_VOICED_SECONDS:
            return []
    offset = utterance["start"] / SAMPLE_RATE
    model = model_pool.acquire_model()
    try:
        segments = backends.transcriber().get_stt_segments(encode_wav(samples), model=model, language=language)
    finally:
        model_pool.release_model(model)
    segments = speech_gate.keep_spoken(segments, ranges, request_id, length)
    timed = []
    for segment in segments:
        text = segment["text"].strip()
        if not text:
            continue
        # Clamped to the utterance: whisper pads to 30 s and can place segment times past the audio.
        # A segment that starts there was made up in the padding, not heard, and is dropped.
        start = float(segment["start"])
        if start >= length:
            continue
        end = min(float(segment["end"]), length)
        timed.append({"start": round(offset + start, 2), "end": round(offset + end, 2), "text": text})
    return timed


def attribute_live_segments(segments: list[dict[str, Any]], turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give each segment a speaker and an overlap flag from the turns diarized so far.

    Segments are not merged into runs here, unlike the upload path: a live segment has already
    been sent by the time the next one exists.
    """
    attributed = []
    for segment in segments:
        speaker = align.assign_speaker(segment, turns)
        attributed.append({**segment, "speaker": speaker, "overlap": align.is_overlapped(segment, speaker, turns)})
    return attributed


def new_diarization() -> dict[str, Any]:
    """Streaming diarization state for one session; see libs/diarize.py for what it carries."""
    return diarize.new_stream_state()


def advance_diarization(state: dict[str, Any], buffer: dict[str, Any], until: int, final: bool) -> None:
    """Diarize every chunk that has arrived, with a pooled diarizer borrowed for the call only.

    Stops early once the frames reach `until` (absolute samples): nothing past the utterance being
    attributed is needed yet. Raises queue.Empty when no diarizer frees up in time.
    """
    diarizer = model_pool.acquire_diarizer()
    try:
        diarize.advance_stream(
            state, lambda start, end: read_samples(buffer, start, end), buffer["total"], diarizer, until, final
        )
    finally:
        model_pool.release_diarizer(diarizer)


def main():
    """No-op entry point: this module is imported by libs/live.py."""
    pass


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Speaker diarization: who spoke when, as time ranges. This module never produces text."""

import io
import logging
import os
import sys
import time
import traceback

import numpy as np
import soundfile as sf

# Local imports
from libs import config, logs

logger = logging.getLogger(__name__)

# The model card states one input format and one only: 16 kHz, single channel.
TARGET_SAMPLE_RATE = 16000

# The architecture emits eight speaker channels, ordered by arrival time in the audio.
MAX_SPEAKERS = 8

# The model emits one decision per spectrogram frame, one frame every 10 ms (the model card).
STREAM_FRAME_SECONDS = 0.01


def resolve_device(device: str | None = None) -> str:
    """Resolve "auto" to cuda/cpu and reject a device this machine cannot serve.

    Deliberately duplicated from libs/stt.py rather than imported from it: that module pulls
    whisper and torch, and a deployment that wants only diarization should not have to install
    a transcription backend to get a device name.
    """
    import torch

    device = config.COMPUTE_TYPE if device is None else device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device not in ("cpu", "cuda"):
        raise ValueError("Device must be 'cpu' or 'cuda'.")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available on this machine.")
    return device


def describe_backend() -> dict:
    """Describe the diarizer for GET /api/models, loading nothing.

    It has no languages at all: it reports who spoke when and never what was said, so the
    language fields are null rather than an empty list, which would read as "none supported".
    """
    model_id = config.DIARIZE_MODEL
    cached = os.path.join(config.DIARIZE_DOWNLOAD_ROOT, "models--" + model_id.replace("/", "--"))
    return {
        "backend": "diarize",
        "model": model_id,
        "aliases": [],
        "status": "installed" if os.path.isdir(cached) else "absent",
        "multilingual": None,
        "accepts_language": False,
        "languages_source": None,
        "languages": None,
        "max_speakers": MAX_SPEAKERS,
    }


def get_diarizer(model_id: str | None = None, device: str | None = None):
    """Load the diarization processor and model as one pair, ready for inference.

    transformers is imported inside the function on purpose: it pulls torch, and this module
    is imported by the pool, which the Gunicorn master must be able to reach without loading
    either. Returns the pair the rest of this module expects, not a bare model.

    The weights land in DIARIZE_DOWNLOAD_ROOT rather than the default `~/.cache`: the
    container runs as an unprivileged user created with --no-create-home, and only the
    bind-mounted directories are chowned for it, so a cache anywhere else is a PermissionError
    on first run.

    The device comes from COMPUTE_TYPE, not from `device_map="auto"`. Automatic placement
    would quietly ignore an operator who forced cpu or cuda, and it needs accelerate.
    """
    from transformers import AutoModelForAudioFrameClassification, AutoProcessor

    model_id = config.DIARIZE_MODEL if model_id is None else model_id
    os.makedirs(config.DIARIZE_DOWNLOAD_ROOT, exist_ok=True)
    processor = AutoProcessor.from_pretrained(model_id, cache_dir=config.DIARIZE_DOWNLOAD_ROOT)
    model = AutoModelForAudioFrameClassification.from_pretrained(model_id, cache_dir=config.DIARIZE_DOWNLOAD_ROOT)
    model.to(resolve_device(device))
    model.eval()
    return processor, model


def read_mono_16k(bio: io.BytesIO) -> np.ndarray:
    """Decode a WAV buffer into the mono float32 waveform the diarizer accepts.

    Refuses any other sampling rate rather than resampling: libs/audio.py already exports
    16 kHz mono for every request, so a mismatch here means the caller skipped it, and
    silently fixing that would hide the real mistake.
    """
    data, sample_rate = sf.read(bio)
    if sample_rate != TARGET_SAMPLE_RATE:
        raise ValueError(f"Diarization needs {TARGET_SAMPLE_RATE} Hz audio, got {sample_rate} Hz.")
    if data.ndim == 2:
        data = data.mean(axis=1)
    return data.astype(np.float32)


def diarize_wav(bio: io.BytesIO, diarizer=None, threshold: float | None = None) -> list[dict]:
    """Return the speech turns in a WAV buffer as ``{"speaker", "start", "end"}`` dicts.

    torch is imported here rather than at module scope for the same reason transformers is:
    the Gunicorn master imports this module and must not load either.

    Without an explicit `diarizer` one is loaded on the spot, which is slow; the server
    passes a pair borrowed from the pool. Turns come back sorted by start time, and they may
    overlap: the model scores each speaker channel independently, so two people talking at
    once produce two turns covering the same seconds.
    """
    import torch

    if diarizer is None:
        diarizer = get_diarizer()
    processor, model = diarizer

    waveform = read_mono_16k(bio)
    inputs = processor(waveform, sampling_rate=TARGET_SAMPLE_RATE).to(model.device, dtype=model.dtype)
    # model.eval() only switches dropout and batch norm; without this the offline loop keeps
    # every chunk's autograd graph alive, and peak memory grows with the length of the recording.
    with torch.inference_mode():
        logits = model(**inputs).logits
    speaker_dicts = processor.extract_speaker_dict(
        logits,
        inputs.attention_mask,
        threshold=config.DIARIZE_THRESHOLD if threshold is None else threshold,
    )

    turns = [
        {"speaker": int(turn["Speaker"]), "start": float(turn["Start"]), "end": float(turn["End"])} for turn in speaker_dicts[0]
    ]
    turns.sort(key=lambda turn: (turn["start"], turn["speaker"]))
    logger.debug("Diarized %d turns across %d speakers", len(turns), len({t["speaker"] for t in turns}))
    return turns


def new_stream_state() -> dict:
    """State of one streaming diarization session.

    `cache` is the model's speaker cache: it carries each speaker's embeddings from chunk to
    chunk, which is what keeps speaker 0 the same person ten minutes in. `frame` is the next
    spectrogram frame to emit and `next_start` the first sample its chunk reads, which is how far
    back a caller trimming its buffer may go. `activity` holds the per-frame speaker decisions so
    far, one bool array of shape `(frames, 8)` per chunk, at one frame every 10 ms.
    """
    return {"cache": None, "first": True, "frame": 0, "next_start": 0, "activity": [], "frames": 0, "finished": False}


def advance_stream(state: dict, read_samples, total_samples: int, diarizer, until: int, final: bool) -> None:
    """Feed the diarizer every whole chunk that has arrived, following the model card's streaming loop.

    `read_samples(start, end)` returns int16 samples by absolute index; `total_samples` is how many
    have arrived. Chunks have fixed sizes set by the processor's streaming mode; the first one is
    shorter because its analysis windows are centered. With `final` the stream is over and the
    remainder goes in as the last chunk, which the model scores without look-ahead. Stops once the
    emitted frames cover `until` samples, so a caller asks for no more work than it needs.
    """
    import torch

    processor, model = diarizer
    hop = processor.feature_extractor.hop_length
    threshold = config.DIARIZE_THRESHOLD
    while not state["finished"] and state["frames"] * hop < until:
        if state["first"]:
            start, end = 0, processor.num_samples_first_audio_chunk
        else:
            start = processor.audio_chunk_start(state["frame"])
            end = start + processor.num_samples_per_audio_chunk
        last = end > total_samples
        if last and not final:
            return
        samples = read_samples(start, min(end, total_samples))
        # A remainder shorter than one analysis window yields no encoder frame at all, and the
        # model refuses an empty chunk. Nothing in it could be attributed anyway.
        if samples.size < processor.feature_extractor.n_fft:
            state["finished"] = True
            return
        inputs = processor(
            samples.astype(np.float32) / 32768.0,
            sampling_rate=TARGET_SAMPLE_RATE,
            is_streaming=True,
            is_first_audio_chunk=state["first"],
            is_last_audio_chunk=last,
        ).to(model.device, dtype=model.dtype)
        with torch.inference_mode():
            outputs = model(**inputs, speaker_cache=state["cache"])
        state["cache"] = outputs.speaker_cache
        active = (outputs.logits.sigmoid() > threshold)[0].cpu().numpy()
        state["activity"].append(active)
        state["frames"] += active.shape[0]
        state["frame"] += processor.num_mel_frames_per_step
        state["next_start"] = max(0, processor.audio_chunk_start(state["frame"]))
        state["first"] = False
        state["finished"] = last


def stream_turns(state: dict, start: float, end: float) -> list[dict]:
    """The speaker turns diarized so far that fall within [start, end] seconds of the stream.

    Built from the per-frame decisions the same way the processor's extract_speaker_dict builds
    them for a whole file, but only over the window asked for: a session can run for hours, and
    attributing one phrase needs only the frames around it.
    """
    first = max(0, int(start / STREAM_FRAME_SECONDS))
    last = min(state["frames"], int(end / STREAM_FRAME_SECONDS) + 1)
    if last <= first:
        return []
    parts = []
    position = 0
    for chunk in state["activity"]:
        chunk_end = position + chunk.shape[0]
        if chunk_end > first and position < last:
            parts.append(chunk[max(0, first - position) : min(chunk.shape[0], last - position)])
        position = chunk_end
    window = np.concatenate(parts).astype(np.int8)
    edges = np.zeros((1, window.shape[1]), dtype=np.int8)
    changes = np.diff(np.concatenate([edges, window, edges]), axis=0)
    turns = []
    for speaker in range(window.shape[1]):
        starts = np.flatnonzero(changes[:, speaker] == 1)
        ends = np.flatnonzero(changes[:, speaker] == -1)
        for turn_start, turn_end in zip(starts, ends, strict=True):
            turns.append(
                {
                    "speaker": speaker,
                    "start": round((first + int(turn_start)) * STREAM_FRAME_SECONDS, 2),
                    "end": round((first + int(turn_end)) * STREAM_FRAME_SECONDS, 2),
                }
            )
    turns.sort(key=lambda turn: (turn["start"], turn["speaker"]))
    return turns


def main():
    """CLI entry point: print the speech turns of the audio file given as the first argument."""
    logs.setup_logging()
    if len(sys.argv) < 2:
        logger.error("Usage: python3 -m libs.diarize <16 kHz mono wav>")
        sys.exit(1)

    filename = sys.argv[1]
    start_time = time.monotonic()
    try:
        with open(filename, "rb") as audio_file:
            turns = diarize_wav(io.BytesIO(audio_file.read()))
    except Exception as exc:
        logger.error("%s: %s\n%s", type(exc).__name__, exc, traceback.format_exc())
        sys.exit(1)

    for turn in turns:
        logger.info("speaker %d: %.2f - %.2f", turn["speaker"], turn["start"], turn["end"])
    logger.info("%d turns (%.3f sec)", len(turns), time.monotonic() - start_time)


if __name__ == "__main__":
    main()

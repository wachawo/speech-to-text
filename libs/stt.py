#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Whisper wrapper: transcribe audio from a file on disk or from an in-memory WAV buffer."""

import io
import logging
import os
import sys
import time
import traceback
import warnings

import numpy as np
import soundfile as sf
import torch
import torchaudio
import whisper
from pydub import AudioSegment

# Local imports
from libs import config, logs

# Whisper always decodes in FP32 on CPU; the warning carries nothing actionable.
warnings.filterwarnings("ignore", message="FP16 is not supported on CPU; using FP32 instead")

logger = logging.getLogger(__name__)

# Sampling rate Whisper expects; anything else is resampled first.
TARGET_SAMPLE_RATE = 16000

# Language values that mean "let Whisper autodetect".
AUTODETECT_VALUES = ("", "auto")

SUPPORTED_DEVICES = ("cpu", "cuda")


def resolve_device(device: str = config.COMPUTE_TYPE) -> str:
    """Resolve "auto" to cuda/cpu and reject a device this machine cannot serve."""
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device not in SUPPORTED_DEVICES:
        raise ValueError("Device must be 'cpu' or 'cuda'.")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available on this machine.")
    return device


def get_model(device: str = config.COMPUTE_TYPE) -> whisper.Whisper:
    """Load one Whisper model instance onto the resolved device, downloading it if needed."""
    device = resolve_device(device)
    os.makedirs(config.WHISPER_DOWNLOAD_ROOT, exist_ok=True)
    return whisper.load_model(
        config.WHISPER_MODEL,
        device=device,
        download_root=config.WHISPER_DOWNLOAD_ROOT,
    )


def normalize_language(language: str | None) -> str | None:
    """Map a requested language onto Whisper's argument.

    None falls back to the WHISPER_LANGUAGE default, "auto" and "" mean
    autodetect (Whisper takes None for that), anything else is passed through.
    """
    value = config.WHISPER_LANGUAGE if language is None else language
    value = (value or "").strip().lower()
    return None if value in AUTODETECT_VALUES else value


def read_waveform(bio: io.BytesIO) -> np.ndarray:
    """Decode a WAV buffer into a mono float32 waveform at 16 kHz, normalized to [-1.0, 1.0]."""
    data, sample_rate = sf.read(bio)
    if sample_rate != TARGET_SAMPLE_RATE:
        waveform = torch.from_numpy(data).float()
        if waveform.ndim == 2:
            waveform = waveform.mean(dim=1)
        resampler = torchaudio.transforms.Resample(
            orig_freq=sample_rate, new_freq=TARGET_SAMPLE_RATE
        )
        data = resampler(waveform).numpy()
    else:
        if data.ndim == 2:
            data = data.mean(axis=1)
        data = data.astype(np.float32)
    peak = np.abs(data).max()
    if peak > 0:
        data = data / peak
    return data


def get_stt_bio(
    bio: io.BytesIO,
    model: whisper.Whisper | None = None,
    device: str = config.COMPUTE_TYPE,
    language: str | None = None,
) -> str:
    """Transcribe a WAV buffer and return the text.

    A 16 kHz mono buffer (what the server always sends) skips the resampling
    step. Without an explicit `model` one is loaded on the spot, which is slow —
    the server passes an instance borrowed from the pool. Decoding is seeded and
    greedy so the same audio always produces the same text.
    """
    if model is None:
        model = get_model(device=device)
    data = read_waveform(bio)
    torch.manual_seed(0)
    np.random.seed(0)
    result = model.transcribe(
        audio=data,
        language=normalize_language(language),
        task="transcribe",
        temperature=0.0,
        beam_size=1,
        best_of=1,
        condition_on_previous_text=False,
    )
    text = result["text"].strip()
    logger.debug("Transcribed %d chars", len(text))
    return text


def get_stt_filename(
    filename: str,
    model: whisper.Whisper | None = None,
    device: str = config.COMPUTE_TYPE,
    language: str | None = None,
) -> str:
    """Transcribe an audio file from disk by exporting it to a WAV buffer first."""
    if not os.path.exists(filename):
        raise FileNotFoundError(f"File '{filename}' does not exist.")
    audio = AudioSegment.from_file(filename)
    bio = io.BytesIO()
    audio.export(bio, format="wav")
    bio.seek(0)
    return get_stt_bio(bio, model=model, device=device, language=language)


def main():
    """CLI entry point: transcribe the audio file given as the first argument."""
    logs.setup_logging()
    if len(sys.argv) < 2:
        logger.error("Usage: python3 -m libs.stt <audio-file>")
        sys.exit(1)
    filename = sys.argv[1]
    start_time = time.monotonic()
    try:
        text = get_stt_filename(filename)
    except Exception as exc:
        logger.error("%s: %s\n%s", type(exc).__name__, exc, traceback.format_exc())
        sys.exit(1)
    logger.info("STT: %s (%.3f sec)", text, time.monotonic() - start_time)


if __name__ == "__main__":
    main()

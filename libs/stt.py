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
from whisper.tokenizer import LANGUAGES, TO_LANGUAGE_CODE

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

# Whisper's language table is sliced by the checkpoint: the large-v3 lineage was trained on 100
# languages, every other multilingual checkpoint on the first 99, and a `.en` checkpoint on one.
# whisper derives this as `n_vocab - 51765 - int(is_multilingual)`; resolving it from the NAME
# instead means describing the backend does not have to load two gigabytes of weights.
LANGUAGES_100 = ("large-v3", "large", "large-v3-turbo", "turbo")


def resolve_device(device: str | None = None) -> str:
    """Resolve "auto" to cuda/cpu and reject a device this machine cannot serve."""
    device = config.COMPUTE_TYPE if device is None else device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device not in SUPPORTED_DEVICES:
        raise ValueError("Device must be 'cpu' or 'cuda'.")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available on this machine.")
    return device


def get_model(device: str | None = None, model_name: str | None = None) -> whisper.Whisper:
    """Load one Whisper model instance onto the resolved device, downloading it if needed.

    `model_name` None means WHISPER_MODEL, the single-model deployment's checkpoint.
    """
    device = resolve_device(device)
    os.makedirs(config.WHISPER_DOWNLOAD_ROOT, exist_ok=True)
    return whisper.load_model(
        config.WHISPER_MODEL if model_name is None else model_name,
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
        resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=TARGET_SAMPLE_RATE)
        data = resampler(waveform).numpy()
    else:
        if data.ndim == 2:
            data = data.mean(axis=1)
        data = data.astype(np.float32)
    peak = np.abs(data).max()
    if peak > 0:
        data = data / peak
    return data


def resolve_languages(model_name: str) -> list[str]:
    """The language codes a Whisper checkpoint accepts, without loading it.

    A file path is judged by its name: `/models/large-v3.pt` knows 100 codes, `/models/tiny.en.pt` one.
    The name is lower-cased because a path keeps its case: `/models/Tiny.EN.pt` is tiny.en too.
    """
    name = config.build_model_name(model_name).lower()
    if name.endswith(".en"):
        return ["en"]
    return list(LANGUAGES)[: 100 if name in LANGUAGES_100 else 99]


def normalize_language_code(language: str) -> str | None:
    """Map a requested language onto a Whisper code, or None when it knows no such language.

    Accepts a code (`ru`) and a full English name (`russian`), which is what Whisper itself
    accepts; anything else is unknown, and the caller should refuse it rather than let the
    backend raise on a value that only looked plausible.
    """
    value = language.strip().lower()
    if value in LANGUAGES:
        return value
    return TO_LANGUAGE_CODE.get(value)


def is_installed(model_name: str | None = None) -> bool:
    """Whether the checkpoint is already on disk, resolved through whisper's own download name.

    The configured name and the file differ: `turbo` downloads as `large-v3-turbo.pt`, so
    comparing the name against the directory listing would report a running model as missing.
    A filesystem path in WHISPER_MODEL counts as installed when the file exists.
    """
    model_name = config.WHISPER_MODEL if model_name is None else model_name
    if model_name not in whisper._MODELS:
        return os.path.isfile(model_name)
    filename = os.path.basename(whisper._MODELS[model_name])
    return os.path.isfile(os.path.join(config.WHISPER_DOWNLOAD_ROOT, filename))


def list_aliases(model_name: str) -> list[str]:
    """Other names whisper downloads the same checkpoint under (`turbo` and `large-v3-turbo`)."""
    url = whisper._MODELS.get(model_name)
    if not url:
        return []
    return sorted(name for name, other in whisper._MODELS.items() if name != model_name and other == url)


def list_known_models() -> list[str]:
    """Every checkpoint name whisper can download, aliases included, whether loaded or not."""
    return sorted(whisper._MODELS)


def describe_backend(model_name: str | None = None) -> dict:
    """Describe one Whisper checkpoint for GET /api/models, loading nothing; None means WHISPER_MODEL."""
    model_name = config.WHISPER_MODEL if model_name is None else model_name
    return {
        "backend": "whisper",
        "model": model_name,
        "aliases": list_aliases(model_name),
        "status": "installed" if is_installed(model_name) else "absent",
        "multilingual": not config.build_model_name(model_name).lower().endswith(".en"),
        "accepts_language": True,
        "languages_source": "derived",
        "languages": resolve_languages(model_name),
        "default_language": config.WHISPER_LANGUAGE,
    }


def get_stt_result(
    bio: io.BytesIO,
    model: whisper.Whisper | None = None,
    device: str | None = None,
    language: str | None = None,
) -> dict:
    """Transcribe a WAV buffer and return `{"text", "language"}`.

    A 16 kHz mono buffer (what the server always sends) skips the resampling
    step. Without an explicit `model` one is loaded on the spot, which is slow -
    the server passes an instance borrowed from the pool. Decoding is seeded and
    greedy so the same audio always produces the same text.

    `language` is the code whisper detected or was told. An English-only checkpoint always
    decodes English, even when it was handed another code, so it honestly reports `en`.
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
    detected = result.get("language") if model.is_multilingual else "en"
    logger.debug("Transcribed %d chars (language %s)", len(text), detected)
    return {"text": text, "language": detected}


def get_stt_bio(
    bio: io.BytesIO,
    model: whisper.Whisper | None = None,
    device: str | None = None,
    language: str | None = None,
) -> str:
    """Transcribe a WAV buffer and return the text alone; see get_stt_result."""
    return get_stt_result(bio, model=model, device=device, language=language)["text"]


def get_stt_segments(
    bio: io.BytesIO,
    model: whisper.Whisper | None = None,
    device: str | None = None,
    language: str | None = None,
) -> list[dict]:
    """Transcribe a WAV buffer and return its segments with their times.

    The same unmodified decode as get_stt_result, keeping `result["segments"]` instead of
    discarding it. Deliberately NOT `word_timestamps=True`: that flag rewrites `seek` from the
    end of the last word and clears segments of zero duration, whose tokens then never reach
    the text, so it can change the transcription the rest of this module fixes on purpose.
    Segment times come free and change nothing.
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
    # float() rather than the raw values: whisper hands back numpy scalars, which the JSON
    # encoder refuses.
    segments = [
        {"start": float(segment["start"]), "end": float(segment["end"]), "text": segment["text"]}
        for segment in result["segments"]
    ]
    logger.debug("Transcribed %d segments", len(segments))
    return segments


def get_stt_filename(
    filename: str,
    model: whisper.Whisper | None = None,
    device: str | None = None,
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

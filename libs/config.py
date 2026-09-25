#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single place where the environment is read: every tunable of the server, client and Whisper."""

import os
from typing import Any

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

TRUE_VALUES = ("1", "true", "yes", "on", "enabled")

# What a model value must start or end with to be read as a file on disk rather than a name.
MODEL_PATH_PREFIXES = ("/", "./", "../", "~")
MODEL_PATH_SUFFIX = ".pt"


def is_model_path(model: str) -> bool:
    """Whether a model value names a file or directory on disk rather than a published model id."""
    return model.startswith(MODEL_PATH_PREFIXES) or model.endswith(MODEL_PATH_SUFFIX)


def build_model_name(model: str) -> str:
    """The name a model value stands for: the value itself, or for a file path its basename without `.pt`.

    `/opt/models/large-v3.pt` is the large-v3 checkpoint, so everything derived from a name
    (the public id, a Whisper language list) must see `large-v3`, never the path.
    """
    if not is_model_path(model):
        return model
    basename = os.path.basename(model.rstrip("/"))
    if basename.endswith(MODEL_PATH_SUFFIX):
        basename = basename[: -len(MODEL_PATH_SUFFIX)]
    return basename or model


def parse_pool_size(text: str, entry: str) -> int:
    """Parse the @pool suffix of one STT_MODELS entry; a positive integer of ASCII digits or ValueError.

    Plain digits only: int() would also take `1_0`, `+2` or full-width digits, and a typo that
    silently loads ten instances of a large model can exhaust the GPU at startup.
    """
    digits = text.strip()
    if not (digits.isascii() and digits.isdigit()) or int(digits) < 1:
        raise ValueError(f"STT_MODELS entry '{entry}' has an invalid pool size")
    return int(digits)


def parse_model_entry(entry: str) -> dict[str, Any]:
    """Parse one `backend:model[@pool]` entry; pool_size None means STT_POOL_SIZE.

    The backend ends at the FIRST colon and the pool starts at the LAST at sign, so a model
    path may carry either character; a path containing `@` must therefore end in an explicit
    `@pool`. A Whisper name is lower-cased like WHISPER_MODEL, a file path keeps its case.
    """
    backend, separator, remainder = entry.partition(":")
    backend = backend.strip().lower()
    if not separator or not backend:
        raise ValueError(f"STT_MODELS entry '{entry}' must look like backend:model[@pool]")
    pool_size = None
    if "@" in remainder:
        remainder, pool_text = remainder.rsplit("@", 1)
        pool_size = parse_pool_size(pool_text, entry)
    model = remainder.strip()
    if not model:
        raise ValueError(f"STT_MODELS entry '{entry}' has no model")
    if backend == "whisper" and not is_model_path(model):
        model = model.lower()
    return {"backend": backend, "model": model, "pool_size": pool_size}


def parse_model_list(raw: str) -> tuple[dict[str, Any], ...]:
    """Parse STT_MODELS into entries {"backend", "model", "pool_size"}; pool_size None means STT_POOL_SIZE.

    Only the syntax is checked here. Whether the backend exists and whether two entries name the
    same weights is decided by libs/registry.py, which may import the backends.
    """
    entries = (entry.strip() for entry in raw.split(","))
    return tuple(parse_model_entry(entry) for entry in entries if entry)


# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_ACCESS = os.getenv("LOG_ACCESS", "false").lower() in TRUE_VALUES

# HTTP server
STT_HOST = os.getenv("STT_HOST", "0.0.0.0")
STT_PORT = int(os.getenv("STT_PORT", "5099"))
STT_DEBUG = os.getenv("STT_DEBUG", "false").lower() in TRUE_VALUES

# Number of instances pre-loaded into a model's pool at startup: the pool of the single model
# when STT_MODELS is empty, and the default for an STT_MODELS entry without its own @pool.
MODEL_POOL_SIZE = int(os.getenv("STT_POOL_SIZE", "8"))

# Static-token auth - an empty set means "auth disabled, allow all" (trusted deployment).
STT_TOKENS: set[str] = {t.strip() for t in os.getenv("STT_TOKENS", "").split(",") if t.strip()}

# Max request body size - caps memory usage per request to mitigate OOM/DoS.
# Flask returns 413 automatically when exceeded.
MAX_CONTENT_LENGTH_MB = int(os.getenv("MAX_CONTENT_LENGTH_MB", "10"))

# CORS allowed origins. "*" allows any origin; otherwise a comma-separated allowlist.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# Gunicorn worker processes (used only when the service is started through gu.py).
GUNICORN_WORKERS = int(os.getenv("GUNICORN_WORKERS", "4"))

# Whisper backend
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small.en").lower()
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "en").lower()
WHISPER_DOWNLOAD_ROOT = os.getenv("WHISPER_DOWNLOAD_ROOT", "models")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "auto").lower()

# Which backend transcribes when STT_MODELS is empty. With STT_MODELS set it is ignored.
STT_BACKEND = os.getenv("STT_BACKEND", "whisper")

# Parakeet, the optional second transcription backend. It detects the language itself and
# takes no language argument, which GET /api/models reports as accepts_language false.
PARAKEET_MODEL = os.getenv("PARAKEET_MODEL", "nvidia/parakeet-tdt-0.6b-v3")
PARAKEET_DOWNLOAD_ROOT = os.getenv("PARAKEET_DOWNLOAD_ROOT", "models")

# Several transcription models served side by side, each with its own pool. Empty keeps the
# single-model deployment chosen by STT_BACKEND / WHISPER_MODEL / PARAKEET_MODEL.
STT_MODELS = parse_model_list(os.getenv("STT_MODELS", ""))
# The model a request without `model` uses; empty means the first STT_MODELS entry.
STT_DEFAULT_MODEL = os.getenv("STT_DEFAULT_MODEL", "").strip()

# Speaker diarization. Off by default: the model is an optional extra, it is documented for
# NVIDIA GPUs only, and a deployment that does not want it should stay byte-identical to one
# that never heard of it.
DIARIZE_ENABLED = os.getenv("DIARIZE_ENABLED", "false").lower() in TRUE_VALUES
DIARIZE_MODEL = os.getenv("DIARIZE_MODEL", "nvidia/Nemotron-3-Diarization")
DIARIZE_POOL_SIZE = int(os.getenv("DIARIZE_POOL_SIZE", "1"))
DIARIZE_DOWNLOAD_ROOT = os.getenv("DIARIZE_DOWNLOAD_ROOT", "models")
# Frames whose activity probability clears this are counted as speech. 0.5 is the default
# baked into the processor's extract_speaker_dict.
DIARIZE_THRESHOLD = float(os.getenv("DIARIZE_THRESHOLD", "0.5"))

# CLI client
STT_URL = os.getenv("STT_URL", "http://localhost:5099")
STT_TOKEN = os.getenv("STT_TOKEN", "").strip()


def main():
    """No-op entry point: this module only exposes configuration constants."""
    pass


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single place where the environment is read: every tunable of the server, client and Whisper."""

import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

TRUE_VALUES = ("1", "true", "yes", "on", "enabled")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_ACCESS = os.getenv("LOG_ACCESS", "false").lower() in TRUE_VALUES

# HTTP server
STT_HOST = os.getenv("STT_HOST", "0.0.0.0")
STT_PORT = int(os.getenv("STT_PORT", "5099"))
STT_DEBUG = os.getenv("STT_DEBUG", "false").lower() in TRUE_VALUES

# Number of Whisper instances pre-loaded into the pool at startup.
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

# Which backend transcribes: "whisper" or "parakeet". A deploy-time choice, not a per-request
# one - a second resident ASR would mean a second set of weights in every worker.
STT_BACKEND = os.getenv("STT_BACKEND", "whisper")

# Parakeet, the optional second transcription backend. It detects the language itself and
# takes no language argument, which GET /api/models reports as accepts_language false.
PARAKEET_MODEL = os.getenv("PARAKEET_MODEL", "nvidia/parakeet-tdt-0.6b-v3")
PARAKEET_DOWNLOAD_ROOT = os.getenv("PARAKEET_DOWNLOAD_ROOT", "models")

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

# Speech gate: a voice detector drops transcribed segments nobody spoke - Whisper's credit-line
# hallucinations on tone, music, noise and silence. On by default; off is the old behaviour.
SPEECH_GATE = os.getenv("SPEECH_GATE", "true").lower() in TRUE_VALUES

# CLI client
STT_URL = os.getenv("STT_URL", "http://localhost:5099")
STT_TOKEN = os.getenv("STT_TOKEN", "").strip()


def main():
    """No-op entry point: this module only exposes configuration constants."""
    pass


if __name__ == "__main__":
    main()

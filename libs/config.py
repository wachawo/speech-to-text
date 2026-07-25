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

# Static-token auth — an empty set means "auth disabled, allow all" (trusted deployment).
STT_TOKENS: set[str] = {t.strip() for t in os.getenv("STT_TOKENS", "").split(",") if t.strip()}

# Max request body size — caps memory usage per request to mitigate OOM/DoS.
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

# CLI client
STT_URL = os.getenv("STT_URL", "http://localhost:5099")
STT_TOKEN = os.getenv("STT_TOKEN", "").strip()


def main():
    """No-op entry point: this module only exposes configuration constants."""
    pass


if __name__ == "__main__":
    main()

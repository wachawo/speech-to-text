#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STT client — send audio files to stt_server and print transcriptions.

Usage:
    python stt_client.py file1.mp3 file2.wav ...
    python stt_client.py recs/2026-03-27/*.mp3

Environment:
    STT_URL    — server base URL (default: http://localhost:5099)
    STT_TOKEN  — optional static token sent as `Authorization: Bearer <token>`
"""

import logging
import os
import sys
import time

import requests
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# Logging
LOGGING = {
    "handlers": [logging.StreamHandler()],
    "format": "%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s.%(funcName)s) %(message)s",
    "level": logging.INFO,
    "datefmt": "%Y-%m-%d %H:%M:%S",
}
logging.basicConfig(**LOGGING)
logger = logging.getLogger(__name__)

STT_URL = os.getenv("STT_URL", "http://localhost:5099")
STT_TOKEN = os.getenv("STT_TOKEN", "").strip()


def transcribe_file(filepath: str) -> dict:
    """Send a single file to /api/stt and return response JSON."""
    headers = {"Authorization": f"Bearer {STT_TOKEN}"} if STT_TOKEN else {}
    with open(filepath, "rb") as f:
        resp = requests.post(
            f"{STT_URL}/api/stt",
            files={"file": (os.path.basename(filepath), f)},
            headers=headers,
            timeout=120,
        )
    resp.raise_for_status()
    return resp.json()


def main():
    if len(sys.argv) < 2:
        logger.error(f"Usage: {sys.argv[0]} <file1> [file2] ...")
        sys.exit(1)

    files = sys.argv[1:]
    total = len(files)

    for i, filepath in enumerate(files, 1):
        if not os.path.isfile(filepath):
            logger.warning(f"[{i}/{total}] SKIP {filepath} — not found")
            continue

        size_kb = os.path.getsize(filepath) // 1024
        t0 = time.monotonic()

        try:
            result = transcribe_file(filepath)
            elapsed = time.monotonic() - t0
            text = result.get("text", "")
            srv = result.get("elapsed", 0)
            logger.info(
                f"[{i}/{total}] {filepath} ({size_kb}kb) → {text} (server={srv:.2f}s total={elapsed:.2f}s)"
            )
        except requests.HTTPError as e:
            resp = e.response
            logger.error(f"[{i}/{total}] {filepath}: {resp.status_code} {resp.reason} {resp.text}")
        except Exception as e:
            import traceback

            logger.error(
                f"[{i}/{total}] {filepath}: {type(e).__name__} {str(e)} {traceback.format_exc()}"
            )


if __name__ == "__main__":
    main()

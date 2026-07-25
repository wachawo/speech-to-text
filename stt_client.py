#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI client: post audio files to a running stt_server and log the transcriptions."""

import logging
import os
import sys
import time
import traceback

import requests

# Local imports
from libs import config, logs

logs.setup_logging()
logger = logging.getLogger(__name__)

# Generous enough for a cold model pool on the server side.
REQUEST_TIMEOUT = 120


def build_headers() -> dict[str, str]:
    """Build the request headers, adding the bearer token only when one is configured."""
    if not config.STT_TOKEN:
        return {}
    return {"Authorization": f"Bearer {config.STT_TOKEN}"}


def transcribe_file(filepath: str) -> dict:
    """Post a single file to /api/stt and return the decoded JSON response."""
    with open(filepath, "rb") as audio_file:
        resp = requests.post(
            f"{config.STT_URL}/api/stt",
            files={"file": (os.path.basename(filepath), audio_file)},
            headers=build_headers(),
            timeout=REQUEST_TIMEOUT,
        )
    resp.raise_for_status()
    return resp.json()


def transcribe_and_log(filepath: str, position: str) -> None:
    """Transcribe one file and log the result, or the reason it failed."""
    if not os.path.isfile(filepath):
        logger.warning("%s SKIP %s - not found", position, filepath)
        return

    size_kb = os.path.getsize(filepath) // 1024
    start_time = time.monotonic()
    try:
        result = transcribe_file(filepath)
    except requests.HTTPError as exc:
        resp = exc.response
        logger.error(
            "%s %s: %s %s %s", position, filepath, resp.status_code, resp.reason, resp.text
        )
        return
    except Exception as exc:
        logger.error(
            "%s %s: %s: %s\n%s",
            position,
            filepath,
            type(exc).__name__,
            exc,
            traceback.format_exc(),
        )
        return

    logger.info(
        "%s %s (%dkb) -> %s (server=%.2fs total=%.2fs)",
        position,
        filepath,
        size_kb,
        result.get("text", ""),
        result.get("elapsed", 0),
        time.monotonic() - start_time,
    )


def main():
    """Entry point: transcribe every file given on the command line, in order."""
    if len(sys.argv) < 2:
        logger.error("Usage: %s <file1> [file2] ...", sys.argv[0])
        sys.exit(1)

    files = sys.argv[1:]
    for index, filepath in enumerate(files, 1):
        transcribe_and_log(filepath, f"[{index}/{len(files)}]")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI client: post audio files to a running stt_server, or stream one live, and log the transcriptions."""

import argparse
import json
import logging
import os
import sys
import threading
import time
import traceback

import requests
from pydub import AudioSegment
from websockets.sync.client import connect

# Local imports
from libs import config, logs

logs.setup_logging()
logger = logging.getLogger(__name__)

# Generous enough for a cold model pool on the server side.
REQUEST_TIMEOUT = 120

# A hundred language codes on one line is not a listing anybody reads.
LANGUAGES_SHOWN = 8

# A live stream is sent in 100 ms frames of 16 kHz mono 16-bit PCM, paced at the speed of speech:
# the server cuts utterances at pauses, and a file dumped at once has none in wall-clock time.
STREAM_SAMPLE_RATE = 16000
STREAM_FRAME_SECONDS = 0.1


def build_headers() -> dict[str, str]:
    """Build the request headers, adding the bearer token only when one is configured."""
    if not config.STT_TOKEN:
        return {}
    return {"Authorization": f"Bearer {config.STT_TOKEN}"}


def fetch_models() -> dict:
    """GET /api/models and return the decoded catalogue."""
    resp = requests.get(f"{config.STT_URL}/api/models", headers=build_headers(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def log_models() -> None:
    """Print what the server carries: one line per backend, languages truncated to stay readable."""
    catalogue = fetch_models()
    logger.info("Default backend: %s", catalogue.get("default", "?"))
    for row in catalogue.get("models", []):
        languages = row.get("languages")
        if languages is None:
            spoken = "-"
        elif len(languages) > LANGUAGES_SHOWN:
            spoken = f"{', '.join(languages[:LANGUAGES_SHOWN])} (+{len(languages) - LANGUAGES_SHOWN} more)"
        else:
            spoken = ", ".join(languages)
        logger.info(
            "%-9s %-34s %-9s lang=%-5s %s",
            row.get("backend", "?"),
            row.get("model", "?"),
            row.get("status", "?"),
            "yes" if row.get("accepts_language") else "no",
            spoken,
        )


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
        logger.error("%s %s: %s %s %s", position, filepath, resp.status_code, resp.reason, resp.text)
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


def build_stream_url() -> str:
    """The websocket address of /api/stream on the configured server."""
    if config.STT_URL.startswith("https://"):
        return "wss://" + config.STT_URL[len("https://") :] + "/api/stream"
    return "ws://" + config.STT_URL.removeprefix("http://") + "/api/stream"


def read_stream_pcm(filepath: str) -> bytes:
    """Decode any audio file into the raw PCM the stream protocol carries."""
    audio = AudioSegment.from_file(filepath)
    return audio.set_channels(1).set_frame_rate(STREAM_SAMPLE_RATE).set_sample_width(2).raw_data


def send_stream_audio(websocket, pcm: bytes) -> None:
    """Send the audio frame by frame in real time, then say stop."""
    frame_bytes = int(STREAM_SAMPLE_RATE * STREAM_FRAME_SECONDS) * 2
    start_time = time.monotonic()
    for index, offset in enumerate(range(0, len(pcm), frame_bytes)):
        delay = start_time + index * STREAM_FRAME_SECONDS - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        websocket.send(pcm[offset : offset + frame_bytes])
    websocket.send(json.dumps({"type": "stop"}))


def log_stream_event(event: dict) -> None:
    """Log one server message: a segment as it arrives, the summary, or the error."""
    if event["type"] == "segment":
        speaker = "-" if event["speaker"] is None else f"Speaker {event['speaker'] + 1}"
        logger.info("[%7.2f - %7.2f] %s: %s", event["start"], event["end"], speaker, event["text"])
    elif event["type"] == "done":
        logger.info("Done - %d segments, %.1fs of audio (%.2fs)", event["segments"], event["seconds"], event["elapsed"])
    elif event["type"] == "error":
        logger.error("Stream refused: %s (request %s)", event["error"], event["request_id"])


def stream_file(filepath: str, language: str | None, speakers: bool) -> None:
    """Stream one file to /api/stream as if it were live and log every segment as it comes back."""
    pcm = read_stream_pcm(filepath)
    logger.info("Streaming %s (%.1fs) to %s", filepath, len(pcm) / 2 / STREAM_SAMPLE_RATE, build_stream_url())
    with connect(build_stream_url(), additional_headers=build_headers()) as websocket:
        websocket.send(json.dumps({"type": "start", "language": language, "diarize": speakers}))
        ready = json.loads(websocket.recv())
        if ready["type"] != "ready":
            log_stream_event(ready)
            return
        sender = threading.Thread(target=send_stream_audio, args=(websocket, pcm), daemon=True)
        sender.start()
        for message in websocket:
            event = json.loads(message)
            log_stream_event(event)
            if event["type"] in ("done", "error"):
                break


def main():
    """Entry point: transcribe every file given on the command line, list the models, or stream one file."""
    parser = argparse.ArgumentParser(description="Client for stt_server (STT_URL, STT_TOKEN from the environment).")
    parser.add_argument("files", nargs="*", help="audio files to transcribe with POST /api/stt")
    parser.add_argument("--list", action="store_true", help="list the models and languages the server carries")
    parser.add_argument("--stream", metavar="FILE", help="stream one file over /api/stream in real time")
    parser.add_argument("--speakers", action="store_true", help="with --stream: attribute each segment to a speaker")
    parser.add_argument("--language", help="with --stream: a language code, or auto")
    args = parser.parse_args()

    if not (args.files or args.list or args.stream):
        parser.print_usage(sys.stderr)
        sys.exit(1)

    if args.list or args.stream:
        try:
            if args.list:
                log_models()
            else:
                stream_file(args.stream, args.language, args.speakers)
        except Exception as exc:
            logger.error("%s: %s\n%s", type(exc).__name__, exc, traceback.format_exc())
            sys.exit(1)
        return

    for index, filepath in enumerate(args.files, 1):
        transcribe_and_log(filepath, f"[{index}/{len(args.files)}]")


if __name__ == "__main__":
    main()

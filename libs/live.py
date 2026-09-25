#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live transcription over a websocket: the /api/stream protocol, one session per connection.

The client opens the socket and sends one JSON start message, then raw PCM (signed 16-bit
little-endian, mono, 16 kHz) as binary messages, then `{"type": "stop"}`. The server answers
`ready`, then a `segment` for every phrase as soon as it is transcribed, `progress` about once a
second, and `done` before it closes. Any failure is one `error` message and a close.

This is plain ASGI, not Flask: a WSGI app cannot hold a socket open. Blocking model calls go to
a worker thread so the event loop keeps receiving audio while a phrase is being transcribed.
"""

import asyncio
import json
import logging
import queue
import time
import traceback
import uuid
from collections import deque
from typing import Any

import numpy as np

# Local imports
from libs import auth, backends, config, diarize, model_pool, stream

logger = logging.getLogger(__name__)

STREAM_PATH = "/api/stream"

# A client that connects and says nothing is not going to start; the socket is not held for it.
START_TIMEOUT = 10

# How often `progress` reports the audio received, in seconds of audio.
PROGRESS_SECONDS = 1.0

# Close codes (RFC 6455): normal, policy violation (auth), unsupported data (a malformed
# message), try again later (a busy pool) and internal error.
CLOSE_NORMAL = 1000
CLOSE_POLICY = 1008
CLOSE_UNSUPPORTED = 1003
CLOSE_TRY_LATER = 1013
CLOSE_INTERNAL = 1011

CLOSE_CODES = {
    "Unauthorized": CLOSE_POLICY,
    "Invalid start message": CLOSE_UNSUPPORTED,
    "Invalid language": CLOSE_UNSUPPORTED,
    "Invalid audio frame": CLOSE_UNSUPPORTED,
    "Diarization disabled": CLOSE_TRY_LATER,
    "Diarization unavailable": CLOSE_TRY_LATER,
    "Service Unavailable": CLOSE_TRY_LATER,
}

# With no utterance to transcribe for this long, the worker catches the diarizer up and trims
# the buffer, so a long silence neither piles up audio nor leaves the diarizer an hour behind.
IDLE_SECONDS = 1.0


def read_header_token(scope: dict[str, Any]) -> str:
    """The bearer token from the handshake's Authorization header, for clients that can set one.

    Browsers cannot set headers on a websocket, which is why the start message may carry the
    token instead.
    """
    for name, value in scope.get("headers", []):
        if name.lower() == b"authorization":
            header = value.decode("latin-1")
            if header.startswith(auth.BEARER_PREFIX):
                return header[len(auth.BEARER_PREFIX) :].strip()
    return ""


def check_start(scope: dict[str, Any], start: Any) -> tuple[str | None, dict[str, Any]]:
    """Validate the start message. Returns an error category, or None and the session options."""
    if not isinstance(start, dict) or start.get("type") != "start":
        return "Invalid start message", {}
    if config.STT_TOKENS:
        token = str(start.get("token") or "") or read_header_token(scope)
        if not auth.is_valid_token(token):
            return "Unauthorized", {}

    language = start.get("language")
    if language is not None and not isinstance(language, str):
        return "Invalid start message", {}
    language = (language or "").strip().lower() or None
    if language is not None:
        language = backends.resolve_language(language)
        if language is None:
            return "Invalid language", {}

    speakers = bool(start.get("diarize"))
    if speakers and not config.DIARIZE_ENABLED:
        return "Diarization disabled", {}
    if speakers and not model_pool.diarizer_ready():
        return "Diarization unavailable", {}
    return None, {"language": language, "diarize": speakers}


def new_session(options: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Everything one connection owns: its samples, its pause detector, its diarizer state."""
    return {
        "request_id": request_id,
        "language": options["language"],
        "buffer": stream.new_buffer(),
        "segmenter": stream.new_segmenter(),
        "diarization": stream.new_diarization() if options["diarize"] else None,
        "pending": deque(),
        "wake": asyncio.Event(),
        "final": False,
        "segments": 0,
        "reported": 0,
        "started": time.monotonic(),
    }


def build_sender(send):
    """Wrap the ASGI send so the reader and the worker never interleave two messages."""
    lock = asyncio.Lock()

    async def send_event(event: dict[str, Any]) -> None:
        """Send one protocol message as JSON text."""
        async with lock:
            await send({"type": "websocket.send", "text": json.dumps(event, ensure_ascii=False)})

    return send_event


def queue_utterances(session: dict[str, Any], final: bool = False) -> None:
    """Run the pause detector over what has arrived and queue every utterance that closed."""
    closed = stream.advance_segmenter(session["segmenter"], session["buffer"], final=final)
    if closed:
        session["pending"].extend(closed)
        session["wake"].set()


async def report_progress(session: dict[str, Any], send_event) -> None:
    """Send `progress` when another second of audio has arrived since the last report."""
    received = session["buffer"]["total"] / stream.SAMPLE_RATE
    if received - session["reported"] >= PROGRESS_SECONDS:
        session["reported"] = received
        await send_event({"type": "progress", "seconds": round(received, 1)})


async def read_client_audio(session: dict[str, Any], receive, send_event) -> str:
    """Take audio from the socket until the client says stop or goes away.

    Returns "stop", "disconnect" or an error category.
    """
    while True:
        message = await receive()
        if message["type"] == "websocket.disconnect":
            return "disconnect"
        data = message.get("bytes")
        if data is not None:
            if len(data) % stream.SAMPLE_WIDTH:
                return "Invalid audio frame"
            stream.append_samples(session["buffer"], np.frombuffer(data, dtype="<i2"))
            queue_utterances(session)
            await report_progress(session, send_event)
            continue
        try:
            control = json.loads(message.get("text") or "")
        except ValueError:
            continue
        if isinstance(control, dict) and control.get("type") == "stop":
            return "stop"


def find_keep_from(session: dict[str, Any]) -> int:
    """The earliest sample anything still needs: a queued utterance, the pause detector, the diarizer."""
    segmenter = session["segmenter"]
    if segmenter["in_speech"]:
        keep_from = segmenter["speech_start"]
    else:
        keep_from = max(segmenter["cut_floor"], segmenter["position"] - int(stream.PRE_ROLL_SECONDS * stream.SAMPLE_RATE))
    if session["pending"]:
        keep_from = min(keep_from, session["pending"][0]["start"])
    if session["diarization"] is not None and not session["diarization"]["finished"]:
        keep_from = min(keep_from, session["diarization"]["next_start"])
    return keep_from


async def process_utterance(session: dict[str, Any], utterance: dict[str, int]) -> list[dict[str, Any]]:
    """Diarize up to the end of the utterance, transcribe it, and attribute its segments."""
    diarization = session["diarization"]
    if diarization is not None:
        await asyncio.to_thread(stream.advance_diarization, diarization, session["buffer"], utterance["end"], session["final"])
    segments = await asyncio.to_thread(stream.transcribe_utterance, session["buffer"], utterance, session["language"])
    if diarization is None:
        return [{**segment, "speaker": None, "overlap": False} for segment in segments]
    start = utterance["start"] / stream.SAMPLE_RATE
    end = utterance["end"] / stream.SAMPLE_RATE
    return stream.attribute_live_segments(segments, diarize.stream_turns(diarization, start, end))


async def catch_up(session: dict[str, Any]) -> None:
    """Diarize whatever has arrived while nothing needs transcribing, then drop what nobody needs."""
    diarization = session["diarization"]
    if diarization is not None and not diarization["finished"]:
        buffer = session["buffer"]
        await asyncio.to_thread(stream.advance_diarization, diarization, buffer, buffer["total"], False)
    stream.trim_samples(session["buffer"], find_keep_from(session))


async def run_worker(session: dict[str, Any], send_event) -> str | None:
    """Transcribe utterances in order as they close. Returns None when the stream ended, or an error.

    An utterance stays at the head of the queue until it is done, so trimming never drops audio
    the worker is still reading.
    """
    request_id = session["request_id"]
    while True:
        try:
            if session["pending"]:
                segments = await process_utterance(session, session["pending"][0])
                session["pending"].popleft()
                for segment in segments:
                    session["segments"] += 1
                    await send_event({"type": "segment", "id": session["segments"], **segment})
                stream.trim_samples(session["buffer"], find_keep_from(session))
                continue
            if session["final"]:
                return None
            session["wake"].clear()
            try:
                await asyncio.wait_for(session["wake"].wait(), timeout=IDLE_SECONDS)
            except TimeoutError:
                await catch_up(session)
        except queue.Empty:
            logger.warning("[%s] Stream: model pool exhausted: %s", request_id, model_pool.get_pool_status())
            return "Service Unavailable"
        except Exception as exc:
            logger.error("[%s] Stream failed: %s: %s\n%s", request_id, type(exc).__name__, exc, traceback.format_exc())
            return "Transcription failed"


async def close_socket(send, code: int) -> None:
    """Close the socket; a client that is already gone is not an error worth a traceback."""
    try:
        await send({"type": "websocket.close", "code": code})
    except Exception as exc:
        logger.debug("Close after the client left: %s: %s", type(exc).__name__, exc)


async def fail_session(send, send_event, error: str, request_id: str) -> None:
    """Report one error in the same shape as every HTTP error body, then close."""
    try:
        await send_event({"type": "error", "error": error, "request_id": request_id})
    except Exception as exc:
        logger.debug("[%s] Error not delivered: %s: %s", request_id, type(exc).__name__, exc)
    await close_socket(send, CLOSE_CODES.get(error, CLOSE_INTERNAL))


async def read_start(receive) -> Any:
    """The first message, decoded; None when it is missing, late or not JSON text."""
    try:
        message = await asyncio.wait_for(receive(), timeout=START_TIMEOUT)
    except TimeoutError:
        return None
    if message["type"] != "websocket.receive" or not message.get("text"):
        return None
    try:
        return json.loads(message["text"])
    except ValueError:
        return None


async def stop_task(task: asyncio.Task) -> None:
    """Cancel a task and wait for it, so nothing of the session outlives the connection."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def run_session(session: dict[str, Any], receive, send, send_event) -> None:
    """Read audio and transcribe it concurrently until the stream ends, fails or is dropped."""
    request_id = session["request_id"]
    reader = asyncio.create_task(read_client_audio(session, receive, send_event))
    worker = asyncio.create_task(run_worker(session, send_event))
    try:
        await asyncio.wait({reader, worker}, return_when=asyncio.FIRST_COMPLETED)
        if worker.done():
            # The worker only returns early on a failure; the reader is still waiting for audio.
            await stop_task(reader)
            await fail_session(send, send_event, worker.result() or "Transcription failed", request_id)
            return

        outcome = reader.result()
        if outcome == "disconnect":
            logger.info(
                "[%s] Stream dropped by the client after %.1fs of audio",
                request_id,
                session["buffer"]["total"] / stream.SAMPLE_RATE,
            )
            await stop_task(worker)
            return
        if outcome != "stop":
            await stop_task(worker)
            await fail_session(send, send_event, outcome, request_id)
            return

        queue_utterances(session, final=True)
        session["final"] = True
        session["wake"].set()
        error = await worker
        if error:
            await fail_session(send, send_event, error, request_id)
            return
        seconds = session["buffer"]["total"] / stream.SAMPLE_RATE
        elapsed = time.monotonic() - session["started"]
        await send_event(
            {"type": "done", "segments": session["segments"], "seconds": round(seconds, 2), "elapsed": round(elapsed, 3)}
        )
        logger.info(
            "[%s] Stream finished - %.1fs of audio, %d segments (%.2fs)", request_id, seconds, session["segments"], elapsed
        )
        await close_socket(send, CLOSE_NORMAL)
    finally:
        for task in (reader, worker):
            if not task.done():
                await stop_task(task)


async def handle_stream(scope: dict[str, Any], receive, send) -> None:
    """Serve one /api/stream connection from handshake to close."""
    request_id = uuid.uuid4().hex[:12]
    if (await receive())["type"] != "websocket.connect":
        return
    await send({"type": "websocket.accept"})
    send_event = build_sender(send)

    error, options = check_start(scope, await read_start(receive))
    if error:
        logger.warning("[%s] Stream refused: %s", request_id, error)
        await fail_session(send, send_event, error, request_id)
        return

    session = new_session(options, request_id)
    logger.info(
        "[%s] Stream started - backend %s, language %s, diarize %s",
        request_id,
        backends.transcriber_name(),
        options["language"] or "default",
        "on" if options["diarize"] else "off",
    )
    await send_event(
        {
            "type": "ready",
            "sample_rate": stream.SAMPLE_RATE,
            "backend": backends.transcriber_name(),
            "language": options["language"],
            "diarize": options["diarize"],
        }
    )
    try:
        await run_session(session, receive, send, send_event)
    except Exception as exc:
        # A client that vanishes mid-send surfaces here as whatever the server library raises.
        logger.warning("[%s] Stream ended abnormally: %s: %s", request_id, type(exc).__name__, exc)


def main():
    """No-op entry point: stt_server.py mounts handle_stream on STREAM_PATH."""
    pass


if __name__ == "__main__":
    main()

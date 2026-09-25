#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live transcription over a websocket: the /api/stream protocol, one session per connection.

The client opens the socket and sends one JSON start message, then raw PCM (signed 16-bit
little-endian, mono, 16 kHz) as binary messages, then `{"type": "stop"}`. The server answers
`ready`, then a `segment` for every phrase as soon as it is transcribed, `progress` about once a
second, and `done` before it closes. Any failure is one `error` message and a close.

With `"source": "url"` in the start message the client sends no audio: the server reads the
stream at that address itself, through ffmpeg, until it ends or the client says stop.

An optional `"model"` in the start message picks one of the models loaded at startup, named as
`model` is on /api/stt; without it the default model serves. Every phrase borrows an instance of
that model from its pool, and the language is checked against that model's own list.

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
from urllib.parse import urlsplit

import numpy as np

# Local imports
from libs import auth, backends, config, diarize, model_pool, registry, stream

logger = logging.getLogger(__name__)

STREAM_PATH = "/api/stream"

# A client that connects and says nothing is not going to start; the socket is not held for it.
START_TIMEOUT = 10

# How often `progress` reports the audio received, in seconds of audio.
PROGRESS_SECONDS = 1.0

# What a URL source may be. Network media protocols only: ffmpeg also reads local files and a
# dozen pseudo-protocols (file:, concat:, data:, pipe:), and a playlist fetched over http can
# point at any of them, so the scheme is checked here and ffmpeg is held to a whitelist below.
URL_SCHEMES = ("http", "https", "rtmp", "rtmps", "rtsp", "srt")
FFMPEG_PROTOCOLS = "http,https,tls,tcp,udp,rtp,rtmp,rtmps,rtsp,srt,hls,crypto,httpproxy"

# How long ffmpeg may wait on a silent connection before giving up, in microseconds.
FFMPEG_RW_TIMEOUT = 15_000_000

# Bytes read from ffmpeg at a time: 100 ms of 16 kHz mono 16-bit audio.
FFMPEG_READ_BYTES = 3200

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
    "Invalid model": CLOSE_UNSUPPORTED,
    "Model not loaded": CLOSE_UNSUPPORTED,
    "Invalid language": CLOSE_UNSUPPORTED,
    "Unsupported language": CLOSE_UNSUPPORTED,
    "Invalid audio frame": CLOSE_UNSUPPORTED,
    "Invalid stream URL": CLOSE_UNSUPPORTED,
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

    model = start.get("model")
    language = start.get("language")
    if model is not None and not isinstance(model, str):
        return "Invalid start message", {}
    if language is not None and not isinstance(language, str):
        return "Invalid start message", {}
    # The same order as /api/stt: the model first, then the language against that model.
    requested_model = (model or "").strip() or None
    spec, error = registry.resolve_request_model(requested_model)
    if spec is None:
        return error or registry.INVALID_MODEL, {}
    language = (language or "").strip().lower() or None
    if requested_model is None:
        # A client that sends nothing new is checked exactly as before: only whether the value is
        # a language at all. A code the default model lacks fails later, when a phrase is transcribed.
        language, error = backends.resolve_language_code(language, spec)
    else:
        language, error = backends.resolve_language(language, spec, explicit=True)
    if error:
        return error, {}

    source = start.get("source") or "client"
    url = start.get("url")
    if source not in ("client", "url"):
        return "Invalid start message", {}
    if source == "url" and not is_allowed_url(url):
        return "Invalid stream URL", {}

    speakers = bool(start.get("diarize"))
    if speakers and not config.DIARIZE_ENABLED:
        return "Diarization disabled", {}
    if speakers and not model_pool.diarizer_ready():
        return "Diarization unavailable", {}
    return None, {"spec": spec, "language": language, "diarize": speakers, "source": source, "url": url}


def is_allowed_url(url: Any) -> bool:
    """Whether a URL source is a network address in one of the schemes ffmpeg is allowed to read."""
    if not isinstance(url, str):
        return False
    parts = urlsplit(url.strip())
    return parts.scheme.lower() in URL_SCHEMES and bool(parts.hostname)


def new_session(options: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Everything one connection owns: its samples, its pause detector, its diarizer state."""
    return {
        "request_id": request_id,
        "spec": options["spec"],
        "language": options["language"],
        "url": options["url"] if options["source"] == "url" else None,
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


async def start_ffmpeg(url: str):
    """Start ffmpeg decoding the URL into the stream protocol's PCM on its stdout.

    `-re` reads at the source's own pace: a finite file behind the URL then behaves like a
    broadcast instead of arriving all at once, and a live source is unaffected.
    """
    return await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        FFMPEG_PROTOCOLS,
        "-rw_timeout",
        str(FFMPEG_RW_TIMEOUT),
        "-re",
        "-i",
        url,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(stream.SAMPLE_RATE),
        "-f",
        "s16le",
        "pipe:1",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def pump_ffmpeg(session: dict[str, Any], process, send_event) -> str:
    """Move ffmpeg's output into the session until it ends. Returns "stop", or an error on failure."""
    assert process.stdout is not None and process.stderr is not None
    carry = b""
    while True:
        data = await process.stdout.read(FFMPEG_READ_BYTES)
        if not data:
            break
        data = carry + data
        # A read can end mid-sample; the odd byte waits for the next one.
        whole = len(data) - len(data) % stream.SAMPLE_WIDTH
        carry = data[whole:]
        stream.append_samples(session["buffer"], np.frombuffer(data[:whole], dtype="<i2"))
        queue_utterances(session)
        await report_progress(session, send_event)
    returncode = await process.wait()
    if returncode == 0:
        return "stop"
    detail = (await process.stderr.read()).decode("utf-8", "replace").strip()
    logger.warning("[%s] Stream source ended (ffmpeg exit %s): %s", session["request_id"], returncode, detail[-500:])
    # A source that never produced a sample failed; one that broke off after an hour of audio
    # still has phrases in flight, and those are finished rather than thrown away.
    return "Stream source failed" if session["buffer"]["total"] == 0 else "stop"


async def watch_control(receive) -> str:
    """With a URL source the socket carries only control: returns "stop" or "disconnect"."""
    while True:
        message = await receive()
        if message["type"] == "websocket.disconnect":
            return "disconnect"
        try:
            control = json.loads(message.get("text") or "")
        except ValueError:
            continue
        if isinstance(control, dict) and control.get("type") == "stop":
            return "stop"


async def read_url_audio(session: dict[str, Any], url: str, receive, send_event) -> str:
    """Take audio from a URL until it ends, the client says stop, or the client goes away.

    Returns "stop", "disconnect" or an error category. ffmpeg never outlives the session.
    """
    logger.info("[%s] Stream source: %s", session["request_id"], url)
    process = await start_ffmpeg(url)
    pump = asyncio.create_task(pump_ffmpeg(session, process, send_event))
    control = asyncio.create_task(watch_control(receive))
    try:
        await asyncio.wait({pump, control}, return_when=asyncio.FIRST_COMPLETED)
        if pump.done():
            return pump.result()
        return control.result()
    finally:
        for task in (pump, control):
            if not task.done():
                await stop_task(task)
        if process.returncode is None:
            process.kill()
            await process.wait()


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
    segments = await asyncio.to_thread(
        stream.transcribe_utterance, session["buffer"], utterance, session["language"], session["spec"]
    )
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
    if session["url"]:
        reader = asyncio.create_task(read_url_audio(session, session["url"], receive, send_event))
    else:
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
    spec = options["spec"]
    logger.info(
        "[%s] Stream started - source %s, backend %s, model %s, language %s, diarize %s",
        request_id,
        options["source"],
        spec["backend"],
        spec["id"],
        options["language"] or "default",
        "on" if options["diarize"] else "off",
    )
    await send_event(
        {
            "type": "ready",
            "sample_rate": stream.SAMPLE_RATE,
            "backend": spec["backend"],
            "model": spec["id"],
            "language": options["language"],
            "diarize": options["diarize"],
            "source": options["source"],
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

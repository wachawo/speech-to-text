#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP service for speech: POST /api/stt transcribes, POST /api/diarize segments by speaker."""

import io
import logging
import queue
import time
import traceback
import uuid
from typing import Any, cast

import numpy as np
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

# Local imports
from libs import (
    align,
    audio,
    backends,
    catalog,
    config,
    diarize,
    live,
    logs,
    metrics,
    model_pool,
    speech_gate,
    stream,
    url_source,
)
from libs.auth import is_valid_token, read_bearer_token, token_required
from libs.errors import build_error_response, get_request_id, register_error_handlers

logs.setup_logging()
logger = logging.getLogger(__name__)

# Paths whose access log is demoted to DEBUG so healthchecks and scrapes do not flood the log.
QUIET_PATHS = ("/api/health", "/metrics")


def create_app() -> Flask:
    """Build the Flask application: upload limit, proxy headers, CORS and error handlers."""
    flask_app = Flask(__name__)
    flask_app.url_map.strict_slashes = False
    flask_app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH_MB * 1024 * 1024
    flask_app.wsgi_app = ProxyFix(flask_app.wsgi_app, x_for=1, x_host=1)
    CORS(flask_app, resources={r"/api/*": {"origins": config.CORS_ORIGINS}})
    register_error_handlers(flask_app)
    return flask_app


app = create_app()

metrics.LIVE_STATE.update(
    pools=model_pool.get_pool_status,
    sessions=lambda: live.ACTIVE_SESSIONS,
    url_sessions=lambda: url_source.URL_SESSIONS,
)
metrics.register_live_gauges()


@app.before_request
def before_request():
    """Tag the request so every log line and every error body can be correlated."""
    g.request_id = uuid.uuid4().hex[:12]
    g.request_start = time.monotonic()


@app.after_request
def after_request(resp):
    """Log one access line per request with its id, status and duration."""
    elapsed = time.monotonic() - getattr(g, "request_start", time.monotonic())
    metrics.observe_request(request.url_rule.rule if request.url_rule else None, request.method, resp.status_code, elapsed)
    log_request = logger.debug if request.path in QUIET_PATHS else logger.info
    log_request(
        "[%s] %s %s: %s (%.2fs)",
        get_request_id(),
        request.method,
        request.path,
        resp.status,
        elapsed,
    )
    return resp


def read_audio_upload() -> tuple[io.BytesIO, str] | None:
    """Read the audio from the multipart ``file`` field or the raw body; None when absent.

    Must run before any access to request.form: parsing the form consumes the
    request stream that a raw-body upload lives in.
    """
    if "file" in request.files:
        upload = request.files["file"]
        return io.BytesIO(upload.read()), upload.filename or "upload"
    if request.data:
        return io.BytesIO(request.data), "raw_body"
    return None


def read_language_argument() -> str | None:
    """Read the optional per-request language from the query string or the form field.

    Absent or empty means "use the server default", which libs/stt.py resolves.
    """
    language = request.args.get("language") or request.form.get("language")
    if language is None:
        return None
    return language.strip().lower() or None


def convert_upload(bio):
    """Turn an uploaded buffer into a 16 kHz mono WAV, or None when it is not decodable audio.

    Owns the logging of the failure so both routes can treat it as a plain None check. A WARNING
    without a traceback: an upload that is not audio is the client's mistake, answered with 400,
    and a traceback per bad file would bury the server's own errors.
    """
    try:
        return audio.convert_to_wav(bio)
    except Exception as exc:
        logger.warning("[%s] Audio conversion failed: %s: %s", get_request_id(), type(exc).__name__, str(exc)[:300])
        return None


# How long the deep health check waits for a free model before reporting it busy rather than broken.
DEEP_CHECK_TIMEOUT = 5


def check_model(acquire, release, run) -> str:
    """Borrow one pooled instance, run it once: "ok", "busy" when none frees up, or "failed"."""
    try:
        instance = acquire(timeout=DEEP_CHECK_TIMEOUT)
    except queue.Empty:
        return "busy"
    try:
        run(instance)
        return "ok"
    except Exception as exc:
        logger.error(
            "[%s] Deep health check failed: %s: %s\n%s", get_request_id(), type(exc).__name__, exc, traceback.format_exc()
        )
        return "failed"
    finally:
        release(instance)


def run_deep_check() -> dict[str, str]:
    """Push one second of silence through every loaded model, the way a request would."""
    silence = np.zeros(speech_gate.SAMPLE_RATE, dtype=np.int16)
    results = {
        "transcriber": check_model(
            model_pool.acquire_model,
            model_pool.release_model,
            lambda model: backends.transcriber().get_stt_segments(stream.encode_wav(silence), model=model, language=None),
        )
    }
    if config.DIARIZE_ENABLED:
        results["diarizer"] = check_model(
            model_pool.acquire_diarizer,
            model_pool.release_diarizer,
            lambda diarizer: diarize.diarize_wav(stream.encode_wav(silence), diarizer=diarizer),
        )
    return results


@app.route("/api/health", methods=["GET"])
def health():
    """Report service liveness and model pool occupancy; available=0 means all models are busy.

    `?deep=1` also runs one second of silence through every loaded model and reports each as ok,
    busy or failed, answering 503 if any failed. That costs GPU work, so while STT_TOKENS is set it
    needs a token like every other route; the plain check stays open for container healthchecks.
    """
    body = {"status": "ok", **model_pool.get_pool_status()}
    if request.args.get("deep", "").lower() not in config.TRUE_VALUES:
        return jsonify(body), 200
    if config.STT_TOKENS and not is_valid_token(read_bearer_token()):
        logger.warning("[%s] Unauthorized deep health check", get_request_id())
        return build_error_response("Unauthorized", 401)
    body["deep"] = run_deep_check()
    if "failed" in body["deep"].values():
        body["status"] = "failed"
        return jsonify(body), 503
    return jsonify(body), 200


@app.route("/metrics", methods=["GET"])
def prometheus_metrics():
    """Prometheus metrics. Open like /api/health, and like it not proxied by stt_www: scrape :STT_PORT."""
    body, content_type = metrics.render()
    return body, 200, {"Content-Type": content_type}


@app.route("/api/models", methods=["GET"])
@token_required
def list_models():
    """Report the backends this server carries, each with its own language list.

    Behind the token like every other non-health route: a catalogue publishes the server's
    configuration, including which model is loaded and where it is in its lifecycle.

    `status` is one of `loaded` (an instance is waiting in a pool), `installed` (the weights
    are on disk but nothing is loaded yet) or `absent`. A backend that is configured but not
    installed says `absent` and nothing more; the reason is in the log.

    `languages` is per backend and never a union, because the sets genuinely diverge.
    `accepts_language` says whether `?language=` means anything to that backend at all.
    """
    return jsonify(catalog.list_models()), 200


def transcribe_text(wav_bio, model, language) -> str:
    """The plain transcript; with the speech gate on, built only from segments that were spoken.

    Without the gate this is exactly what it always was. With it, the text is the joined segment
    texts - what the transcriber's own text is made of - minus the ones the gate drops, so a
    recording with speech in it reads the same and one without reads empty instead of a
    subtitle credit such as "to be continued...".
    """
    transcriber = backends.transcriber()
    if not config.SPEECH_GATE:
        return transcriber.get_stt_bio(wav_bio, model=model, language=language)
    segments = transcriber.get_stt_segments(wav_bio, model=model, language=language)
    kept = speech_gate.gate_wav(wav_bio, segments, get_request_id())
    return "".join(segment["text"] for segment in kept).strip()


@app.route("/api/stt", methods=["POST"])
@token_required
def transcribe():
    """Transcribe an uploaded audio file.

    Accepts multipart/form-data with field ``file`` (any format pydub supports)
    or a raw binary body with Content-Type audio/*. An optional ``language``
    (query string or form field) overrides the server WHISPER_LANGUAGE default
    for this request; ``auto`` autodetects.

    Returns::
        {"text": "transcribed text", "elapsed": 1.23}
    """
    start_time = time.monotonic()

    upload = read_audio_upload()
    if upload is None:
        return build_error_response("No audio data", 400)
    bio, filename = upload
    size_kb = len(bio.getvalue()) // 1024

    language = read_language_argument()
    if language is not None:
        language = backends.resolve_language(language)
        if language is None:
            return build_error_response("Invalid language", 400)

    wav_bio = convert_upload(bio)
    if wav_bio is None:
        return build_error_response("Invalid audio data", 400)

    try:
        model = model_pool.acquire_model()
    except queue.Empty:
        logger.warning("[%s] Model pool exhausted: %s", get_request_id(), model_pool.get_pool_status())
        return build_error_response("Service Unavailable", 503)

    try:
        text = transcribe_text(wav_bio, model, language)
        elapsed = time.monotonic() - start_time
        logger.info(
            "[%s] STT %s (%dkb) - %d chars (%.2fs)",
            get_request_id(),
            filename,
            size_kb,
            len(text),
            elapsed,
        )
        return jsonify({"text": text, "elapsed": round(elapsed, 3)}), 200
    except Exception as exc:
        logger.error(
            "[%s] STT failed: %s: %s\n%s",
            get_request_id(),
            type(exc).__name__,
            exc,
            traceback.format_exc(),
        )
        return build_error_response("Transcription failed", 500)
    finally:
        model_pool.release_model(model)


@app.route("/api/diarize", methods=["POST"])
@token_required
def diarize_speakers():
    """Report who spoke when in an uploaded audio file. No text: this endpoint returns time ranges.

    Accepts the same body shapes as ``/api/stt``: multipart/form-data with field ``file``, or a
    raw binary body with Content-Type audio/*.

    Turns may overlap, because each speaker channel is scored independently, and the labels are
    positions in this recording ordered by arrival, not identities: the same person gets a
    different number in the next request.

    Returns::
        {"segments": [{"speaker": 0, "start": 0.51, "end": 12.62}], "speakers": 2, "elapsed": 1.23}
    """
    if not config.DIARIZE_ENABLED:
        logger.warning("[%s] Diarization requested while disabled", get_request_id())
        return build_error_response("Diarization disabled", 503)

    start_time = time.monotonic()

    upload = read_audio_upload()
    if upload is None:
        return build_error_response("No audio data", 400)
    bio, filename = upload
    size_kb = len(bio.getvalue()) // 1024

    wav_bio = convert_upload(bio)
    if wav_bio is None:
        return build_error_response("Invalid audio data", 400)

    if not model_pool.diarizer_ready():
        logger.warning("[%s] Diarization enabled but no diarizer loaded", get_request_id())
        return build_error_response("Diarization unavailable", 503)

    try:
        diarizer = model_pool.acquire_diarizer()
    except queue.Empty:
        logger.warning("[%s] Diarizer pool exhausted: %s", get_request_id(), model_pool.get_pool_status())
        return build_error_response("Service Unavailable", 503)

    try:
        segments = diarize.diarize_wav(wav_bio, diarizer=diarizer)
        elapsed = time.monotonic() - start_time
        speakers = len({segment["speaker"] for segment in segments})
        logger.info(
            "[%s] Diarize %s (%dkb) - %d turns, %d speakers (%.2fs)",
            get_request_id(),
            filename,
            size_kb,
            len(segments),
            speakers,
            elapsed,
        )
        return jsonify({"segments": segments, "speakers": speakers, "elapsed": round(elapsed, 3)}), 200
    except Exception as exc:
        logger.error(
            "[%s] Diarization failed: %s: %s\n%s",
            get_request_id(),
            type(exc).__name__,
            exc,
            traceback.format_exc(),
        )
        return build_error_response("Diarization failed", 500)
    finally:
        model_pool.release_diarizer(diarizer)


def run_diarization(wav_bio):
    """Diarize the buffer with a pooled instance, releasing it before anything else runs."""
    diarizer = model_pool.acquire_diarizer()
    try:
        wav_bio.seek(0)
        return diarize.diarize_wav(wav_bio, diarizer=diarizer)
    finally:
        model_pool.release_diarizer(diarizer)


def run_transcription(wav_bio, language):
    """Transcribe the buffer with a pooled model, releasing it before anything else runs."""
    model = model_pool.acquire_model()
    try:
        wav_bio.seek(0)
        return backends.transcriber().get_stt_segments(wav_bio, model=model, language=language)
    finally:
        model_pool.release_model(model)


@app.route("/api/transcript", methods=["POST"])
@token_required
def transcribe_by_speaker():
    """Transcribe an uploaded file and attribute each part of it to a speaker.

    Accepts the same body shapes as /api/stt. Diarization runs first and its instance is
    released before a transcription model is borrowed, so no request ever holds one of each.

    `turns` is the diarizer's raw output and `segments` is the join, kept as two fields rather
    than one fused list so a caller who distrusts the attribution can still see what the
    diarizer said. `text` is the unattributed transcript.

    `overlap` marks a segment during which another speaker was also talking. NVIDIA is explicit
    that pairing a conventional single-speaker model with diarization is not equivalent to a
    model built for overlapping speech: an extracted range still contains every voice that
    overlaps it, so those segments may merge or select the wrong speaker's words.

    Returns::
        {"segments": [...], "turns": [...], "speakers": 2, "text": "...", "elapsed": 1.23}
    """
    if not config.DIARIZE_ENABLED:
        logger.warning("[%s] Speaker transcript requested while diarization is disabled", get_request_id())
        return build_error_response("Diarization disabled", 503)
    if not model_pool.diarizer_ready():
        logger.warning("[%s] Speaker transcript requested but no diarizer loaded", get_request_id())
        return build_error_response("Diarization unavailable", 503)

    start_time = time.monotonic()

    upload = read_audio_upload()
    if upload is None:
        return build_error_response("No audio data", 400)
    bio, filename = upload
    size_kb = len(bio.getvalue()) // 1024

    language = read_language_argument()
    if language is not None:
        language = backends.resolve_language(language)
        if language is None:
            return build_error_response("Invalid language", 400)

    wav_bio = convert_upload(bio)
    if wav_bio is None:
        return build_error_response("Invalid audio data", 400)

    try:
        turns = run_diarization(wav_bio)
    except queue.Empty:
        logger.warning("[%s] Diarizer pool exhausted: %s", get_request_id(), model_pool.get_pool_status())
        return build_error_response("Service Unavailable", 503)
    except Exception as exc:
        logger.error("[%s] Diarization failed: %s: %s\n%s", get_request_id(), type(exc).__name__, exc, traceback.format_exc())
        return build_error_response("Diarization failed", 500)

    try:
        segments = run_transcription(wav_bio, language)
    except queue.Empty:
        logger.warning("[%s] Model pool exhausted: %s", get_request_id(), model_pool.get_pool_status())
        return build_error_response("Service Unavailable", 503)
    except Exception as exc:
        logger.error("[%s] STT failed: %s: %s\n%s", get_request_id(), type(exc).__name__, exc, traceback.format_exc())
        return build_error_response("Transcription failed", 500)

    if config.SPEECH_GATE:
        segments = speech_gate.gate_wav(wav_bio, segments, get_request_id())
    attributed = align.attribute_segments(segments, turns)
    elapsed = time.monotonic() - start_time
    speakers = align.count_speakers(attributed)
    logger.info(
        "[%s] Transcript %s (%dkb) - %d segments, %d speakers (%.2fs)",
        get_request_id(),
        filename,
        size_kb,
        len(attributed),
        speakers,
        elapsed,
    )
    return (
        jsonify(
            {
                "segments": attributed,
                "turns": turns,
                "speakers": speakers,
                # Joined with no separator, not with a space: whisper's segment texts already carry
                # their leading space, so this reproduces exactly what /api/stt would return.
                "text": "".join(segment["text"] for segment in segments).strip(),
                "elapsed": round(elapsed, 3),
            }
        ),
        200,
    )


def log_auth_mode() -> None:
    """State at startup whether the endpoint is protected, so it is never a surprise."""
    if config.STT_TOKENS:
        logger.info("Auth: %d static token(s) loaded", len(config.STT_TOKENS))
    else:
        logger.info("Auth: disabled (STT_TOKENS empty)")


def build_asgi_app(wsgi_app):
    """One ASGI app for uvicorn: the live stream socket, and everything else into Flask.

    Dispatched on the path rather than mounted: Starlette-style mounting strips the prefix, and
    Flask would then see `/health` for `/api/health` and answer its own 404. Here every public URL
    stays exactly what it was.
    """
    from uvicorn.middleware.wsgi import WSGIMiddleware

    http_app = WSGIMiddleware(wsgi_app)

    async def asgi_app(scope, receive, send):
        """Route one ASGI connection by its type and path."""
        if scope["type"] == "websocket":
            if scope["path"] == live.STREAM_PATH:
                await live.handle_stream(scope, receive, send)
            else:
                # Closing before accepting is how ASGI refuses a handshake: the client sees a 403.
                await send({"type": "websocket.close", "code": live.CLOSE_POLICY})
            return
        await http_app(scope, receive, send)

    return asgi_app


# The ASGI entry point for servers that take an application object rather than run main():
# `gunicorn --config gu.py stt_server:asgi_app` with GUNICORN_WORKER_CLASS=uvicorn_worker.UvicornWorker.
asgi_app = build_asgi_app(cast(Any, app.wsgi_app))


def run_server() -> None:
    """Serve the app: the Flask dev server in debug mode, uvicorn otherwise.

    The live stream exists only under uvicorn: neither the Flask dev server nor Gunicorn's sync
    workers speak websocket.
    """
    if config.STT_DEBUG:
        app.run(host=config.STT_HOST, port=config.STT_PORT, debug=True)
        return

    import uvicorn

    uvicorn.run(
        asgi_app,
        host=config.STT_HOST,
        port=config.STT_PORT,
        log_level=config.LOG_LEVEL.lower(),
        log_config=logs.build_uvicorn_log_config(),
        access_log=config.LOG_ACCESS,
    )


def main():
    """Entry point: fill the model pool, then serve."""
    model_pool.init_model_pool()
    model_pool.init_diarizer_pool()
    if config.SPEECH_GATE:
        speech_gate.find_speech(np.zeros(speech_gate.SAMPLE_RATE, dtype=np.float32))
    log_auth_mode()
    run_server()


if __name__ == "__main__":
    main()

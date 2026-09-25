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

from flask import Flask, g, jsonify, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

# Local imports
from libs import align, audio, backends, catalog, config, diarize, live, logs, model_pool, registry
from libs.auth import is_request_authorized, token_required
from libs.errors import build_error_response, get_request_id, register_error_handlers

logs.setup_logging()
logger = logging.getLogger(__name__)

# Path whose access log is demoted to DEBUG so healthchecks do not flood the log.
QUIET_PATH = "/api/health"


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


@app.before_request
def before_request():
    """Tag the request so every log line and every error body can be correlated."""
    g.request_id = uuid.uuid4().hex[:12]
    g.request_start = time.monotonic()


@app.after_request
def after_request(resp):
    """Log one access line per request with its id, status and duration."""
    elapsed = time.monotonic() - getattr(g, "request_start", time.monotonic())
    log_request = logger.debug if request.path == QUIET_PATH else logger.info
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


def read_model_argument() -> str | None:
    """Read the optional per-request model from the query string or the form field; empty means default.

    Like read_language_argument, it must run after read_audio_upload: parsing the form
    consumes the stream a raw-body upload lives in.
    """
    model = request.args.get("model") or request.form.get("model")
    if model is None:
        return None
    return model.strip() or None


def resolve_request_options() -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Resolve the request's model and then its language against that model.

    Returns (spec, language, None), or (None, None, error category) for a 400. Both checks run
    before the audio is decoded and before any instance is borrowed, so a bad request costs
    nothing. `explicit` is whether the client named a model: one that did gets the language
    checked against that model's own list, one that did not keeps the lenient behaviour it
    always had.
    """
    requested_model = read_model_argument()
    spec, error = registry.resolve_request_model(requested_model)
    if spec is None:
        return None, None, error
    language, error = backends.resolve_language(read_language_argument(), spec, explicit=requested_model is not None)
    if error is not None:
        return None, None, error
    return spec, language, None


def convert_upload(bio):
    """Turn an uploaded buffer into a 16 kHz mono WAV, or None when it is not decodable audio.

    Owns the logging of the failure so both routes can treat it as a plain None check.
    """
    try:
        return audio.convert_to_wav(bio)
    except Exception as exc:
        logger.error(
            "[%s] Audio conversion failed: %s: %s\n%s",
            get_request_id(),
            type(exc).__name__,
            exc,
            traceback.format_exc(),
        )
        return None


@app.route("/api/health", methods=["GET"])
def health():
    """Report service liveness and model pool occupancy.

    Open, so healthchecks need no token. The top-level `pool_size` and `available` describe the
    default model (available=0 means every instance of it is busy). `default_model` and `models`
    (every loaded model's pool by id) name the deployment's configuration, so like /api/models
    they are only included for a caller that passes the token check, or when auth is off.
    """
    return jsonify({"status": "ok", **model_pool.get_pool_status(detailed=is_request_authorized())}), 200


@app.route("/api/models", methods=["GET"])
@token_required
def list_models():
    """Report the models this server carries, each with its own language list.

    Behind the token like every other non-health route: a catalogue publishes the server's
    configuration, including which model is loaded and where it is in its lifecycle.

    One row per loaded model (a request may name its `id` as `model`), one row for a
    transcriber with nothing loaded, and the diarizer when it is on. `status` is one of
    `loaded` (instances of it exist, idle or busy), `installed` (the weights are on disk but
    nothing is loaded yet) or `absent`. A backend that is configured but not installed says
    `absent` and nothing more; the reason is in the log.

    `selectable` says whether a request may name the row as its `model`, `pool_size` and
    `available` are that model's pool, and exactly one row has `default` true: its id is the
    top-level `default_model`, and its backend the top-level `default`.

    `languages` is per row and never a union, because the sets genuinely diverge.
    `accepts_language` says whether `?language=` means anything to that backend at all.
    """
    return jsonify(catalog.list_models()), 200


@app.route("/api/stt", methods=["POST"])
@token_required
def transcribe():
    """Transcribe an uploaded audio file.

    Accepts multipart/form-data with field ``file`` (any format pydub supports)
    or a raw binary body with Content-Type audio/*. An optional ``model`` (query
    string or form field: an id, an alias, ``backend:model`` or a bare backend
    name) picks one of the models loaded at startup; without it the default model
    serves. An optional ``language`` overrides the server WHISPER_LANGUAGE default
    for this request; ``auto`` autodetects.

    ``model`` is the id of the model that transcribed. ``language`` is the code
    Whisper detected or used (always ``en`` for an English-only checkpoint), or
    null for a backend that does not report it.

    Returns::
        {"text": "transcribed text", "elapsed": 1.23, "model": "turbo", "language": "en"}
    """
    start_time = time.monotonic()

    upload = read_audio_upload()
    if upload is None:
        return build_error_response("No audio data", 400)
    bio, filename = upload
    size_kb = len(bio.getvalue()) // 1024

    spec, language, error = resolve_request_options()
    if spec is None:
        return build_error_response(error or "Invalid model", 400)

    wav_bio = convert_upload(bio)
    if wav_bio is None:
        return build_error_response("Invalid audio data", 400)

    try:
        model = model_pool.acquire_model(model_id=spec["id"])
    except queue.Empty:
        logger.warning("[%s] Model pool exhausted: %s", get_request_id(), model_pool.get_pool_status())
        return build_error_response("Service Unavailable", 503)

    try:
        result = backends.transcriber_for_backend(spec["backend"]).get_stt_result(wav_bio, model=model, language=language)
        text = result["text"]
        elapsed = time.monotonic() - start_time
        logger.info(
            "[%s] STT %s (%dkb) model=%s language=%s - %d chars (%.2fs)",
            get_request_id(),
            filename,
            size_kb,
            spec["id"],
            result["language"],
            len(text),
            elapsed,
        )
        return jsonify({"text": text, "elapsed": round(elapsed, 3), "model": spec["id"], "language": result["language"]}), 200
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
        model_pool.release_model(model, model_id=spec["id"])


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


def run_transcription(wav_bio, language, spec):
    """Transcribe the buffer with an instance of the chosen model, releasing it before anything else runs."""
    model = model_pool.acquire_model(model_id=spec["id"])
    try:
        wav_bio.seek(0)
        return backends.transcriber_for_backend(spec["backend"]).get_stt_segments(wav_bio, model=model, language=language)
    finally:
        model_pool.release_model(model, model_id=spec["id"])


@app.route("/api/transcript", methods=["POST"])
@token_required
def transcribe_by_speaker():
    """Transcribe an uploaded file and attribute each part of it to a speaker.

    Accepts the same body shapes and the same ``model`` and ``language`` options as /api/stt.
    Diarization runs first and its instance is released before a transcription model is
    borrowed, so no request ever holds one of each. ``model`` in the response is the id of the
    model that transcribed.

    `turns` is the diarizer's raw output and `segments` is the join, kept as two fields rather
    than one fused list so a caller who distrusts the attribution can still see what the
    diarizer said. `text` is the unattributed transcript.

    `overlap` marks a segment during which another speaker was also talking. NVIDIA is explicit
    that pairing a conventional single-speaker model with diarization is not equivalent to a
    model built for overlapping speech: an extracted range still contains every voice that
    overlaps it, so those segments may merge or select the wrong speaker's words.

    Returns::
        {"segments": [...], "turns": [...], "speakers": 2, "text": "...", "elapsed": 1.23, "model": "turbo"}
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

    spec, language, error = resolve_request_options()
    if spec is None:
        return build_error_response(error or "Invalid model", 400)

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
        segments = run_transcription(wav_bio, language, spec)
    except queue.Empty:
        logger.warning("[%s] Model pool exhausted: %s", get_request_id(), model_pool.get_pool_status())
        return build_error_response("Service Unavailable", 503)
    except Exception as exc:
        logger.error("[%s] STT failed: %s: %s\n%s", get_request_id(), type(exc).__name__, exc, traceback.format_exc())
        return build_error_response("Transcription failed", 500)

    attributed = align.attribute_segments(segments, turns)
    elapsed = time.monotonic() - start_time
    speakers = align.count_speakers(attributed)
    logger.info(
        "[%s] Transcript %s (%dkb) model=%s - %d segments, %d speakers (%.2fs)",
        get_request_id(),
        filename,
        size_kb,
        spec["id"],
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
                "model": spec["id"],
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


def run_server() -> None:
    """Serve the app: the Flask dev server in debug mode, uvicorn otherwise.

    The live stream exists only under uvicorn: neither the Flask dev server nor Gunicorn's sync
    workers speak websocket.
    """
    if config.STT_DEBUG:
        app.run(host=config.STT_HOST, port=config.STT_PORT, debug=True)
        return

    import uvicorn

    wsgi_app = cast(Any, app.wsgi_app)
    uvicorn.run(
        build_asgi_app(wsgi_app),
        host=config.STT_HOST,
        port=config.STT_PORT,
        log_level=config.LOG_LEVEL.lower(),
        log_config=logs.build_uvicorn_log_config(),
        access_log=config.LOG_ACCESS,
    )


def main():
    """Entry point: fill every model's pool, then serve."""
    model_pool.init_model_pool()
    model_pool.init_diarizer_pool()
    log_auth_mode()
    run_server()


if __name__ == "__main__":
    main()

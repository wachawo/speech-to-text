#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP service exposing Whisper transcription: POST /api/stt and GET /api/health."""

import io
import logging
import queue
import re
import time
import traceback
import uuid
from typing import Any, cast

from flask import Flask, g, jsonify, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

# Local imports
from libs import audio, config, logs, model_pool, stt
from libs.auth import token_required
from libs.errors import build_error_response, get_request_id, register_error_handlers

logs.setup_logging()
logger = logging.getLogger(__name__)

# Accepted per-request language: an ISO code (2-3 letters) or "auto" (autodetect).
LANGUAGE_RE = re.compile(r"^[a-z]{2,3}$")

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


def is_valid_language(language: str) -> bool:
    """Accept "auto" and ISO-like codes only, so junk never reaches Whisper as a 500."""
    return language == "auto" or bool(LANGUAGE_RE.match(language))


@app.route("/api/health", methods=["GET"])
def health():
    """Report service liveness and model pool occupancy; available=0 means all models are busy."""
    return jsonify({"status": "ok", **model_pool.get_pool_status()}), 200


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
    if language is not None and not is_valid_language(language):
        return build_error_response("Invalid language", 400)

    try:
        wav_bio = audio.convert_to_wav(bio)
    except Exception as exc:
        logger.error(
            "[%s] Audio conversion failed: %s: %s\n%s",
            get_request_id(),
            type(exc).__name__,
            exc,
            traceback.format_exc(),
        )
        return build_error_response("Invalid audio data", 400)

    try:
        model = model_pool.acquire_model()
    except queue.Empty:
        logger.warning(
            "[%s] Model pool exhausted: %s", get_request_id(), model_pool.get_pool_status()
        )
        return build_error_response("Service Unavailable", 503)

    try:
        text = stt.get_stt_bio(wav_bio, model=model, language=language)
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


def log_auth_mode() -> None:
    """State at startup whether the endpoint is protected, so it is never a surprise."""
    if config.STT_TOKENS:
        logger.info("Auth: %d static token(s) loaded", len(config.STT_TOKENS))
    else:
        logger.info("Auth: disabled (STT_TOKENS empty)")


def run_server() -> None:
    """Serve the app: the Flask dev server in debug mode, uvicorn otherwise."""
    if config.STT_DEBUG:
        app.run(host=config.STT_HOST, port=config.STT_PORT, debug=True)
        return

    import uvicorn
    from uvicorn.middleware.wsgi import WSGIMiddleware

    wsgi_app = cast(Any, app.wsgi_app)
    uvicorn.run(
        WSGIMiddleware(wsgi_app),
        host=config.STT_HOST,
        port=config.STT_PORT,
        log_level=config.LOG_LEVEL.lower(),
        log_config=logs.build_uvicorn_log_config(),
        access_log=config.LOG_ACCESS,
    )


def main():
    """Entry point: fill the model pool, then serve."""
    model_pool.init_model_pool()
    log_auth_mode()
    run_server()


if __name__ == "__main__":
    main()

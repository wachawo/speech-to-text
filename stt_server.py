#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STT Flask server — exposes Whisper transcription via HTTP.

POST /api/stt  — upload audio file, get transcription text back.
GET  /api/health — healthcheck (model pool status).

Initializes a pool of N Whisper model instances at startup
so each request grabs a pre-loaded model from the queue.
"""

import hmac
import io
import logging
import os
import queue
import time
import traceback
import uuid
from functools import wraps
from typing import Any, cast

import werkzeug.exceptions
from dotenv import find_dotenv, load_dotenv
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv(find_dotenv())

# Local import — stt.py must NOT be modified
import libs.stt as stt  # noqa: E402  (must follow load_dotenv)

TRUE = ("1", "true", "yes", "on", "enabled")
# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_ACCESS = os.getenv("LOG_ACCESS", "false").lower() in TRUE
LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s.%(funcName)s) %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

LOGGING = {
    "handlers": [logging.StreamHandler()],
    "format": LOG_FORMAT,
    "level": getattr(logging, LOG_LEVEL, logging.INFO),
    "datefmt": LOG_DATE_FORMAT,
}
logging.basicConfig(**LOGGING)
logger = logging.getLogger(__name__)

LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": LOG_FORMAT,
            "datefmt": LOG_DATE_FORMAT,
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": LOG_LEVEL, "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": LOG_LEVEL, "propagate": False},
        "uvicorn.access": {"handlers": [], "propagate": False},
    },
}

# Config
TRUE_VALUES = ("1", "true", "yes", "on", "enabled")
FLASK_HOST = os.getenv("STT_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("STT_PORT", "5099"))
FLASK_DEBUG = os.getenv("STT_DEBUG", "False").lower() in TRUE_VALUES
MODEL_POOL_SIZE = int(os.getenv("STT_POOL_SIZE", "8"))
MODEL_POOL: queue.Queue = queue.Queue()

# Static-token auth — empty set means "auth disabled, allow all".
STT_TOKENS: set[str] = {t.strip() for t in os.getenv("STT_TOKENS", "").split(",") if t.strip()}


def init_model_pool(size: int = MODEL_POOL_SIZE):
    """Pre-load `size` Whisper model instances into the pool."""
    logger.info("Initializing %d Whisper model instances...", size)
    for i in range(size):
        t0 = time.monotonic()
        model = stt.get_model()
        elapsed = time.monotonic() - t0
        MODEL_POOL.put(model)
        logger.info("  Model #%d ready (%.2fs)", i + 1, elapsed)
    logger.info("Model pool ready: %d instances", MODEL_POOL.qsize())


# Flask app
app = Flask(__name__)
app.url_map.strict_slashes = False
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1)
CORS(app, resources={r"/api/*": {"origins": "*"}})


# Request context helpers


def get_req_id() -> str:
    return getattr(g, "request_id", "-")


def token_required(view):
    """Reject requests without a valid Bearer token when STT_TOKENS is non-empty."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not STT_TOKENS:
            return view(*args, **kwargs)
        header = request.headers.get("Authorization", "")
        token = header[7:].strip() if header.startswith("Bearer ") else ""
        if not token or not any(hmac.compare_digest(token, t) for t in STT_TOKENS):
            logger.warning("[%s] Unauthorized", get_req_id())
            return jsonify({"error": "Unauthorized", "request_id": get_req_id()}), 401
        return view(*args, **kwargs)

    return wrapper


@app.before_request
def before_request():
    g.request_id = uuid.uuid4().hex[:12]
    g.request_start = time.monotonic()


# Error handlers


@app.errorhandler(400)
def bad_request(error):
    logger.warning("[%s] Bad Request: %s", get_req_id(), error)
    return jsonify({"error": "Bad Request", "request_id": get_req_id()}), 400


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not Found", "request_id": get_req_id()}), 404


@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"error": "Method Not Allowed", "request_id": get_req_id()}), 405


@app.errorhandler(500)
def internal_error(error):
    logger.error(
        "[%s] Internal Server Error: %s: %s\n%s",
        get_req_id(),
        type(error).__name__,
        error,
        traceback.format_exc(),
    )
    return jsonify({"error": "Internal Server Error", "request_id": get_req_id()}), 500


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, werkzeug.exceptions.NotFound):
        return jsonify({"error": "Not Found", "request_id": get_req_id()}), 404

    logger.error(
        "[%s] Unhandled exception: %s: %s\n%s",
        get_req_id(),
        type(e).__name__,
        e,
        traceback.format_exc(),
    )
    return jsonify({"error": "Internal Server Error", "request_id": get_req_id()}), 500


@app.after_request
def after_request(resp):
    elapsed_ms = int((time.monotonic() - getattr(g, "request_start", time.monotonic())) * 1000)
    log_fn = logger.debug if request.path == "/api/health" else logger.info
    log_fn(
        "[%s] %s %s: %s %s (%dms)",
        get_req_id(),
        request.method,
        request.path,
        resp.status_code,
        resp.status,
        elapsed_ms,
    )
    return resp


# Routes


@app.route("/api/health", methods=["GET"])
def health():
    """Healthcheck — report pool size and available models."""
    health_status = {
        "status": "ok",
        "pool_size": MODEL_POOL_SIZE,
        "available": MODEL_POOL.qsize(),
    }
    return jsonify(health_status), 200


@app.route("/api/stt", methods=["POST"])
@token_required
def transcribe():
    """
    Transcribe an uploaded audio file.

    Accepts multipart/form-data with field ``file`` (any format pydub supports)
    or raw binary body with Content-Type audio/*.

    Returns::
        {"text": "transcribed text", "elapsed": 1.23}
    """
    t0 = time.monotonic()

    # Read audio into BytesIO
    if "file" in request.files:
        f = request.files["file"]
        bio = io.BytesIO(f.read())
        filename = f.filename or "upload"
    elif request.data:
        bio = io.BytesIO(request.data)
        filename = "raw_body"
    else:
        return jsonify({"error": "No audio data", "request_id": get_req_id()}), 400

    bio.seek(0)
    size_kb = len(bio.getvalue()) // 1024

    # Convert to WAV via pydub (handles mp3, wav, ogg, etc.)
    # Export as 16kHz mono 16-bit PCM — matches Whisper's expected format,
    # so stt.py skips the torchaudio resampling step entirely.
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(bio)
        channels = audio.split_to_mono()
        if len(channels) > 1:
            audio = AudioSegment.from_mono_audiosegments(*channels)
        wav_bio = io.BytesIO()
        audio.export(wav_bio, format="wav")
        wav_bio.seek(0)
    except Exception as e:
        logger.error(
            "[%s] Audio conversion failed: %s: %s\n%s",
            get_req_id(),
            type(e).__name__,
            e,
            traceback.format_exc(),
        )
        return jsonify({"error": "Invalid audio data", "request_id": get_req_id()}), 400

    # Acquire model from pool
    try:
        model = MODEL_POOL.get(timeout=120)
    except queue.Empty:
        logger.warning(
            "[%s] Model pool exhausted (size=%d, available=%d)",
            get_req_id(),
            MODEL_POOL_SIZE,
            MODEL_POOL.qsize(),
        )
        return jsonify({"error": "Service Unavailable", "request_id": get_req_id()}), 503

    # Transcribe
    try:
        text = stt.get_stt_bio(wav_bio, model=model)
        elapsed = time.monotonic() - t0
        logger.info(
            "[%s] STT %s (%dkb) → %d chars (%.2fs)",
            get_req_id(),
            filename,
            size_kb,
            len(text),
            elapsed,
        )
        return jsonify({"text": text, "elapsed": round(elapsed, 3)}), 200
    except Exception as e:
        logger.error(
            "[%s] STT failed: %s: %s\n%s",
            get_req_id(),
            type(e).__name__,
            e,
            traceback.format_exc(),
        )
        return jsonify({"error": "Transcription failed", "request_id": get_req_id()}), 500
    finally:
        MODEL_POOL.put(model)


# Main


def main():
    init_model_pool(MODEL_POOL_SIZE)
    if STT_TOKENS:
        logger.info("Auth: %d static token(s) loaded", len(STT_TOKENS))
    else:
        logger.info("Auth: disabled (STT_TOKENS empty)")

    if FLASK_DEBUG:
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
    else:
        import uvicorn
        from uvicorn.middleware.wsgi import WSGIMiddleware

        wsgi_app = cast(Any, app.wsgi_app)
        uvicorn.run(
            WSGIMiddleware(wsgi_app),
            host=FLASK_HOST,
            port=FLASK_PORT,
            log_level=LOG_LEVEL.lower(),
            log_config=LOG_CONFIG,
            access_log=LOG_ACCESS,
        )


if __name__ == "__main__":
    main()

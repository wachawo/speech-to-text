#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STT Flask server — exposes Whisper transcription via HTTP.

POST /api/stt  — upload audio file, get transcription text back.
GET  /api/health — healthcheck (model pool status).

Initializes a pool of N Whisper model instances at startup
so each request grabs a pre-loaded model from the queue.
"""

import io
import logging
import os
import queue
import time
import traceback
from typing import Any, cast

import werkzeug.exceptions
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# Local import — stt.py must NOT be modified
import libs.stt as stt

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
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


# Error handlers


@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad Request", "message": str(error)}), 400


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not Found"}), 404


@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"error": "Method Not Allowed"}), 405


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal Server Error", "message": str(error)}), 500


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, werkzeug.exceptions.NotFound):
        return jsonify({"error": "NotFound"}), 404

    logger.error(f"{type(e).__name__} {str(e)} {traceback.format_exc()}")
    return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.after_request
def after_request(resp):
    log_fn = logger.debug if request.path == "/api/health" else logger.info
    log_fn("%s %s: %s %s", request.method, request.path, resp.status_code, resp.status)
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
        return jsonify({"error": "No audio file provided"}), 400

    bio.seek(0)
    size_kb = len(bio.getvalue()) // 1024

    # Convert to WAV via pydub (handles mp3, wav, ogg, etc.)
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
            f"Audio conversion failed: {type(e).__name__} {str(e)}\n{traceback.format_exc()}"
        )
        return jsonify({"error": f"Audio conversion failed: {e}"}), 400

    # Acquire model from pool
    try:
        model = MODEL_POOL.get(timeout=120)
    except queue.Empty:
        return jsonify({"error": "All models busy, try again later"}), 503

    # Transcribe
    try:
        text = stt.get_stt_bio(wav_bio, model=model)
        elapsed = time.monotonic() - t0
        logger.info(
            "STT %s (%dkb) → %d chars (%.2fs)",
            filename,
            size_kb,
            len(text),
            elapsed,
        )
        return jsonify({"text": text, "elapsed": round(elapsed, 3)}), 200
    except Exception as e:
        logger.error(
            f"STT failed: {type(e).__name__} {str(e)}\n{traceback.format_exc()}"
        )
        return jsonify({"error": f"STT failed: {e}"}), 500
    finally:
        MODEL_POOL.put(model)


# Main


def main():
    init_model_pool(MODEL_POOL_SIZE)

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
            access_log=False,
        )


if __name__ == "__main__":
    main()

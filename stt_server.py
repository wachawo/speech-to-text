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
LOGGING = {
    "handlers": [logging.StreamHandler()],
    "format": "%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s.%(funcName)s) %(message)s",
    "level": logging.INFO,
    "datefmt": "%Y-%m-%d %H:%M:%S",
}
logging.basicConfig(**LOGGING)
logger = logging.getLogger(__name__)

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
def handle_exception(exc):
    if isinstance(exc, werkzeug.exceptions.NotFound):
        return jsonify({"error": "NotFound"}), 404
    logger.error("%s: %s\n%s", type(exc).__name__, exc, traceback.format_exc())
    return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


# Routes


@app.route("/api/health", methods=["GET"])
def health():
    """Healthcheck — report pool size and available models."""
    return (
        jsonify(
            {
                "status": "ok",
                "pool_size": MODEL_POOL_SIZE,
                "available": MODEL_POOL.qsize(),
            }
        ),
        200,
    )


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
        logger.error("Audio conversion failed: %s", e)
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
        logger.error("STT failed: %s\n%s", e, traceback.format_exc())
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
            WSGIMiddleware(wsgi_app), host=FLASK_HOST, port=FLASK_PORT, log_level="info"
        )


if __name__ == "__main__":
    main()

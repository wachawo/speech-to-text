#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP service for speech: POST /api/stt transcribes, POST /api/diarize segments by speaker."""

import io
import logging
import queue
import shutil
import time
import traceback
import uuid
from functools import partial
from typing import Any, cast

import numpy as np
import uvicorn
from flask import Flask, g, has_request_context, jsonify, request
from flask_cors import CORS
from uvicorn.middleware.wsgi import WSGIMiddleware
from werkzeug.formparser import FormDataParser
from werkzeug.middleware.proxy_fix import ProxyFix

# Local imports
from libs import (
    align,
    audio,
    backends,
    catalog,
    config,
    diarize,
    jobs,
    live,
    logs,
    metrics,
    model_pool,
    openai_api,
    registry,
    speech_gate,
    stream,
    url_source,
)
from libs.auth import is_request_authorized, token_required
from libs.errors import build_error_response, get_request_id, is_openai_path, register_error_handlers

logs.setup_logging()
logger = logging.getLogger(__name__)

JOBS_PATH = "/api/jobs"

# Paths whose access log is demoted to DEBUG so healthchecks and scrapes do not flood the log.
QUIET_PATHS = ("/api/health", "/metrics")


def keep_upload_in_memory(**unused_part_details) -> io.BytesIO:
    """Werkzeug stream factory that holds a multipart file part in memory, whatever its size.

    Werkzeug passes the part's sizes, filename and content type by name; none of them is needed.
    """
    return io.BytesIO()


class MemoryFormDataParser(FormDataParser):
    """A form parser that never spools an uploaded file to disk, as werkzeug's default does past 500 KB."""

    def __init__(self, *args, **kwargs):
        """Swap in the in-memory stream factory; every other limit stays the request's own."""
        kwargs["stream_factory"] = keep_upload_in_memory
        super().__init__(*args, **kwargs)


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


def is_scrape_detailed() -> bool:
    """Whether the scrape being answered may see series labelled with model ids.

    Those ids are what /api/health and /api/models keep behind the token, so a scrape gets them on
    the same terms as health's model list. prometheus_client also reads the gauges once when they
    are registered, outside any request; that read gets the counters alone.
    """
    return has_request_context() and is_request_authorized()


def read_scrape_pools() -> dict[str, Any]:
    """The pool status behind /metrics, with every model's pool only for a scrape health would show it to.

    The per-model gauges are built from the `models` map and labelled with each model's id; see
    is_scrape_detailed for who gets them.
    """
    return model_pool.get_pool_status(detailed=is_scrape_detailed())


metrics.LIVE_STATE.update(
    detailed=is_scrape_detailed,
    pools=read_scrape_pools,
    sessions=lambda: live.ACTIVE_SESSIONS,
    url_sessions=lambda: url_source.URL_SESSIONS,
)
metrics.register_live_gauges()


@app.before_request
def before_request():
    """Tag the request so every log line and every error body can be correlated."""
    g.request_id = uuid.uuid4().hex[:12]
    g.request_start = time.monotonic()
    # A job exists for recordings too long for a synchronous request, so it takes far larger files.
    if request.path == JOBS_PATH and request.method == "POST":
        request.max_content_length = config.JOB_MAX_CONTENT_LENGTH_MB * 1024 * 1024
    else:
        # A synchronous upload is not spooled to disk; MAX_CONTENT_LENGTH_MB bounds the memory it takes.
        request.form_data_parser_class = MemoryFormDataParser


@app.after_request
def after_request(resp):
    """Log one access line per request with its id, status and duration.

    An OpenAI-compatible response also carries the request id as X-Request-Id, errors included:
    its body has no top-level field for it.
    """
    if is_openai_path(request.path):
        resp.headers["X-Request-Id"] = get_request_id()
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


def read_model_argument() -> str | None:
    """Read the optional per-request model from the query string or the form field; empty means default.

    Like read_language_argument, it must run after read_audio_upload: parsing the form
    consumes the stream a raw-body upload lives in.
    """
    model = request.args.get("model") or request.form.get("model")
    if model is None:
        return None
    return model.strip() or None


def resolve_request_options() -> tuple[dict[str, Any] | None, str | None, Any]:
    """Resolve the request's model and then its language against that model.

    Returns (spec, language, None) - the language None when the request names none - or
    (None, None, the 400 to answer). Both checks run before the audio is decoded and before any
    instance is borrowed, so a bad request costs nothing. A client that named a model gets the
    language checked against that model's own list; one that did not keeps the lenient
    behaviour it always had.
    """
    requested_model = read_model_argument()
    spec, error = registry.resolve_request_model(requested_model)
    if spec is None:
        return None, None, build_error_response(error or registry.INVALID_MODEL, 400)
    language, error = backends.resolve_language(read_language_argument(), spec, explicit=requested_model is not None)
    if error is not None:
        return None, None, build_error_response(error, 400)
    return spec, language, None


def diarization_refusal():
    """The 503 for a request that needs the diarizer when there is none, or None when there is one."""
    if not config.DIARIZE_ENABLED:
        logger.warning("[%s] %s needs diarization, which is disabled", get_request_id(), request.path)
        return build_error_response("Diarization disabled", 503)
    if not model_pool.diarizer_ready():
        logger.warning("[%s] %s needs diarization, but no diarizer is loaded", get_request_id(), request.path)
        return build_error_response("Diarization unavailable", 503)
    return None


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

# Deep check outcomes from best to worst; `transcriber` reports the worst of the loaded models.
CHECK_SEVERITY = ("ok", "busy", "failed")


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


def check_transcriber(spec: dict[str, Any], silence: np.ndarray) -> str:
    """Run one loaded model once, with an instance borrowed from and returned to its own pool."""
    transcriber = backends.transcriber_for_backend(spec["backend"])
    return check_model(
        partial(model_pool.acquire_model, model_id=spec["id"], observe=False),
        partial(model_pool.release_model, model_id=spec["id"]),
        lambda model: transcriber.get_stt_segments(stream.encode_wav(silence), model=model, language=None),
    )


def run_deep_check() -> dict[str, Any]:
    """Push one second of silence through every loaded model, one at a time, the way a request would.

    Each transcription model is reported by its id under `models`, and `transcriber` is the worst
    of them, so a check that reads only that line still sees one broken model among several.
    """
    silence = np.zeros(speech_gate.SAMPLE_RATE, dtype=np.int16)
    models = {spec["id"]: check_transcriber(spec, silence) for spec in registry.get_model_specs()}
    results: dict[str, Any] = {"transcriber": max(models.values(), key=CHECK_SEVERITY.index), "models": models}
    if config.DIARIZE_ENABLED:
        results["diarizer"] = check_model(
            model_pool.acquire_diarizer,
            model_pool.release_diarizer,
            lambda diarizer: diarize.diarize_wav(stream.encode_wav(silence), diarizer=diarizer),
        )
    return results


@app.route("/api/health", methods=["GET"])
def health():
    """Report service liveness and model pool occupancy.

    Open, so healthchecks need no token. The top-level `pool_size` and `available` describe the
    default model (available=0 means every instance of it is busy). `default_model` and `models`
    (every loaded model's pool by id) name the deployment's configuration, so like /api/models
    they are only included for a caller that passes the token check, or when auth is off.

    `?deep=1` also runs one second of silence through every loaded model, one at a time, and
    reports each as ok, busy or failed - every transcription model by its id under
    `deep.models`, `deep.transcriber` the worst of them, `deep.diarizer` when diarization is on -
    answering 503 if any failed. That costs GPU work, so while STT_TOKENS is set it needs a token
    like every other route; the plain check stays open for container healthchecks.
    """
    authorized = is_request_authorized()
    body = {"status": "ok", **model_pool.get_pool_status(detailed=authorized)}
    if request.args.get("deep", "").lower() not in config.TRUE_VALUES:
        return jsonify(body), 200
    if not authorized:
        logger.warning("[%s] Unauthorized deep health check", get_request_id())
        return build_error_response("Unauthorized", 401)
    body["deep"] = run_deep_check()
    if "failed" in body["deep"].values():
        body["status"] = "failed"
        return jsonify(body), 503
    return jsonify(body), 200


@app.route("/metrics", methods=["GET"])
def prometheus_metrics():
    """Prometheus metrics. Open like /api/health, and like it not proxied by stt_www: scrape :STT_PORT.

    Also like health, the per-model gauges only carry the loaded models, and the per-model latency
    series only appear, for a scrape that passes the token check, or when auth is off; see
    is_scrape_detailed.
    """
    body, content_type = metrics.render()
    return body, 200, {"Content-Type": content_type}


@app.route("/api/models", methods=["GET"])
@token_required
def list_models():
    """Report the models this server carries, each with its own language list.

    Behind the token like every other non-health route: a catalogue publishes the server's
    configuration, including which model is loaded and where it is in its lifecycle.

    One row per loaded model (a request may name its `id` as `model`), one row for a
    transcriber with nothing loaded, and the diarizer when it is on. `status` is one of
    `loaded` (instances were loaded into its pool, free or busy), `installed` (the weights are
    on disk but nothing is loaded yet) or `absent`. A backend that is configured but not
    installed says `absent` and nothing more; the reason is in the log.

    `selectable` says whether a request may name the row as its `model`, `pool_size` and
    `available` are that model's pool, and exactly one row has `default` true: its id is the
    top-level `default_model`, and its backend the top-level `default`.

    `languages` is per row and never a union, because the sets genuinely diverge.
    `accepts_language` says whether `?language=` means anything to that backend at all.
    """
    return jsonify(catalog.list_models()), 200


def transcribe_text(wav_bio, model, language, spec) -> tuple[str, str | None]:
    """The plain transcript and its language; with the speech gate on, built only from segments that were spoken.

    Without the gate the text is exactly what it always was. With it, the text is the joined
    segment texts - what the transcriber's own text is made of - minus the ones the gate drops, so
    a recording with speech in it reads the same and one without reads empty instead of a
    subtitle credit such as "to be continued...". Either way one decode by the spec's backend
    gives the text, the segments and the language the model reports.
    """
    with metrics.measure_inference(spec["id"], spec["backend"]):
        result = backends.transcriber_for_backend(spec["backend"]).get_stt_result(wav_bio, model=model, language=language)
    if not config.SPEECH_GATE:
        return result["text"], result["language"]
    kept = speech_gate.gate_wav(wav_bio, result["segments"], get_request_id())
    return "".join(segment["text"] for segment in kept).strip(), result["language"]


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

    spec, language, refusal = resolve_request_options()
    if spec is None:
        return refusal

    wav_bio = convert_upload(bio)
    if wav_bio is None:
        return build_error_response("Invalid audio data", 400)

    try:
        model = model_pool.acquire_request_model(model_id=spec["id"])
    except queue.Empty:
        logger.warning("[%s] Model pool exhausted: %s", get_request_id(), model_pool.get_pool_status())
        return build_error_response("Service Unavailable", 503)

    try:
        text, detected = transcribe_text(wav_bio, model, language, spec)
        elapsed = time.monotonic() - start_time
        logger.info(
            "[%s] STT %s (%dkb) model=%s language=%s - %d chars (%.2fs)",
            get_request_id(),
            filename,
            size_kb,
            spec["id"],
            detected,
            len(text),
            elapsed,
        )
        return jsonify({"text": text, "elapsed": round(elapsed, 3), "model": spec["id"], "language": detected}), 200
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
    refusal = diarization_refusal()
    if refusal is not None:
        return refusal

    start_time = time.monotonic()

    upload = read_audio_upload()
    if upload is None:
        return build_error_response("No audio data", 400)
    bio, filename = upload
    size_kb = len(bio.getvalue()) // 1024

    wav_bio = convert_upload(bio)
    if wav_bio is None:
        return build_error_response("Invalid audio data", 400)

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
    model = model_pool.acquire_request_model(model_id=spec["id"])
    try:
        wav_bio.seek(0)
        with metrics.measure_inference(spec["id"], spec["backend"]):
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
    refusal = diarization_refusal()
    if refusal is not None:
        return refusal

    start_time = time.monotonic()

    upload = read_audio_upload()
    if upload is None:
        return build_error_response("No audio data", 400)
    bio, filename = upload
    size_kb = len(bio.getvalue()) // 1024

    spec, language, refusal = resolve_request_options()
    if spec is None:
        return refusal

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

    if config.SPEECH_GATE:
        segments = speech_gate.gate_wav(wav_bio, segments, get_request_id())
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


def resolve_job_options(mode: str) -> tuple[dict[str, Any] | None, str | None, Any]:
    """Resolve a job's model and language the way the endpoint its mode stands in for does.

    `text` and `speakers` transcribe, so like /api/stt and /api/transcript they take `model` and
    have the language checked against that model. `turns` transcribes nothing: like /api/diarize
    it reads no `model`, and its language is only checked for being a language at all, as every
    job's was before models were selectable. Returns (spec, language, None), the spec None for
    `turns`, or (None, None, the 400 to answer).
    """
    if mode != "turns":
        return resolve_request_options()
    language, error = backends.resolve_language_code(read_language_argument(), registry.get_default_spec())
    if error is not None:
        return None, None, build_error_response(error, 400)
    return None, language, None


def job_view(job: dict[str, Any]) -> dict[str, Any]:
    """What a client sees of a job record, with its place in the queue while it waits."""
    view = {
        key: job.get(key)
        for key in (
            "id",
            "status",
            "mode",
            "model",
            "language",
            "filename",
            "size",
            "created",
            "started",
            "finished",
            "seconds",
            "error",
        )
    }
    view["position"] = jobs.queue_position(job)
    return view


@app.route(JOBS_PATH, methods=["POST"])
@token_required
def submit_job():
    """Accept a recording for background processing and answer at once with the job's id.

    The same body shapes as /api/stt, up to JOB_MAX_CONTENT_LENGTH_MB. `mode` is `text` (the
    default), `speakers` (the /api/transcript result) or `turns` (the /api/diarize result);
    `model` and `language` as on the endpoint the mode stands in for. A job that transcribes
    keeps the model it was accepted for, named in its record: it runs on that model and on no
    other. The upload is written to disk as it arrives, never held whole in memory. Returns 202
    with the job record and a Location to poll.
    """
    mode = (request.args.get("mode") or request.form.get("mode") or "text").strip().lower()
    if mode not in jobs.MODES:
        return build_error_response("Invalid mode", 400)
    if mode != "text":
        refusal = diarization_refusal()
        if refusal is not None:
            return refusal
    spec, language, refusal = resolve_job_options(mode)
    if refusal is not None:
        return refusal
    if "file" in request.files:
        upload = request.files["file"]
        filename = upload.filename or "upload"

        def save_input(path):
            """Stream the multipart file to disk."""
            upload.save(path)

    elif request.content_length:
        filename = "raw_body"

        def save_input(path):
            """Stream the raw body to disk."""
            with open(path, "wb") as handle:
                shutil.copyfileobj(request.stream, handle)

    else:
        return build_error_response("No audio data", 400)
    job = jobs.create_job(save_input, filename, mode, language, spec["id"] if spec is not None else None)
    return jsonify(job_view(job)), 202, {"Location": f"{JOBS_PATH}/{job['id']}"}


@app.route(JOBS_PATH, methods=["GET"])
@token_required
def list_jobs():
    """The jobs on this server, newest first, without their results."""
    return jsonify({"jobs": [job_view(job) for job in reversed(jobs.all_jobs())]}), 200


@app.route(f"{JOBS_PATH}/<job_id>", methods=["GET"])
@token_required
def get_job(job_id):
    """A job's state, and its result once it is done - the same shape as the matching endpoint."""
    job = jobs.read_job(job_id)
    if job is None:
        return build_error_response("Job not found", 404)
    view = job_view(job)
    if job["status"] == "done":
        view["result"] = jobs.read_result(job_id)
    return jsonify(view), 200


@app.route(f"{JOBS_PATH}/<job_id>", methods=["DELETE"])
@token_required
def remove_job(job_id):
    """Delete a job and its files. A job being processed right now cannot be deleted: 409."""
    outcome = jobs.delete_job(job_id)
    if outcome == "missing":
        return build_error_response("Job not found", 404)
    if outcome == "running":
        return build_error_response("Job is running", 409)
    return jsonify({"deleted": job_id}), 200


@app.route(openai_api.TRANSCRIPTIONS_PATH, methods=["POST"])
@token_required
def transcribe_openai():
    """Transcribe an upload the way OpenAI's POST /v1/audio/transcriptions does, for its SDKs.

    multipart/form-data with ``file``; ``model`` and ``language`` are resolved exactly as on
    /api/stt, so a model is one of the ids GET /v1/models lists and none means the default.
    ``prompt`` becomes Whisper's initial prompt and is ignored by Parakeet; it is never logged.
    ``temperature`` must be absent or 0, ``response_format`` is ``json`` (the default), ``text``
    or ``verbose_json``, and ``timestamp_granularities[]`` may only ask for ``segment``. The
    same token, size limit, conversion, speech gate and STT_QUEUE_TIMEOUT wait apply as on
    /api/stt; errors take OpenAI's shape.
    """
    start_time = time.monotonic()

    upload = read_audio_upload()
    if upload is None:
        return build_error_response("No audio data", 400)
    bio, filename = upload
    size_kb = len(bio.getvalue()) // 1024

    options, refusal = openai_api.read_transcription_options(request.form)
    if options is None:
        return refusal
    spec, language, refusal = resolve_request_options()
    if spec is None:
        return refusal

    wav_bio = convert_upload(bio)
    if wav_bio is None:
        return build_error_response("Invalid audio data", 400)

    try:
        model = model_pool.acquire_request_model(model_id=spec["id"])
    except queue.Empty:
        logger.warning("[%s] Model pool exhausted: %s", get_request_id(), model_pool.get_pool_status())
        return build_error_response("Service Unavailable", 503)

    try:
        result = openai_api.transcribe_wav(wav_bio, model, language, spec, options["prompt"])
    except Exception as exc:
        logger.error("[%s] STT failed: %s: %s\n%s", get_request_id(), type(exc).__name__, exc, traceback.format_exc())
        return build_error_response("Transcription failed", 500)
    finally:
        model_pool.release_model(model, model_id=spec["id"])

    logger.info(
        "[%s] OpenAI STT %s (%dkb) model=%s language=%s format=%s - %d chars (%.2fs)",
        get_request_id(),
        filename,
        size_kb,
        spec["id"],
        result["language_code"],
        options["response_format"],
        len(result["text"]),
        time.monotonic() - start_time,
    )
    return openai_api.build_transcription_response(result, options["response_format"])


@app.route(openai_api.MODELS_PATH, methods=["GET"])
@token_required
def list_openai_models():
    """The loaded models in OpenAI's GET /v1/models shape, by the ids /api/models uses; behind the token like it."""
    return jsonify(openai_api.list_openai_models()), 200


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

    uvicorn.run(
        asgi_app,
        host=config.STT_HOST,
        port=config.STT_PORT,
        log_level=config.LOG_LEVEL.lower(),
        log_config=logs.build_uvicorn_log_config(),
        access_log=config.LOG_ACCESS,
        timeout_keep_alive=config.STT_KEEPALIVE_SECONDS,
    )


def main():
    """Entry point: fill every model's pool, then serve."""
    model_pool.init_model_pool()
    model_pool.init_diarizer_pool()
    if config.SPEECH_GATE:
        speech_gate.find_speech(np.zeros(speech_gate.SAMPLE_RATE, dtype=np.float32))
    jobs.start_worker()
    log_auth_mode()
    run_server()


if __name__ == "__main__":
    main()

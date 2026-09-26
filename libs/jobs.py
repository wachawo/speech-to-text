#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background jobs for long recordings: the file goes in now, the result is fetched later by id.

A synchronous request holds the client, and nginx, for as long as the transcription takes. A job
is written to disk at once and answered with its id; a worker thread in each server process takes
queued jobs one at a time and writes the result next to them. Everything lives in files under
JOBS_DIR, so a job survives a restart, and a job is claimed with an flock, so several gunicorn
workers never run the same one twice and a job whose worker died is simply claimed again.
"""

import fcntl
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from typing import Any

# Local imports
from libs import config, longform, metrics

logger = logging.getLogger(__name__)

MODES = ("text", "speakers", "turns")

# How often an idle worker looks for work it was not woken for: a job another process accepted.
POLL_SECONDS = 2.0

# Finished jobs are looked at for removal at most this often.
CLEANUP_SECONDS = 600

JOB_ID_LENGTH = 16
INPUT_NAME = "input"
AUDIO_NAME = "audio.wav"
JOB_NAME = "job.json"
RESULT_NAME = "result.json"
LOCK_NAME = "job.lock"

WAKE = threading.Event()
STOP = threading.Event()
WORKER: dict[str, Any] = {"thread": None, "cleaned": 0.0}


def is_valid_id(job_id: str) -> bool:
    """Whether a string is a job id: exactly JOB_ID_LENGTH lower-case hex digits, nothing to traverse."""
    return len(job_id) == JOB_ID_LENGTH and all(character in "0123456789abcdef" for character in job_id)


def job_path(job_id: str, name: str = "") -> str:
    """A path inside a job's directory."""
    return os.path.join(config.JOBS_DIR, job_id, name)


def write_json(path: str, data: dict[str, Any]) -> None:
    """Write JSON atomically: a reader never sees a half-written job or result."""
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.replace(temporary, path)


def read_json(path: str) -> dict[str, Any] | None:
    """Read a JSON file, or None when it is missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def read_job(job_id: str) -> dict[str, Any] | None:
    """A job's record, or None when there is no such job."""
    if not is_valid_id(job_id):
        return None
    return read_json(job_path(job_id, JOB_NAME))


def update_job(job: dict[str, Any], **changes) -> dict[str, Any]:
    """Apply changes to a job's record and write it."""
    job.update(changes)
    write_json(job_path(job["id"], JOB_NAME), job)
    return job


def create_job(save_input, filename: str, mode: str, language: str | None) -> dict[str, Any]:
    """Accept a job: `save_input(path)` writes the upload to disk, then the job is queued."""
    job_id = uuid.uuid4().hex[:JOB_ID_LENGTH]
    os.makedirs(job_path(job_id), exist_ok=True)
    save_input(job_path(job_id, INPUT_NAME))
    job = {
        "id": job_id,
        "status": "queued",
        "mode": mode,
        "language": language,
        "filename": filename,
        "size": os.path.getsize(job_path(job_id, INPUT_NAME)),
        "created": time.time(),
        "started": None,
        "finished": None,
        "seconds": None,
        "error": None,
    }
    write_json(job_path(job_id, JOB_NAME), job)
    metrics.JOBS.labels(status="queued").inc()
    logger.info("[%s] Job queued - %s, %s, %d bytes", job_id, mode, filename, job["size"])
    WAKE.set()
    return job


def all_jobs() -> list[dict[str, Any]]:
    """Every job record on disk, oldest first."""
    if not os.path.isdir(config.JOBS_DIR):
        return []
    jobs = [read_job(name) for name in os.listdir(config.JOBS_DIR) if is_valid_id(name)]
    return sorted((job for job in jobs if job), key=lambda job: job["created"])


def queue_position(job: dict[str, Any]) -> int | None:
    """1 for the next job to run; None when the job is not waiting."""
    if job["status"] != "queued":
        return None
    waiting = [other for other in all_jobs() if other["status"] in ("queued", "running")]
    return 1 + sum(1 for other in waiting if other["created"] < job["created"])


def read_result(job_id: str) -> dict[str, Any] | None:
    """A finished job's result, or None."""
    return read_json(job_path(job_id, RESULT_NAME))


def try_lock(job_id: str) -> int | None:
    """Take the job's lock without waiting: its file descriptor, or None when somebody holds it."""
    descriptor = os.open(job_path(job_id, LOCK_NAME), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None
    return descriptor


def unlock(descriptor: int) -> None:
    """Release a job's lock."""
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def delete_job(job_id: str) -> str:
    """Remove a job and its files: "deleted", "running" when it is being processed, or "missing"."""
    if read_job(job_id) is None:
        return "missing"
    descriptor = try_lock(job_id)
    if descriptor is None:
        return "running"
    try:
        shutil.rmtree(job_path(job_id), ignore_errors=True)
    finally:
        os.close(descriptor)
    logger.info("[%s] Job deleted", job_id)
    return "deleted"


def claim_next() -> tuple[dict[str, Any], int] | None:
    """Lock the oldest job that still needs running, with its lock; None when there is none.

    A job recorded as running whose lock is free was being run by a process that died; it is run
    again from the start.
    """
    for job in all_jobs():
        if job["status"] not in ("queued", "running"):
            continue
        descriptor = try_lock(job["id"])
        if descriptor is None:
            continue
        fresh = read_job(job["id"])
        if fresh and fresh["status"] in ("queued", "running"):
            return fresh, descriptor
        unlock(descriptor)
    return None


def decode_to_wav(source: str, target: str) -> bool:
    """Decode any audio file into 16 kHz mono 16-bit WAV on disk with ffmpeg; False when it is not audio.

    ffmpeg writes to disk as it decodes: an hour of stereo 44.1 kHz audio decoded in memory, the way
    the synchronous path does for short uploads, would take hundreds of megabytes per job.
    """
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        source,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        target,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        logger.warning("Job audio not decodable: %s", completed.stderr.strip()[-300:])
        return False
    return True


def run_job(job: dict[str, Any], descriptor: int) -> None:
    """Run one claimed job to its end: done with a result, failed with a category, or back in the queue."""
    job_id = job["id"]
    started = time.time()
    update_job(job, status="running", started=started)
    try:
        if not os.path.exists(job_path(job_id, AUDIO_NAME)) and not decode_to_wav(
            job_path(job_id, INPUT_NAME), job_path(job_id, AUDIO_NAME)
        ):
            update_job(job, status="failed", error="Invalid audio data", finished=time.time())
            metrics.JOBS.labels(status="failed").inc()
            return
        result = longform.run(job["mode"], job_path(job_id, AUDIO_NAME), job["language"], job_id)
        write_json(job_path(job_id, RESULT_NAME), result)
        update_job(job, status="done", finished=time.time(), seconds=result.get("seconds"), error=None)
        metrics.JOBS.labels(status="done").inc()
        for name in (INPUT_NAME, AUDIO_NAME):
            with_path = job_path(job_id, name)
            if os.path.exists(with_path):
                os.remove(with_path)
        logger.info(
            "[%s] Job done - %s, %.1fs of audio (%.2fs)", job_id, job["mode"], result.get("seconds") or 0, time.time() - started
        )
    except queue.Empty:
        # Every model stayed busy for the whole acquire timeout: not the job's fault, try again later.
        logger.warning("[%s] Job waited too long for a model, back in the queue", job_id)
        update_job(job, status="queued", started=None)
    except Exception as exc:
        logger.error("[%s] Job failed: %s: %s\n%s", job_id, type(exc).__name__, exc, traceback.format_exc())
        update_job(job, status="failed", error="Transcription failed", finished=time.time())
        metrics.JOBS.labels(status="failed").inc()
    finally:
        unlock(descriptor)


def remove_expired(now: float | None = None) -> int:
    """Remove finished jobs older than JOB_RETENTION_HOURS; the number removed."""
    now = time.time() if now is None else now
    removed = 0
    for job in all_jobs():
        finished = job.get("finished")
        if job["status"] in ("done", "failed") and finished and now - finished > config.JOB_RETENTION_HOURS * 3600:
            if delete_job(job["id"]) == "deleted":
                removed += 1
    return removed


def run_pending() -> int:
    """Run every job that can be claimed right now; the number run. The worker loop's one step."""
    count = 0
    while not STOP.is_set():
        claimed = claim_next()
        if claimed is None:
            return count
        run_job(*claimed)
        count += 1
    return count


def work_forever() -> None:
    """The worker thread: run what is queued, clean up now and then, sleep until woken or polled."""
    os.makedirs(config.JOBS_DIR, exist_ok=True)
    while not STOP.is_set():
        try:
            run_pending()
            if time.time() - WORKER["cleaned"] > CLEANUP_SECONDS:
                WORKER["cleaned"] = time.time()
                removed = remove_expired()
                if removed:
                    logger.info("Removed %d expired jobs", removed)
        except Exception as exc:
            logger.error("Job worker error: %s: %s\n%s", type(exc).__name__, exc, traceback.format_exc())
        WAKE.wait(POLL_SECONDS)
        WAKE.clear()


def start_worker() -> None:
    """Start this process's job worker thread, once."""
    if WORKER["thread"] is not None:
        return
    thread = threading.Thread(target=work_forever, name="jobs", daemon=True)
    WORKER["thread"] = thread
    thread.start()
    logger.info("Job worker started (%s)", config.JOBS_DIR)


def main():
    """No-op entry point: stt_server.py starts the worker and serves the routes."""
    pass


if __name__ == "__main__":
    main()

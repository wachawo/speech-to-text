#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background jobs: accepted at once, run by the worker, fetched by id, and never run twice."""

import io
import os
import queue
import shutil

import pytest

from libs import config, jobs, longform
from tests.helpers import make_wav

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs the ffmpeg binary")


@pytest.fixture
def jobs_dir(tmp_path, monkeypatch):
    """Jobs in a fresh directory, and a pipeline that returns a fixed result instead of running models."""
    monkeypatch.setattr(config, "JOBS_DIR", str(tmp_path / "jobs"))
    calls = []

    def fake_run(mode, wav_path, language, request_id):
        """Record the call and answer like the text mode would."""
        calls.append((mode, os.path.basename(wav_path), language, request_id))
        return {"text": "hello", "segments": [], "seconds": 0.1}

    monkeypatch.setattr(longform, "run", fake_run)
    return calls


def submit(client, data: bytes | None = None, **params):
    """POST a job and return the response."""
    body = {"file": (io.BytesIO(make_wav() if data is None else data), "a.wav")}
    return client.post("/api/jobs", query_string=params, data=body)


def test_a_job_is_accepted_at_once(client, jobs_dir):
    """202 with the record, a Location to poll, the upload on disk and nothing run yet."""
    response = submit(client, mode="text")
    assert response.status_code == 202
    job = response.get_json()
    assert job["status"] == "queued" and job["position"] == 1 and job["mode"] == "text"
    assert response.headers["Location"] == f"/api/jobs/{job['id']}"
    assert os.path.exists(os.path.join(config.JOBS_DIR, job["id"], jobs.INPUT_NAME))
    assert jobs_dir == []


@needs_ffmpeg
def test_the_worker_runs_it_and_the_result_is_served(client, jobs_dir):
    """The worker decodes the upload, runs the pipeline, stores the result and removes the audio."""
    job_id = submit(client, mode="text", language="ru").get_json()["id"]
    assert jobs.run_pending() == 1
    body = client.get(f"/api/jobs/{job_id}").get_json()
    assert body["status"] == "done" and body["result"]["text"] == "hello"
    assert jobs_dir == [("text", jobs.AUDIO_NAME, "ru", job_id)]
    assert not os.path.exists(os.path.join(config.JOBS_DIR, job_id, jobs.INPUT_NAME))
    assert not os.path.exists(os.path.join(config.JOBS_DIR, job_id, jobs.AUDIO_NAME))


@needs_ffmpeg
def test_an_upload_that_is_not_audio_fails_with_its_category(client, jobs_dir):
    """ffmpeg cannot decode it: the job fails as Invalid audio data and the pipeline never runs."""
    job_id = submit(client, data=b"this is not audio at all").get_json()["id"]
    jobs.run_pending()
    body = client.get(f"/api/jobs/{job_id}").get_json()
    assert body["status"] == "failed" and body["error"] == "Invalid audio data"
    assert jobs_dir == []


@needs_ffmpeg
def test_a_pipeline_failure_is_a_failed_job(client, jobs_dir, monkeypatch):
    """An exception inside the pipeline fails the job with a generic category, detail only in the log."""

    def broken_run(mode, wav_path, language, request_id):
        """Fail like a CUDA error would."""
        raise RuntimeError("CUDA error")

    monkeypatch.setattr(longform, "run", broken_run)
    job_id = submit(client).get_json()["id"]
    jobs.run_pending()
    body = client.get(f"/api/jobs/{job_id}").get_json()
    assert body["status"] == "failed" and body["error"] == "Transcription failed"
    assert "CUDA" not in str(body)


@needs_ffmpeg
def test_a_job_that_cannot_get_a_model_goes_back_to_the_queue(client, jobs_dir, monkeypatch):
    """Every model busy for the whole timeout is not the job's fault: it is queued again."""

    def busy_run(mode, wav_path, language, request_id):
        """Behave like an exhausted pool."""
        raise queue.Empty

    monkeypatch.setattr(longform, "run", busy_run)
    job_id = submit(client).get_json()["id"]
    claimed = jobs.claim_next()
    jobs.run_job(*claimed)
    assert client.get(f"/api/jobs/{job_id}").get_json()["status"] == "queued"


def test_a_locked_job_is_not_claimed_twice(client, jobs_dir):
    """Another process holding the job's lock means this one leaves it alone."""
    job_id = submit(client).get_json()["id"]
    held = jobs.try_lock(job_id)
    try:
        assert jobs.claim_next() is None
    finally:
        jobs.unlock(held)
    claimed = jobs.claim_next()
    assert claimed is not None and claimed[0]["id"] == job_id
    jobs.unlock(claimed[1])


def test_a_job_left_running_by_a_dead_process_is_claimed_again(client, jobs_dir):
    """Recorded as running with nobody holding its lock: its process died, and it is run again."""
    job_id = submit(client).get_json()["id"]
    job = jobs.read_job(job_id)
    jobs.update_job(job, status="running")
    claimed = jobs.claim_next()
    assert claimed is not None and claimed[0]["id"] == job_id
    jobs.unlock(claimed[1])


def test_positions_follow_the_order_of_arrival(client, jobs_dir):
    """The second job waits behind the first."""
    first = submit(client).get_json()
    second = submit(client).get_json()
    assert (first["position"], second["position"]) == (1, 2)
    listed = client.get("/api/jobs").get_json()["jobs"]
    assert [job["id"] for job in listed] == [second["id"], first["id"]]


def test_delete_removes_a_job_but_not_a_running_one(client, jobs_dir):
    """DELETE removes a waiting job; one being processed answers 409; an unknown one 404."""
    job_id = submit(client).get_json()["id"]
    held = jobs.try_lock(job_id)
    assert client.delete(f"/api/jobs/{job_id}").status_code == 409
    jobs.unlock(held)
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.delete(f"/api/jobs/{job_id}").status_code == 404


@pytest.mark.parametrize("job_id", ["../etc", "0123456789abcdeZ", "abc", "0123456789ABCDEF"])
def test_an_id_that_is_not_a_job_id_is_not_found(client, jobs_dir, job_id):
    """Anything but sixteen lower-case hex digits is refused before it touches the disk."""
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_expired_jobs_are_removed(client, jobs_dir, monkeypatch):
    """A finished job older than the retention is removed; a waiting one never is."""
    monkeypatch.setattr(config, "JOB_RETENTION_HOURS", 1)
    finished = submit(client).get_json()["id"]
    waiting = submit(client).get_json()["id"]
    jobs.update_job(jobs.read_job(finished), status="done", finished=1000.0)
    assert jobs.remove_expired(now=1000.0 + 7200) == 1
    assert jobs.read_job(finished) is None and jobs.read_job(waiting) is not None


def test_mode_and_language_are_checked_before_anything_is_stored(client, jobs_dir):
    """An unknown mode or language is refused and leaves no job behind."""
    assert submit(client, mode="karaoke").status_code == 400
    assert submit(client, language="zz").status_code == 400
    assert jobs.all_jobs() == []


def test_speaker_modes_need_the_diarizer(client, jobs_dir):
    """speakers and turns answer 503 while diarization is off."""
    assert submit(client, mode="speakers").status_code == 503
    assert submit(client, mode="turns").status_code == 503


def test_a_job_takes_a_larger_file_than_a_synchronous_request(client, jobs_dir, monkeypatch):
    """/api/jobs has its own, larger limit; /api/stt keeps MAX_CONTENT_LENGTH_MB."""
    monkeypatch.setattr(config, "JOB_MAX_CONTENT_LENGTH_MB", 2)
    monkeypatch.setitem(stt_server_app(client).config, "MAX_CONTENT_LENGTH", 1024 * 1024)
    payload = b"\0" * (int(1.5 * 1024 * 1024))
    assert client.post("/api/stt", data={"file": (io.BytesIO(payload), "big.wav")}).status_code == 413
    assert submit(client, data=payload).status_code == 202
    too_big = submit(client, data=b"\0" * (3 * 1024 * 1024))
    assert too_big.status_code == 413 and too_big.get_json()["limit_mb"] == 2


def test_a_raw_body_is_accepted_too(client, jobs_dir):
    """An audio/* body instead of a multipart form becomes a job the same way."""
    response = client.post("/api/jobs", data=make_wav(), content_type="audio/wav")
    assert response.status_code == 202 and response.get_json()["filename"] == "raw_body"


def test_jobs_need_the_token(client, jobs_dir, monkeypatch):
    """Like every route but health and metrics."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    assert submit(client).status_code == 401
    assert client.get("/api/jobs").status_code == 401


def stt_server_app(client):
    """The Flask app behind a test client."""
    return client.application

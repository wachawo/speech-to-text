#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gunicorn configuration and hooks for STT server."""

import fcntl
import logging
import os
import time

logger = logging.getLogger(__name__)

# Server socket
bind = f"0.0.0.0:{os.getenv('STT_PORT', '5099')}"

# Worker processes — sync is safest for CPU-bound torch/whisper inference.
# gthread causes hangs because PyTorch's MKL/OpenBLAS thread pools
# conflict with Gunicorn's threading model.
workers = int(os.getenv("GUNICORN_WORKERS", "4"))
worker_class = "sync"

# Timeouts
timeout = 600  # model loading + inference can be slow
graceful_timeout = 120


def on_starting(server):
    """Log master startup. No heavy imports here — torch + fork = deadlock."""
    logger.info(
        "Gunicorn master starting (workers=%s, worker_class=%s, bind=%s)",
        workers,
        worker_class,
        bind,
    )


def post_fork(server, worker):
    """Initialize Whisper model pool in each worker after fork.

    A file lock serializes workers so only one downloads the model at a time;
    the rest load from the cached .pt file on disk.

    With sync workers each process handles 1 request at a time,
    so STT_POOL_SIZE=1 per worker is sufficient.
    """
    # Prevent torch from spawning extra threads — one worker = one inference at a time
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("TORCH_NUM_THREADS", "1")

    lock_path = "/tmp/.stt_model_init.lock"
    t0 = time.monotonic()
    logger.info("Worker %s (pid %s): waiting for model init lock...", worker.age, worker.pid)

    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        logger.info(
            "Worker %s (pid %s): lock acquired, loading model(s)...", worker.age, worker.pid
        )
        from stt_server import MODEL_POOL_SIZE, init_model_pool

        init_model_pool(MODEL_POOL_SIZE)

    elapsed = time.monotonic() - t0
    logger.info("Worker %s (pid %s): model pool ready (%.2fs)", worker.age, worker.pid, elapsed)


def child_exit(server, worker):
    """Called when a worker process exits."""
    logger.info("Worker %s (pid %s) exited", worker.age, worker.pid)

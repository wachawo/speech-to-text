#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gunicorn configuration and hooks: one Whisper pool per worker, loaded after fork."""

import fcntl
import logging
import os
import time

# Local imports
from libs import config, logs

logs.setup_logging()
logger = logging.getLogger(__name__)

# Serializes the first model download across workers; the rest read the cached .pt file.
MODEL_INIT_LOCK_PATH = "/tmp/.stt_model_init.lock"

# Server socket
bind = f"0.0.0.0:{config.STT_PORT}"

# Worker processes — sync is safest for CPU-bound torch/whisper inference.
# gthread causes hangs because PyTorch's MKL/OpenBLAS thread pools
# conflict with Gunicorn's threading model.
workers = config.GUNICORN_WORKERS
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
    """Initialize the Whisper model pool in each worker after fork.

    A file lock serializes workers so only one downloads the model at a time;
    the rest load from the cached .pt file on disk.

    With sync workers each process handles one request at a time, so
    STT_POOL_SIZE=1 per worker is enough.
    """
    # Prevent torch from spawning extra threads — one worker = one inference at a time.
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("TORCH_NUM_THREADS", "1")

    start_time = time.monotonic()
    logger.info("Worker %s (pid %s): waiting for model init lock...", worker.age, worker.pid)

    with open(MODEL_INIT_LOCK_PATH, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        logger.info(
            "Worker %s (pid %s): lock acquired, loading model(s)...", worker.age, worker.pid
        )
        # Imported here, not at module scope: torch must never be loaded in the master.
        from libs.model_pool import init_model_pool

        init_model_pool()

    elapsed = time.monotonic() - start_time
    logger.info("Worker %s (pid %s): model pool ready (%.2fs)", worker.age, worker.pid, elapsed)


def child_exit(server, worker):
    """Log a worker leaving the pool so restarts are visible in the log."""
    logger.info("Worker %s (pid %s) exited", worker.age, worker.pid)

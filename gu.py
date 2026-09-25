#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gunicorn configuration and hooks: the model pools are filled per worker, after fork."""

import fcntl
import logging
import os
import time

# Local imports
# Aliased here and only here: gunicorn reads every module-level name in this file that matches
# one of its settings, `config` is one of them, and a module bound to it stops gunicorn at
# startup with "Invalid value for config".
from libs import config as stt_config
from libs import logs

logs.setup_logging()
logger = logging.getLogger(__name__)

# Serializes the first model download across workers; the rest read the cached .pt file.
MODEL_INIT_LOCK_PATH = "/tmp/.stt_model_init.lock"

# Server socket
bind = f"0.0.0.0:{stt_config.STT_PORT}"

# Worker processes - sync is safest for CPU-bound torch/whisper inference.
# gthread causes hangs because PyTorch's MKL/OpenBLAS thread pools
# conflict with Gunicorn's threading model.
workers = stt_config.GUNICORN_WORKERS
worker_class = "sync"

# Gunicorn 26 opens a control socket under $HOME by default. The server runs as `stt` with
# HOME still /root, so it fails and logs an ERROR on every start, and nothing here uses it.
control_socket_disable = True

# Timeouts
timeout = 600  # model loading + inference can be slow
graceful_timeout = 120


def on_starting(server):
    """Log master startup. No heavy imports here - torch + fork = deadlock."""
    logger.info(
        "Gunicorn master starting (workers=%s, worker_class=%s, bind=%s)",
        workers,
        worker_class,
        bind,
    )


def post_fork(server, worker):
    """Initialize the model pools in each worker after fork.

    A file lock serializes workers so only one downloads the models at a time;
    the rest load from the cache on disk. Every model in STT_MODELS loads under
    the same lock, so a first run downloads each of them exactly once.

    With sync workers each process handles one request at a time, so one
    instance per model per worker (STT_POOL_SIZE=1, or @1 on every STT_MODELS
    entry) is enough; concurrency comes from GUNICORN_WORKERS, and every extra
    instance only costs memory in every worker.
    """
    # Prevent torch from spawning extra threads - one worker = one inference at a time.
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("TORCH_NUM_THREADS", "1")

    start_time = time.monotonic()
    logger.info("Worker %s (pid %s): waiting for model init lock...", worker.age, worker.pid)

    with open(MODEL_INIT_LOCK_PATH, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        logger.info(
            "Worker %s (pid %s): lock acquired, loading %d model(s)...",
            worker.age,
            worker.pid,
            len(stt_config.STT_MODELS) or 1,
        )
        # Imported here, not at module scope: torch must never be loaded in the master.
        from libs.model_pool import init_diarizer_pool, init_model_pool

        init_model_pool()
        # Inside the same lock on purpose: both models download to disk on first run, and two
        # workers racing to fetch them is the problem this lock exists to prevent.
        init_diarizer_pool()

    elapsed = time.monotonic() - start_time
    logger.info("Worker %s (pid %s): model pool ready (%.2fs)", worker.age, worker.pid, elapsed)


def child_exit(server, worker):
    """Log a worker leaving the pool so restarts are visible in the log."""
    logger.info("Worker %s (pid %s) exited", worker.age, worker.pid)

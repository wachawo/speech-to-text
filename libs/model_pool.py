#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pool of pre-loaded Whisper instances — Whisper is not thread-safe, so requests borrow one."""

import logging
import queue
import time
from typing import Any

# Local imports
from libs import config, stt

logger = logging.getLogger(__name__)

# How long a request waits for a free model before the pool is declared exhausted.
MODEL_ACQUIRE_TIMEOUT = 120

MODEL_POOL: queue.Queue = queue.Queue()


def init_model_pool(size: int = config.MODEL_POOL_SIZE) -> None:
    """Pre-load `size` Whisper instances into the pool. Called once per process at startup."""
    logger.info("Initializing %d Whisper model instances...", size)
    for number in range(1, size + 1):
        start_time = time.monotonic()
        model = stt.get_model()
        MODEL_POOL.put(model)
        logger.info("Model #%d ready (%.2fs)", number, time.monotonic() - start_time)
    logger.info("Model pool ready: %d instances", MODEL_POOL.qsize())


def acquire_model(timeout: int = MODEL_ACQUIRE_TIMEOUT) -> Any:
    """Take a model out of the pool; raises queue.Empty when none frees up in time."""
    return MODEL_POOL.get(timeout=timeout)


def release_model(model: Any) -> None:
    """Return a model to the pool so the next request can use it."""
    MODEL_POOL.put(model)


def get_pool_status() -> dict[str, int]:
    """Report the configured pool size and how many models are currently free."""
    return {"pool_size": config.MODEL_POOL_SIZE, "available": MODEL_POOL.qsize()}


def main():
    """No-op entry point: this module is imported for its pool helpers."""
    pass


if __name__ == "__main__":
    main()

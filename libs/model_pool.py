#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pools of pre-loaded models - no transcriber and no diarizer is thread-safe, so requests borrow one."""

import logging
import queue
import time
import traceback
from typing import Any

# Local imports
from libs import backends, config, diarize, registry

logger = logging.getLogger(__name__)

# How long a request waits for a free model before the pool is declared exhausted.
MODEL_ACQUIRE_TIMEOUT = 120

# The diarizer gets a much shorter bound. Transcription is minutes of work, so waiting for it
# is reasonable; diarization is a fraction of realtime, so a wait this long means the pool is
# genuinely oversubscribed, and parking a WSGI thread for two minutes starves everything else,
# including the healthcheck.
DIARIZER_ACQUIRE_TIMEOUT = 30

# One queue per transcription model, keyed by its canonical id. A request names the model it
# wants and borrows from that model's queue only, so an instance always goes back where it came
# from and no caller has to check what kind of model it was handed.
MODEL_POOLS: dict[str, queue.Queue] = {}
# How many instances of each model were created. A model whose every instance is busy has an
# empty queue and is still loaded, which is what this counter lets the catalogue tell apart.
MODELS_LOADED: dict[str, int] = {}
DIARIZER_POOL: queue.Queue = queue.Queue()

# How many diarizers actually loaded. Zero with diarization switched on means loading failed,
# which is not the same as "all of them are busy" and must not cost a request the full timeout.
DIARIZERS_LOADED = 0


def init_model_pool() -> None:
    """Validate the model list, then pre-load every model's instances into its own queue.

    Called once per process at startup. Each model loads exactly its spec's pool_size, the
    number health, the catalogue and the startup log report. A model that fails to load raises:
    a transcription service that cannot load a configured model must not report itself healthy.
    Sizes are read at call time, so a test or a caller that changes `config.MODEL_POOL_SIZE` is
    actually obeyed.
    """
    registry.validate_model_specs()
    for spec in registry.get_model_specs():
        count = spec["pool_size"]
        transcriber = backends.transcriber_for_backend(spec["backend"])
        pool = get_model_pool(spec["id"])
        logger.info("Initializing %d %s model instances of %s...", count, spec["backend"], spec["id"])
        for number in range(1, count + 1):
            start_time = time.monotonic()
            pool.put(transcriber.get_model(model_name=spec["model"]))
            MODELS_LOADED[spec["id"]] = MODELS_LOADED.get(spec["id"], 0) + 1
            logger.info("Model %s #%d ready (%.2fs)", spec["id"], number, time.monotonic() - start_time)
    logger.info("Model pools ready: %s", registry.describe_model_specs())


def init_diarizer_pool(size: int | None = None) -> None:
    """Pre-load diarizer instances into their own pool, or do nothing when diarization is off.

    A separate queue rather than a second kind of entry in MODEL_POOLS: a queue hands out
    whatever is at its head and has no notion of kind, so mixing the two would make every
    caller check what it got.
    """
    if not config.DIARIZE_ENABLED:
        logger.info("Diarization disabled (DIARIZE_ENABLED is false); no diarizer loaded")
        return

    global DIARIZERS_LOADED

    size = config.DIARIZE_POOL_SIZE if size is None else size
    logger.info("Initializing %d diarizer instances (%s)...", size, config.DIARIZE_MODEL)
    for number in range(1, size + 1):
        start_time = time.monotonic()
        try:
            DIARIZER_POOL.put(diarize.get_diarizer())
            DIARIZERS_LOADED += 1
        except Exception as exc:
            # An optional backend must fail optionally. Raising here would abort main(), and
            # under Gunicorn it would raise inside post_fork and boot-loop every worker, so a
            # missing diarization dependency would take transcription down with it. Leave the
            # pool empty instead: /api/diarize answers 503 and /api/stt keeps serving.
            logger.error(
                "Diarizer #%d failed to load, diarization will be unavailable: %s: %s\n%s",
                number,
                type(exc).__name__,
                exc,
                traceback.format_exc(),
            )
            return
        logger.info("Diarizer #%d ready (%.2fs)", number, time.monotonic() - start_time)
    logger.info("Diarizer pool ready: %d instances", DIARIZER_POOL.qsize())


def get_model_pool(model_id: str | None = None) -> queue.Queue:
    """The queue of one model; None means the default model."""
    model_id = registry.get_default_model_id() if model_id is None else model_id
    return MODEL_POOLS.setdefault(model_id, queue.Queue())


def acquire_model(timeout: int = MODEL_ACQUIRE_TIMEOUT, model_id: str | None = None) -> Any:
    """Take an instance of the given (or default) model; raises queue.Empty when none frees up in time."""
    return get_model_pool(model_id).get(timeout=timeout)


def release_model(model: Any, model_id: str | None = None) -> None:
    """Return an instance to the pool of the model it came from."""
    get_model_pool(model_id).put(model)


def count_available(model_id: str) -> int:
    """How many instances of a model are idle right now; zero for a model with no pool."""
    pool = MODEL_POOLS.get(model_id)
    return pool.qsize() if pool is not None else 0


def is_model_loaded(model_id: str) -> bool:
    """Whether instances of this model exist, busy or idle: MODELS_LOADED > 0 or a non-empty queue.

    The queue alone is not enough: a model whose every instance is in flight has an empty queue,
    and reporting it as merely installed would be wrong exactly when it is busiest.
    """
    return MODELS_LOADED.get(model_id, 0) > 0 or count_available(model_id) > 0


def diarizer_ready() -> bool:
    """Whether a diarizer exists at all, as opposed to every one of them being busy.

    True as soon as one instance was loaded, or as soon as the pool holds anything, so a test
    that fills the pool directly is served without also setting the counter.
    """
    return DIARIZERS_LOADED > 0 or not DIARIZER_POOL.empty()


def acquire_diarizer(timeout: int = DIARIZER_ACQUIRE_TIMEOUT) -> Any:
    """Take a diarizer out of its pool; raises queue.Empty when none frees up in time."""
    return DIARIZER_POOL.get(timeout=timeout)


def release_diarizer(diarizer: Any) -> None:
    """Return a diarizer to its pool so the next request can use it."""
    DIARIZER_POOL.put(diarizer)


def get_pool_status(detailed: bool = True) -> dict[str, Any]:
    """Report the default model's pool at the top level, the diarizer, and with `detailed` every model.

    The top-level `pool_size` and `available` describe the default model, because that is the
    pool a request without `model` waits on; with STT_MODELS empty they are what they always were.
    `default_model` and `models` name what this server loaded, which is configuration: the open
    /api/health only adds them for a caller that /api/models would also serve.
    """
    default_spec = registry.get_default_spec()
    status: dict[str, Any] = {
        "pool_size": default_spec["pool_size"],
        "available": count_available(default_spec["id"]),
        "diarize": config.DIARIZE_ENABLED,
    }
    if detailed:
        status["default_model"] = default_spec["id"]
        status["models"] = {
            spec["id"]: {"backend": spec["backend"], "pool_size": spec["pool_size"], "available": count_available(spec["id"])}
            for spec in registry.get_model_specs()
        }
    if config.DIARIZE_ENABLED:
        status["diarize_pool_size"] = config.DIARIZE_POOL_SIZE
        status["diarize_available"] = DIARIZER_POOL.qsize()
    return status


def main():
    """No-op entry point: this module is imported for its pool helpers."""
    pass


if __name__ == "__main__":
    main()

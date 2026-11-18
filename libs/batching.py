#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One thread per loaded model that decodes whatever requests are waiting for it as one batch."""

import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# What CUDA out-of-memory failures say: torch's OutOfMemoryError, and CTranslate2's RuntimeErrors.
MEMORY_ERROR_MARKERS = ("out of memory", "parallel_for failed")


def start_engine(model: Any, name: str, serve_batch: Callable[[Any, list[dict[str, Any]]], None]) -> dict[str, Any]:
    """Wrap a loaded model in an engine and start the one thread that ever decodes on it.

    `serve_batch(model, batch)` decodes a batch and sets each item's `result` or `error`; the
    engine wakes every caller afterwards, whatever it did. Started from a backend's get_model,
    which runs after fork(): a thread started in the Gunicorn master would not exist in its workers.
    """
    engine: dict[str, Any] = {"name": name, "model": model, "requests": queue.Queue()}
    thread = threading.Thread(target=run_engine, args=(engine, serve_batch), name=name, daemon=True)
    thread.start()
    return engine


def take_batch(requests: queue.Queue) -> list[dict[str, Any]]:
    """Block for one request, then take every other one already waiting.

    A lone request goes at once; whatever arrived while the previous batch ran goes together.
    The pool in front bounds how many can be waiting, so the batch needs no cap of its own.
    """
    batch = [requests.get()]
    while True:
        try:
            batch.append(requests.get_nowait())
        except queue.Empty:
            return batch


def run_engine(engine: dict[str, Any], serve_batch: Callable[[Any, list[dict[str, Any]]], None]) -> None:
    """The engine's thread: take a batch, decode it, wake its callers, forever."""
    while True:
        batch = take_batch(engine["requests"])
        try:
            run_safely(batch, serve_batch, engine["model"], batch)
        finally:
            for item in batch:
                item["done"].set()


def run_safely(items: list[dict[str, Any]], function: Callable[..., None], *args: Any) -> None:
    """Run one decoding step and hand any exception to the items it left without a result.

    Each caller re-raises it in its own request, which logs it under its request id; the engine
    thread itself must survive, or every later request would wait forever.
    """
    try:
        function(*args)
    except Exception as exc:
        for item in items:
            if item["result"] is None:
                item["error"] = exc


def is_memory_error(exc: Exception) -> bool:
    """Whether a decode failed for want of GPU memory: torch's OutOfMemoryError or CTranslate2's CUDA errors.

    CTranslate2 raises a plain RuntimeError. Out of memory, it says "CUDA failed with error out of
    memory" or, when the allocation that failed belonged to one of its kernels, "parallel_for
    failed" - both seen together in one burst on a card that a second process shared.
    """
    return isinstance(exc, RuntimeError) and any(marker in str(exc) for marker in MEMORY_ERROR_MARKERS)


def decode_in_halves(
    items: list[dict[str, Any]],
    decode: Callable[[Any, list[dict[str, Any]]], None],
    model: Any,
    release: Callable[[], None] | None = None,
) -> None:
    """Decode items as one batch; out of GPU memory, decode each half the same way, down to one item.

    A batch that does not fit when the card is shared - with another framework's cache in this
    process, or another process - would otherwise fail every request in it at once, while each
    half usually fits. `release` frees what the failed attempt left cached before the halves run.
    An item that fails alone, or any other error, is handed to the items left without a result.
    """
    try:
        decode(model, items)
    except Exception as exc:
        pending = [item for item in items if item["result"] is None]
        if len(pending) < 2 or not is_memory_error(exc):
            for item in pending:
                item["error"] = exc
            return
        logger.warning("Out of GPU memory decoding a batch of %d, retrying it in halves: %s", len(pending), exc)
        if release is not None:
            release()
        middle = len(pending) // 2
        decode_in_halves(pending[:middle], decode, model, release)
        decode_in_halves(pending[middle:], decode, model, release)


def submit_request(engine: dict[str, Any], item: dict[str, Any]) -> Any:
    """Hand one item to the engine and wait for its decode; raises whatever the decode raised."""
    item.update({"done": threading.Event(), "result": None, "error": None})
    engine["requests"].put(item)
    item["done"].wait()
    if item["error"] is not None:
        raise item["error"]
    return item["result"]


def main():
    """No-op entry point: this module is imported for its engine."""
    pass


if __name__ == "__main__":
    main()

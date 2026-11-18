#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One thread per loaded model that decodes whatever requests are waiting for it as one batch."""

import queue
import threading
from collections.abc import Callable
from typing import Any


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

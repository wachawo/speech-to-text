#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A batch that runs out of GPU memory is decoded in halves instead of failing every request in it."""

import importlib.util
import os
import queue
import threading

import pytest

from libs import batching, fast_whisper

# What CTranslate2 raised on a shared card, word for word, and torch's own message.
CT2_OUT_OF_MEMORY = "CUDA failed with error out of memory"
CT2_PARALLEL_FOR = "parallel_for failed: cudaErrorInvalidDevice: invalid device ordinal"
TORCH_OUT_OF_MEMORY = "CUDA out of memory. Tried to allocate 2.00 GiB"

PARAKEET_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "libs", "parakeet.py")


def build_items(count):
    """Items as an engine holds them, before any decode."""
    return [{"id": number, "frames": 100, "result": None, "error": None} for number in range(count)]


def build_decoder(limit, message=CT2_OUT_OF_MEMORY):
    """A decode that fails like the GPU above `limit` items and records every batch size it was given."""
    sizes = []

    def decode(model, batch):
        """Set every item its id as the result, or fail the whole batch when it is too large."""
        sizes.append(len(batch))
        if len(batch) > limit:
            raise RuntimeError(message)
        for item in batch:
            item["result"] = {"text": f"phrase {item['id']}"}

    return decode, sizes


@pytest.mark.parametrize("message", [CT2_OUT_OF_MEMORY, CT2_PARALLEL_FOR, TORCH_OUT_OF_MEMORY])
def test_a_batch_out_of_memory_is_decoded_in_halves(message):
    """32 that do not fit become halves that do, and every request still gets its own result."""
    items = build_items(32)
    decode, sizes = build_decoder(limit=8, message=message)
    batching.decode_in_halves(items, decode, model=None)
    assert [item["result"]["text"] for item in items] == [f"phrase {number}" for number in range(32)]
    assert all(item["error"] is None for item in items)
    assert sizes == [32, 16, 8, 8, 16, 8, 8]


def test_the_cache_is_released_before_the_halves_run():
    """Whatever the failed attempt left cached is freed first, once per split."""
    releases = []
    decode, unused_sizes = build_decoder(limit=8)
    batching.decode_in_halves(build_items(32), decode, model=None, release=lambda: releases.append(1))
    assert len(releases) == 3


def test_an_item_that_does_not_fit_alone_fails_alone():
    """Splitting stops at one item, and only the item that cannot fit gets the error."""
    items = build_items(4)

    def decode(model, batch):
        """Item 2 never fits; anything with it in the batch fails."""
        if any(item["id"] == 2 for item in batch):
            raise RuntimeError(CT2_OUT_OF_MEMORY)
        for item in batch:
            item["result"] = {"text": "ok"}

    batching.decode_in_halves(items, decode, model=None)
    assert [item["result"] is None for item in items] == [False, False, True, False]
    assert str(items[2]["error"]) == CT2_OUT_OF_MEMORY


def test_any_other_error_fails_the_batch_without_a_retry():
    """A bug is not a memory shortage: splitting would only run it five more times."""
    items = build_items(8)
    calls = []

    def decode(model, batch):
        """Fail as a broken decode does."""
        calls.append(len(batch))
        raise ValueError("bad input")

    batching.decode_in_halves(items, decode, model=None)
    assert calls == [8]
    assert all(isinstance(item["error"], ValueError) for item in items)


def test_items_decoded_before_the_failure_are_not_decoded_again():
    """Only the items left without a result go into the halves."""
    items = build_items(4)
    items[0]["result"] = {"text": "already"}
    sizes = []

    def decode(model, batch):
        """Fail on the full batch, then decode what is left."""
        sizes.append([item["id"] for item in batch])
        if len(batch) == 4:
            raise RuntimeError(CT2_OUT_OF_MEMORY)
        for item in batch:
            item["result"] = {"text": "ok"}

    batching.decode_in_halves(items, decode, model=None)
    assert sizes == [[0, 1, 2, 3], [1], [2, 3]]
    assert items[0]["result"] == {"text": "already"}


def test_faster_whisper_answers_every_request_of_a_batch_that_ran_out_of_memory(monkeypatch):
    """Through the engine: 32 requests waiting at once, a GPU with room for 8 of them, 32 answers."""
    decode, sizes = build_decoder(limit=8)

    def decode_window_batch(model, batch):
        """faster-whisper's batched window decode, failing above 8 like the shared card did."""
        decode(model, batch)
        for item in batch:
            item["result"] = {"language": "en", "segments": [], "text": item["result"]["text"]}

    monkeypatch.setattr(fast_whisper, "decode_window_batch", decode_window_batch)
    engine = {"name": "test", "model": None, "requests": queue.Queue()}
    results = {}

    def submit(number):
        """One request, as get_stt_result submits it."""
        results[number] = batching.submit_request(engine, {"id": number, "frames": 100})

    threads = [threading.Thread(target=submit, args=(number,)) for number in range(32)]
    for thread in threads:
        thread.start()
    while engine["requests"].qsize() < 32:
        threading.Event().wait(0.01)
    batch = batching.take_batch(engine["requests"])
    try:
        fast_whisper.serve_batch(None, batch)
    finally:
        for item in batch:
            item["done"].set()
    for thread in threads:
        thread.join()
    assert sorted(results) == list(range(32))
    assert all(result["text"] == f"phrase {number}" for number, result in results.items())
    assert sizes[0] == 32


def test_parakeet_decodes_in_halves_and_releases_the_cache_after_every_batch(monkeypatch):
    """The real libs/parakeet.py, loaded past its stub: halves on a shortage, the cache freed at the end."""
    spec = importlib.util.spec_from_file_location("libs_parakeet_batching", PARAKEET_PATH)
    parakeet = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parakeet)
    decode, sizes = build_decoder(limit=8, message=TORCH_OUT_OF_MEMORY)
    releases = []
    monkeypatch.setattr(parakeet, "decode_batch", decode)
    monkeypatch.setattr(parakeet, "release_cache", lambda: releases.append(1))
    items = build_items(16)
    parakeet.serve_batch(None, items)
    assert all(item["result"] is not None and item["error"] is None for item in items)
    assert sizes == [16, 8, 8]
    # Once before the halves, once after the batch.
    assert len(releases) == 2

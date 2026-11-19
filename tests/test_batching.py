#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The engine thread batches what is waiting, and a batch out of GPU memory is decoded in halves."""

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

# Longest any engine test waits for another thread; a broken engine fails the test instead of hanging the suite.
WAIT_SECONDS = 10


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


def decode_ids(model, batch):
    """A serve_batch that answers every item with its own id."""
    for item in batch:
        item["result"] = {"text": f"phrase {item['id']}"}


def watch_arrivals(engine):
    """Count every item put on the engine's queue; returns the semaphore a test acquires once per item."""
    arrivals = threading.Semaphore(0)
    put_request = engine["requests"].put

    def put_and_count(item):
        """Queue the item as before, then say it is there."""
        put_request(item)
        arrivals.release()

    engine["requests"].put = put_and_count
    return arrivals


def submit_in_thread(engine, number, outcomes):
    """Submit one request from its own daemon thread, recording its result or the exception it raised."""

    def submit():
        """One caller, as a backend's get_stt_result is."""
        try:
            outcomes[number] = batching.submit_request(engine, {"id": number})
        except Exception as exc:
            outcomes[number] = exc

    thread = threading.Thread(target=submit, daemon=True)
    thread.start()
    return thread


def join_threads(threads):
    """Wait for every caller to get its answer, failing rather than hanging when one never does."""
    for thread in threads:
        thread.join(WAIT_SECONDS)
        assert not thread.is_alive()


def run_while_engine_is_busy(serve_batch, count):
    """Start a real engine, hold it inside a first batch until `count` more requests are queued, then let it go.

    The opening request has id "opener" and is answered by the engine's first batch; the others
    have ids 0 to count - 1 and go to `serve_batch`. Returns the engine, every caller's result or
    exception by id, and the ids of each batch in the order the engine decoded them.
    """
    batches = []
    started = threading.Event()
    release = threading.Event()

    def serve(model, batch):
        """Hold the first batch until the test releases it; hand every later one to the test's decode."""
        batches.append([item["id"] for item in batch])
        if len(batches) > 1:
            serve_batch(model, batch)
            return
        started.set()
        assert release.wait(WAIT_SECONDS)
        decode_ids(model, batch)

    engine = batching.start_engine("model", "test-engine", serve)
    arrivals = watch_arrivals(engine)
    outcomes = {}
    threads = [submit_in_thread(engine, "opener", outcomes)]
    assert started.wait(WAIT_SECONDS)
    threads += [submit_in_thread(engine, number, outcomes) for number in range(count)]
    # The opener's own put counts too.
    for unused_number in range(count + 1):
        assert arrivals.acquire(timeout=WAIT_SECONDS)
    release.set()
    join_threads(threads)
    return engine, outcomes, batches


def test_take_batch_returns_everything_queued():
    """Whatever is waiting goes into one batch, in the order it arrived, and the queue is left empty."""
    requests = queue.Queue()
    for item in build_items(5):
        requests.put(item)
    batch = batching.take_batch(requests)
    assert [item["id"] for item in batch] == [0, 1, 2, 3, 4]
    assert requests.empty()


def test_a_lone_request_is_decoded_by_the_engine_thread():
    """One request goes at once, on the engine's thread, with the engine's model, and gets its result back."""
    seen = []

    def serve(model, batch):
        """Record who decoded what, then answer."""
        seen.append((threading.current_thread().name, model, len(batch)))
        decode_ids(model, batch)

    engine = batching.start_engine("model", "test-engine", serve)
    outcomes = {}
    join_threads([submit_in_thread(engine, 7, outcomes)])
    assert outcomes == {7: {"text": "phrase 7"}}
    assert seen == [("test-engine", "model", 1)]


def test_requests_waiting_for_the_engine_are_taken_as_one_batch():
    """Everything that arrived while a batch ran is the next batch, and each caller gets its own result."""
    unused_engine, outcomes, batches = run_while_engine_is_busy(decode_ids, count=8)
    assert batches[0] == ["opener"]
    assert len(batches) == 2
    assert sorted(batches[1]) == list(range(8))
    assert outcomes == {number: {"text": f"phrase {number}"} for number in ["opener", *range(8)]}


def test_a_failed_batch_raises_in_every_caller_left_without_a_result():
    """The exception reaches each request the decode did not answer; one it had answered keeps its result."""
    failure = ValueError("bad input")

    def serve(model, batch):
        """Answer request 0, then fail as a broken decode does."""
        for item in batch:
            if item["id"] == 0:
                item["result"] = {"text": "phrase 0"}
        raise failure

    unused_engine, outcomes, batches = run_while_engine_is_busy(serve, count=4)
    assert sorted(batches[1]) == [0, 1, 2, 3]
    assert outcomes[0] == {"text": "phrase 0"}
    assert [outcomes[number] for number in (1, 2, 3)] == [failure, failure, failure]
    assert outcomes["opener"] == {"text": "phrase opener"}


def test_the_engine_thread_survives_a_failed_batch():
    """A batch that raised does not end the thread: the next request is decoded as usual."""
    failed = []

    def serve(model, batch):
        """Fail the first batch it is given, decode every later one."""
        if not failed:
            failed.append(len(batch))
            raise RuntimeError("decode failed")
        decode_ids(model, batch)

    engine, outcomes, unused_batches = run_while_engine_is_busy(serve, count=2)
    assert failed == [2]
    assert all(isinstance(outcomes[number], RuntimeError) for number in (0, 1))
    join_threads([submit_in_thread(engine, 9, outcomes)])
    assert outcomes[9] == {"text": "phrase 9"}

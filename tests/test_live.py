#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""libs/live.py driven as a raw ASGI app: a queue of incoming messages, a list of sent ones, no sockets."""

import asyncio
import json
import logging
import queue
import re
import threading
import types

import numpy as np
import pytest

# Local imports
from libs import config, live, model_pool, stream, url_source
from tests.helpers import make_silence, make_tone

RATE = stream.SAMPLE_RATE
CHUNK_SECONDS = 0.1
REQUEST_ID_RE = re.compile(r"^[0-9a-f]{12}$")
STREAM_URL = "http://example.com/live"


def answer_hello(bio, model=None, device=None, language=None):
    """Stand in for the transcriber: one half-second phrase at the start of every utterance."""
    return [{"start": 0.0, "end": 0.5, "text": " hello"}]


@pytest.fixture(autouse=True)
def live_env(monkeypatch, stt_module):
    """A one-slot model pool, no auth, diarization off, the whisper stub, and no URL session running."""
    pool: queue.Queue = queue.Queue()
    pool.put("model-sentinel")
    monkeypatch.setattr(model_pool, "MODEL_POOL", pool)
    monkeypatch.setattr(model_pool, "DIARIZER_POOL", queue.Queue())
    monkeypatch.setattr(model_pool, "DIARIZERS_LOADED", 0)
    monkeypatch.setattr(config, "STT_TOKENS", set())
    monkeypatch.setattr(config, "DIARIZE_ENABLED", False)
    monkeypatch.setattr(config, "STT_BACKEND", "whisper")
    monkeypatch.setattr(config, "CORS_ORIGINS", ["*"])
    monkeypatch.setattr(url_source, "URL_SESSIONS", 0)
    monkeypatch.setattr(stt_module, "get_stt_segments", answer_hello)
    return pool


@pytest.fixture
def sessions(monkeypatch):
    """Every session handle_stream creates, so a test can look inside one while it runs."""
    created: list[dict] = []
    real_new_session = live.new_session

    def capture_session(options, request_id):
        """Create the session as usual and keep a reference to it."""
        session = real_new_session(options, request_id)
        created.append(session)
        return session

    monkeypatch.setattr(live, "new_session", capture_session)
    return created


def build_connect() -> dict:
    """The handshake message the server hands the app first."""
    return {"type": "websocket.connect"}


def build_text(payload) -> dict:
    """A text frame carrying the JSON encoding of `payload`."""
    return {"type": "websocket.receive", "text": json.dumps(payload)}


def build_start(**options) -> dict:
    """The client's start message with the given options."""
    return build_text({"type": "start", **options})


def build_stop() -> dict:
    """The client's stop message."""
    return build_text({"type": "stop"})


def build_disconnect() -> dict:
    """The message the server hands the app when the client goes away."""
    return {"type": "websocket.disconnect", "code": 1001}


def build_audio(samples: np.ndarray) -> list[dict]:
    """Binary frames of 100 ms each carrying the samples as little-endian int16."""
    step = int(CHUNK_SECONDS * RATE)
    data = samples.astype("<i2")
    return [{"type": "websocket.receive", "bytes": data[start : start + step].tobytes()} for start in range(0, data.size, step)]


def build_speech() -> np.ndarray:
    """One phrase between two silences, 2.5 s in all: exactly one utterance."""
    return np.concatenate([make_silence(0.5), make_tone(1.0), make_silence(1.0)])


async def drive_stream(messages: list[dict], headers=(), hold=None) -> dict:
    """Serve one /api/stream connection from a queue of incoming messages.

    `hold(message)`, when given, is awaited before each message is handed over, so a test can
    delay one until the session has reached some state. Returns what was sent and which tasks
    were still running once the handler returned.
    """
    incoming: asyncio.Queue = asyncio.Queue()
    for message in messages:
        incoming.put_nowait(message)
    sent: list[dict] = []

    async def receive():
        """Hand the handler the next incoming message, as the ASGI server would."""
        message = await incoming.get()
        if hold is not None:
            await hold(message)
        return message

    async def send(message):
        """Record what the handler sent."""
        sent.append(message)

    scope = {"type": "websocket", "path": live.STREAM_PATH, "headers": list(headers)}
    await asyncio.wait_for(live.handle_stream(scope, receive, send), timeout=10)
    leftover = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
    return {"sent": sent, "leftover": leftover}


def run_stream(messages: list[dict], headers=(), hold=None) -> dict:
    """Run drive_stream in a fresh event loop."""
    return asyncio.run(drive_stream(messages, headers=headers, hold=hold))


def read_events(result: dict) -> list[dict]:
    """The protocol messages the handler sent, decoded."""
    return [json.loads(message["text"]) for message in result["sent"] if message["type"] == "websocket.send"]


def read_closes(result: dict) -> list[int]:
    """The close codes the handler sent."""
    return [message["code"] for message in result["sent"] if message["type"] == "websocket.close"]


def select_events(result: dict, kind: str) -> list[dict]:
    """The decoded messages of one type."""
    return [event for event in read_events(result) if event["type"] == kind]


async def wait_until(condition, seconds: float = 5.0) -> None:
    """Poll a condition on the event loop until it holds; fail the test when it never does."""
    deadline = asyncio.get_running_loop().time() + seconds
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.005)


def assert_refused(result: dict, error: str, code: int, after_ready: bool = False) -> None:
    """The handshake was accepted, then exactly one error of this category and one close with this code."""
    assert result["sent"][0] == {"type": "websocket.accept"}
    events = read_events(result)
    if after_ready:
        assert events[0]["type"] == "ready"
    else:
        assert all(event["type"] == "error" for event in events)
    errors = select_events(result, "error")
    assert len(errors) == 1
    assert errors[0]["error"] == error
    assert set(errors[0]) == {"type", "error", "request_id"}
    assert REQUEST_ID_RE.match(errors[0]["request_id"])
    assert select_events(result, "done") == []
    assert read_closes(result) == [code]
    assert result["sent"][-1]["type"] == "websocket.close"
    assert result["leftover"] == []


def build_fake_ffmpeg(pcm: bytes = b"", stderr: bytes = b"", returncode: int | None = 0) -> types.SimpleNamespace:
    """A stand-in for ffmpeg's asyncio process. Needs a running loop.

    The PCM and stderr are there to read at once. With a return code the process has already
    exited; with None it keeps running, its stdout open, until killed.
    """
    process = types.SimpleNamespace(stdout=asyncio.StreamReader(), stderr=asyncio.StreamReader(), returncode=None, killed=False)
    exited = asyncio.Event()

    def finish_process(code: int) -> None:
        """Close both pipes and record the exit."""
        process.returncode = code
        process.stdout.feed_eof()
        process.stderr.feed_eof()
        exited.set()

    async def wait() -> int:
        """Wait for the exit, like asyncio.subprocess.Process.wait."""
        await exited.wait()
        return process.returncode

    def kill() -> None:
        """Kill the process, like asyncio.subprocess.Process.kill."""
        process.killed = True
        finish_process(-9)

    process.wait = wait
    process.kill = kill
    process.stdout.feed_data(pcm)
    process.stderr.feed_data(stderr)
    if returncode is not None:
        finish_process(returncode)
    return process


def install_fake_ffmpeg(monkeypatch, **fake_options) -> list:
    """Make url_source.start_ffmpeg hand out one fake process per call; returns the (url, process) pairs."""
    started: list = []

    async def start_fake_ffmpeg(url):
        """Stand in for url_source.start_ffmpeg."""
        process = build_fake_ffmpeg(**fake_options)
        started.append((url, process))
        return process

    monkeypatch.setattr(url_source, "start_ffmpeg", start_fake_ffmpeg)
    return started


def test_client_session_streams_segments_then_done(live_env):
    """ready, progress every second, a segment per phrase, done, and a normal close."""
    ignored = [build_text({"type": "ping"}), {"type": "websocket.receive", "text": "not json"}]
    messages = [build_connect(), build_start(), *build_audio(build_speech()), *ignored, build_stop()]
    result = run_stream(messages)

    assert result["sent"][0] == {"type": "websocket.accept"}
    events = read_events(result)
    assert events[0] == {
        "type": "ready",
        "sample_rate": RATE,
        "backend": "whisper",
        "language": None,
        "diarize": False,
        "source": "client",
    }
    assert [event["seconds"] for event in select_events(result, "progress")] == [1.0, 2.0]

    segments = select_events(result, "segment")
    assert len(segments) == 1
    segment = segments[0]
    assert set(segment) == {"type", "id", "start", "end", "text", "speaker", "overlap"}
    assert segment["id"] == 1
    assert segment["text"] == "hello"
    assert segment["speaker"] is None
    assert segment["overlap"] is False
    # The phrase starts where its utterance does: at the tone, less at most the pre-roll and a frame.
    assert 0.5 - stream.PRE_ROLL_SECONDS - stream.FRAME_SAMPLES / RATE <= segment["start"] <= 0.5
    assert segment["end"] == pytest.approx(segment["start"] + 0.5, abs=0.011)

    done = events[-1]
    assert done["type"] == "done"
    assert done["segments"] == 1
    assert done["seconds"] == 2.5
    assert done["elapsed"] >= 0
    assert read_closes(result) == [live.CLOSE_NORMAL]
    assert result["leftover"] == []
    assert live_env.qsize() == 1


@pytest.mark.parametrize("requested, resolved", [("Russian", "ru"), (" EN ", "en"), ("auto", "auto"), ("", None)])
def test_language_is_resolved_passed_on_and_announced(stt_module, monkeypatch, requested, resolved):
    """The start message's language is resolved against the backend, announced, and handed to the transcriber."""
    languages = []

    def record_language(bio, model=None, device=None, language=None):
        """Record the language the transcriber is asked for."""
        languages.append(language)
        return answer_hello(bio)

    monkeypatch.setattr(stt_module, "get_stt_segments", record_language)
    result = run_stream([build_connect(), build_start(language=requested), *build_audio(build_speech()), build_stop()])
    assert read_events(result)[0]["language"] == resolved
    assert languages == [resolved]
    assert read_closes(result) == [live.CLOSE_NORMAL]


def test_no_start_message_in_time_is_refused(monkeypatch):
    """A client that connects and says nothing is not waited for."""
    monkeypatch.setattr(live, "START_TIMEOUT", 0.05)
    assert_refused(run_stream([build_connect()]), "Invalid start message", live.CLOSE_UNSUPPORTED)


@pytest.mark.parametrize(
    "first",
    [
        build_stop(),
        {"type": "websocket.receive", "bytes": b"\x00\x00"},
        {"type": "websocket.receive", "text": "hello"},
        build_text([1, 2]),
        build_text({"type": "begin"}),
        build_start(source="file"),
        build_start(language=123),
    ],
    ids=["stop", "audio", "not-json", "json-list", "wrong-type", "unknown-source", "language-not-a-string"],
)
def test_a_first_message_that_is_not_a_valid_start_is_refused(first):
    """Anything but a well-formed start message ends the session before it begins."""
    assert_refused(run_stream([build_connect(), first]), "Invalid start message", live.CLOSE_UNSUPPORTED)


@pytest.mark.parametrize(
    "start, headers",
    [
        (build_start(), []),
        (build_start(token="wrong"), []),
        (build_start(), [(b"authorization", b"Bearer wrong")]),
        (build_start(), [(b"authorization", b"Basic secret")]),
    ],
    ids=["no-token", "wrong-token", "wrong-header", "not-bearer"],
)
def test_a_bad_token_is_refused(monkeypatch, start, headers):
    """With STT_TOKENS set, a session needs a valid token."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    assert_refused(run_stream([build_connect(), start], headers=headers), "Unauthorized", live.CLOSE_POLICY)


@pytest.mark.parametrize(
    "start, headers",
    [(build_start(token="secret"), []), (build_start(), [(b"Authorization", b"Bearer secret")])],
    ids=["in-start-message", "in-header"],
)
def test_a_valid_token_is_accepted_from_the_message_or_the_header(monkeypatch, start, headers):
    """Browsers cannot set headers on a websocket, so the start message may carry the token instead."""
    monkeypatch.setattr(config, "STT_TOKENS", {"secret"})
    result = run_stream([build_connect(), start, build_stop()], headers=headers)
    assert [event["type"] for event in read_events(result)] == ["ready", "done"]
    assert read_closes(result) == [live.CLOSE_NORMAL]


def test_an_unknown_language_is_refused():
    """A language the backend does not know is refused up front, not failed inside the model."""
    assert_refused(run_stream([build_connect(), build_start(language="zz")]), "Invalid language", live.CLOSE_UNSUPPORTED)


def test_diarize_is_refused_while_disabled():
    """Asking for speakers on a server without diarization is refused, not silently ignored."""
    result = run_stream([build_connect(), build_start(diarize=True)])
    assert_refused(result, "Diarization disabled", live.CLOSE_TRY_LATER)


def test_diarize_is_refused_when_no_diarizer_loaded(monkeypatch):
    """Diarization switched on but never loaded is a different answer from switched off."""
    monkeypatch.setattr(config, "DIARIZE_ENABLED", True)
    result = run_stream([build_connect(), build_start(diarize=True)])
    assert_refused(result, "Diarization unavailable", live.CLOSE_TRY_LATER)


def test_an_odd_length_audio_frame_is_refused():
    """A frame that is not whole 16-bit samples is not audio in the stream's format."""
    result = run_stream([build_connect(), build_start(), {"type": "websocket.receive", "bytes": b"\x01\x02\x03"}])
    assert_refused(result, "Invalid audio frame", live.CLOSE_UNSUPPORTED, after_ready=True)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "srt://relay.example.com:9000?mode=listener", None, ""])
def test_a_malformed_url_is_refused(monkeypatch, url):
    """A URL source that is not an outbound network address never reaches ffmpeg."""
    started = install_fake_ffmpeg(monkeypatch)
    result = run_stream([build_connect(), build_start(source="url", url=url)])
    assert_refused(result, "Invalid stream URL", live.CLOSE_UNSUPPORTED)
    assert started == []
    assert url_source.URL_SESSIONS == 0


def test_a_url_from_a_foreign_origin_is_forbidden(monkeypatch):
    """A page on another site cannot make this server fetch an address, and claims no slot trying."""
    started = install_fake_ffmpeg(monkeypatch)
    headers = [(b"origin", b"https://evil.example"), (b"host", b"stt.example.com")]
    result = run_stream([build_connect(), build_start(source="url", url=STREAM_URL)], headers=headers)
    assert_refused(result, "Forbidden", live.CLOSE_POLICY)
    assert started == []
    assert url_source.URL_SESSIONS == 0


def test_a_fifth_url_session_is_refused(monkeypatch):
    """With every URL slot taken, the next URL session is refused and the count is left alone."""
    started = install_fake_ffmpeg(monkeypatch)
    monkeypatch.setattr(url_source, "URL_SESSIONS", url_source.MAX_URL_SESSIONS)
    result = run_stream([build_connect(), build_start(source="url", url=STREAM_URL)])
    assert_refused(result, "Service Unavailable", live.CLOSE_TRY_LATER)
    assert started == []
    assert url_source.URL_SESSIONS == url_source.MAX_URL_SESSIONS


def test_a_client_disconnect_ends_quietly():
    """A client that leaves gets no error and no close, and nothing of its session keeps running."""
    result = run_stream([build_connect(), build_start(), *build_audio(make_tone(0.5)), build_disconnect()])
    assert select_events(result, "error") == []
    assert read_closes(result) == []
    assert result["leftover"] == []


def test_a_disconnect_during_transcription_stops_the_session_and_the_model_comes_back(live_env, stt_module, monkeypatch):
    """Leaving while a phrase is in the model ends the session at once; the model still returns to the pool."""
    started = threading.Event()
    release = threading.Event()

    def transcribe_slowly(bio, model=None, device=None, language=None):
        """Block inside the model until the test lets go."""
        started.set()
        release.wait(timeout=5)
        return answer_hello(bio)

    monkeypatch.setattr(stt_module, "get_stt_segments", transcribe_slowly)

    async def hold_disconnect(message):
        """Deliver the disconnect only once the worker is inside the model."""
        if message["type"] == "websocket.disconnect":
            await wait_until(started.is_set)

    async def disconnect_mid_phrase():
        """Run the session, then let the abandoned model call finish."""
        messages = [build_connect(), build_start(), *build_audio(build_speech()), build_disconnect()]
        result = await drive_stream(messages, hold=hold_disconnect)
        release.set()
        return result

    result = asyncio.run(disconnect_mid_phrase())
    assert select_events(result, "error") == []
    assert select_events(result, "segment") == []
    assert read_closes(result) == []
    assert result["leftover"] == []
    assert live_env.get(timeout=5) == "model-sentinel"


def test_a_transcriber_that_raises_fails_the_session(live_env, stt_module, monkeypatch):
    """A model crash is one `Transcription failed` and an internal-error close, and the model is returned."""

    def fail_segments(bio, model=None, device=None, language=None):
        """Stand in for a transcriber that crashes."""
        raise RuntimeError("decoder exploded")

    monkeypatch.setattr(stt_module, "get_stt_segments", fail_segments)
    result = run_stream([build_connect(), build_start(), *build_audio(build_speech()), build_stop()])
    assert_refused(result, "Transcription failed", live.CLOSE_INTERNAL, after_ready=True)
    assert live_env.qsize() == 1


def test_a_transcriber_failure_mid_stream_stops_the_reader_too(stt_module, monkeypatch):
    """The worker failing while the client is still sending ends the session at once, reader included."""

    def fail_segments(bio, model=None, device=None, language=None):
        """Stand in for a transcriber that crashes."""
        raise RuntimeError("decoder exploded")

    monkeypatch.setattr(stt_module, "get_stt_segments", fail_segments)
    # No stop: the reader is still waiting for audio when the worker gives up.
    result = run_stream([build_connect(), build_start(), *build_audio(build_speech())])
    assert_refused(result, "Transcription failed", live.CLOSE_INTERNAL, after_ready=True)


def test_a_connection_that_is_not_a_handshake_is_left_alone():
    """Anything but websocket.connect first means there is no socket to accept or to answer on."""
    assert run_stream([build_disconnect()])["sent"] == []


def test_an_exhausted_pool_fails_the_session(monkeypatch):
    """No model freeing up in time is a try-again-later, not an internal error."""

    def raise_empty(timeout=None):
        """Stand in for a pool whose wait timed out."""
        raise queue.Empty

    monkeypatch.setattr(model_pool, "acquire_model", raise_empty)
    result = run_stream([build_connect(), build_start(), *build_audio(build_speech()), build_stop()])
    assert_refused(result, "Service Unavailable", live.CLOSE_TRY_LATER, after_ready=True)


def test_an_unexpected_failure_still_sends_one_error(monkeypatch):
    """Whatever escapes the session becomes the protocol's error and a close, never silence."""

    async def explode(session, receive, send, send_event):
        """Stand in for a session that fails in a way nobody planned for."""
        raise RuntimeError("unplanned")

    monkeypatch.setattr(live, "run_session", explode)
    result = run_stream([build_connect(), build_start()])
    assert_refused(result, "Internal Server Error", live.CLOSE_INTERNAL, after_ready=True)


def test_a_url_session_whose_ffmpeg_cannot_start_fails_and_frees_its_slot(monkeypatch):
    """ffmpeg missing or unrunnable is `Stream source failed`, a close, and the slot back."""

    async def refuse_to_start(url):
        """Stand in for a machine without ffmpeg."""
        raise OSError("No such file or directory: 'ffmpeg'")

    monkeypatch.setattr(url_source, "start_ffmpeg", refuse_to_start)
    result = run_stream([build_connect(), build_start(source="url", url=STREAM_URL)])
    assert read_events(result)[0]["source"] == "url"
    assert_refused(result, "Stream source failed", live.CLOSE_INTERNAL, after_ready=True)
    assert url_source.URL_SESSIONS == 0


def test_a_url_session_transcribes_until_ffmpeg_ends(live_env, monkeypatch):
    """ffmpeg's PCM goes through the same pipeline; its clean exit ends the session with done."""
    started = install_fake_ffmpeg(monkeypatch, pcm=build_speech().astype("<i2").tobytes(), returncode=0)
    result = run_stream([build_connect(), build_start(source="url", url="HTTP://example.com/live")])
    assert [url for url, unused_process in started] == [STREAM_URL]
    assert read_events(result)[0]["source"] == "url"
    assert [event["text"] for event in select_events(result, "segment")] == ["hello"]
    assert select_events(result, "done")[0]["seconds"] == 2.5
    assert read_closes(result) == [live.CLOSE_NORMAL]
    assert started[0][1].killed is False
    assert url_source.URL_SESSIONS == 0
    assert result["leftover"] == []
    assert live_env.qsize() == 1


def test_a_client_disconnect_kills_a_running_ffmpeg(monkeypatch, sessions):
    """A client that leaves a URL session gets no error, and ffmpeg does not outlive it."""
    speech = build_speech()
    started = install_fake_ffmpeg(monkeypatch, pcm=speech.astype("<i2").tobytes(), returncode=None)

    async def hold_disconnect(message):
        """Deliver the disconnect only once ffmpeg's audio is in the session."""
        if message["type"] == "websocket.disconnect":
            await wait_until(lambda: bool(sessions) and sessions[0]["buffer"]["total"] == speech.size)

    messages = [build_connect(), build_start(source="url", url=STREAM_URL), build_disconnect()]
    result = run_stream(messages, hold=hold_disconnect)
    assert select_events(result, "error") == []
    assert read_closes(result) == []
    assert started[0][1].killed is True
    assert url_source.URL_SESSIONS == 0
    assert result["leftover"] == []


def test_a_client_stop_kills_a_running_ffmpeg(monkeypatch, sessions):
    """stop ends a live source: what arrived is finished, ffmpeg is killed, and the slot is freed."""
    speech = build_speech()
    started = install_fake_ffmpeg(monkeypatch, pcm=speech.astype("<i2").tobytes(), returncode=None)

    async def hold_stop(message):
        """Deliver stop only once all of ffmpeg's audio is in the session."""
        if message == build_stop():
            await wait_until(lambda: bool(sessions) and sessions[0]["buffer"]["total"] == speech.size)

    result = run_stream([build_connect(), build_start(source="url", url=STREAM_URL), build_stop()], hold=hold_stop)
    assert [event["text"] for event in select_events(result, "segment")] == ["hello"]
    assert select_events(result, "done")[0]["segments"] == 1
    assert read_closes(result) == [live.CLOSE_NORMAL]
    assert started[0][1].killed is True
    assert url_source.URL_SESSIONS == 0
    assert result["leftover"] == []


def test_a_source_that_fails_before_any_audio_is_reported_with_the_url_redacted(monkeypatch, caplog):
    """ffmpeg exiting non-zero with no audio is `Stream source failed`; its complaint is logged without secrets."""
    url = "http://user:pw@example.com/live?token=secret"
    install_fake_ffmpeg(monkeypatch, stderr=f"{url}: Connection refused\n".encode(), returncode=1)
    caplog.set_level(logging.INFO, logger="libs.live")
    result = run_stream([build_connect(), build_start(source="url", url=url)])
    assert_refused(result, "Stream source failed", live.CLOSE_INTERNAL, after_ready=True)
    assert url_source.URL_SESSIONS == 0
    assert "http://example.com/live: Connection refused" in caplog.text
    assert "secret" not in caplog.text
    assert "pw@" not in caplog.text


def test_find_keep_from_between_utterances_keeps_the_pre_roll():
    """With nothing in progress, only the pre-roll behind the detector is still needed."""
    session = live.new_session({"language": None, "diarize": False, "url": None}, "abc")
    session["segmenter"]["position"] = 10 * RATE
    assert live.find_keep_from(session) == 10 * RATE - int(stream.PRE_ROLL_SECONDS * RATE)
    # Never back into the previous utterance, which is already done with.
    session["segmenter"]["cut_floor"] = 10 * RATE - 100
    assert live.find_keep_from(session) == 10 * RATE - 100


def test_find_keep_from_takes_the_earliest_need():
    """An utterance in progress, a queued one and an unfinished diarizer each hold samples back."""
    session = live.new_session({"language": None, "diarize": False, "url": None}, "abc")
    segmenter = session["segmenter"]
    segmenter.update(position=20 * RATE, in_speech=True, speech_start=15 * RATE)
    assert live.find_keep_from(session) == 15 * RATE
    session["pending"].append({"start": 12 * RATE, "end": 14 * RATE})
    assert live.find_keep_from(session) == 12 * RATE
    session["diarization"] = {"finished": False, "next_start": 9 * RATE}
    assert live.find_keep_from(session) == 9 * RATE
    # A diarizer that has finished holds nothing back.
    session["diarization"]["finished"] = True
    assert live.find_keep_from(session) == 12 * RATE


def test_a_long_silence_is_trimmed_while_idle(monkeypatch, sessions):
    """With nothing to transcribe the worker catches up and drops audio nobody needs any more."""
    monkeypatch.setattr(live, "IDLE_SECONDS", 0.02)
    silence = make_silence(5.0)
    chunk = int(CHUNK_SECONDS * RATE)

    async def hold_stop(message):
        """Deliver stop only once the idle worker has trimmed the buffer."""
        if message == build_stop():
            await wait_until(lambda: bool(sessions) and sessions[0]["buffer"]["base"] > 0)

    result = run_stream([build_connect(), build_start(), *build_audio(silence), build_stop()], hold=hold_stop)
    buffer = sessions[0]["buffer"]
    assert buffer["total"] == silence.size
    kept = buffer["total"] - buffer["base"]
    # What is left is the pre-roll, the frame the detector has not finished, and the chunk grain.
    assert kept <= int(stream.PRE_ROLL_SECONDS * RATE) + stream.FRAME_SAMPLES + chunk
    assert select_events(result, "segment") == []
    assert select_events(result, "done")[0]["seconds"] == 5.0
    assert read_closes(result) == [live.CLOSE_NORMAL]


def test_a_diarized_session_attributes_segments_from_the_turns_so_far(monkeypatch):
    """With diarize on, each utterance is diarized up to its end and its segments get speakers from that window."""
    monkeypatch.setattr(config, "DIARIZE_ENABLED", True)
    diarizers: queue.Queue = queue.Queue()
    diarizers.put("diarizer-sentinel")
    monkeypatch.setattr(model_pool, "DIARIZER_POOL", diarizers)
    state = {"finished": False, "next_start": 0}
    advanced = []
    windows = []

    def record_advance(diarization, buffer, until, final):
        """Stand in for stream.advance_diarization and record how far it was asked to go."""
        advanced.append((diarization, until, final))

    def answer_turns(diarization, start, end):
        """Speaker 1 throughout, with speaker 0 cutting in: the phrase belongs to 1 and is overlapped."""
        windows.append((diarization, start, end))
        return [{"speaker": 1, "start": 0.0, "end": 60.0}, {"speaker": 0, "start": start + 0.1, "end": start + 0.2}]

    monkeypatch.setattr(stream, "new_diarization", lambda: state)
    monkeypatch.setattr(stream, "advance_diarization", record_advance)
    monkeypatch.setattr(live, "diarize", types.SimpleNamespace(stream_turns=answer_turns))

    result = run_stream([build_connect(), build_start(diarize=True), *build_audio(build_speech()), build_stop()])
    assert read_events(result)[0]["diarize"] is True
    segments = select_events(result, "segment")
    assert [(segment["speaker"], segment["overlap"]) for segment in segments] == [(1, True)]
    assert len(windows) == 1
    window_state, window_start, window_end = windows[0]
    assert window_state is state
    assert window_start == segments[0]["start"]
    # Diarized as far as the end of the utterance the window covers, and no further.
    assert advanced and all(diarization is state for diarization, unused_until, unused_final in advanced)
    assert any(until / RATE == pytest.approx(window_end) for unused_state, until, unused_final in advanced)
    assert read_closes(result) == [live.CLOSE_NORMAL]


def test_idle_catch_up_diarizes_and_trims_no_further_than_the_diarizer_needs(monkeypatch, sessions):
    """While idle the diarizer is caught up to the audio received, and trimming stops at its next chunk."""
    monkeypatch.setattr(config, "DIARIZE_ENABLED", True)
    monkeypatch.setattr(live, "IDLE_SECONDS", 0.02)
    diarizers: queue.Queue = queue.Queue()
    diarizers.put("diarizer-sentinel")
    monkeypatch.setattr(model_pool, "DIARIZER_POOL", diarizers)
    state = {"finished": False, "next_start": 0}
    advanced = []

    def record_advance(diarization, buffer, until, final):
        """Stand in for stream.advance_diarization: the diarizer ends up needing the last second again."""
        advanced.append((until, final, buffer["total"]))
        diarization["next_start"] = max(0, until - RATE)

    monkeypatch.setattr(stream, "new_diarization", lambda: state)
    monkeypatch.setattr(stream, "advance_diarization", record_advance)
    silence = make_silence(5.0)

    async def hold_stop(message):
        """Deliver stop only once an idle catch-up has diarized everything and trimmed."""
        if message == build_stop():
            await wait_until(lambda: bool(advanced) and bool(sessions) and sessions[0]["buffer"]["base"] > 0)

    result = run_stream([build_connect(), build_start(diarize=True), *build_audio(silence), build_stop()], hold=hold_stop)
    # Caught up to everything received, and not as the end of the stream.
    assert advanced[0] == (silence.size, False, silence.size)
    base = sessions[0]["buffer"]["base"]
    assert 0 < base <= silence.size - RATE
    assert select_events(result, "done")[0]["seconds"] == 5.0

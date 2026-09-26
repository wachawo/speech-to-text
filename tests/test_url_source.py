#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""libs/url_source.py: what a URL source may be, how it is logged, who may ask for one, and ffmpeg's I/O."""

import asyncio
import functools
import http.server
import shutil
import threading
import types
from collections import deque

import numpy as np
import pytest

# Local imports
from libs import config, stream, url_source
from tests.helpers import make_tone

ACCEPTED_URLS = [
    ("http://example.com/live", "http://example.com/live"),
    ("HTTPS://Example.COM/Live.m3u8", "https://Example.COM/Live.m3u8"),
    ("  rtmp://media.example.com/app/key \n", "rtmp://media.example.com/app/key"),
    ("\trtsp://cam.example.com:554/stream1", "rtsp://cam.example.com:554/stream1"),
    ("rtmps://live.example.com:443/app", "rtmps://live.example.com:443/app"),
    ("srt://relay.example.com:9000", "srt://relay.example.com:9000"),
    ("srt://relay.example.com:9000?mode=caller&latency=200", "srt://relay.example.com:9000?mode=caller&latency=200"),
    ("SRT://relay.example.com:9000?MODE=Caller", "srt://relay.example.com:9000?MODE=Caller"),
    ("http://[::1]:8080/radio", "http://[::1]:8080/radio"),
    ("http://192.168.0.10/radio", "http://192.168.0.10/radio"),
    ("http://user:secret@example.com/a?token=x#frag", "http://user:secret@example.com/a?token=x#frag"),
]

REFUSED_URLS = [
    # Empty
    "",
    "   ",
    "\n",
    # Schemes that are not network media protocols, or no scheme at all
    "file:///etc/passwd",
    "FILE:///etc/passwd",
    "ftp://example.com/a.mp3",
    "concat:http://example.com/a|http://example.com/b",
    "data:audio/wav;base64,AAAA",
    "pipe:0",
    "udp://example.com:1234",
    "tcp://example.com:1234",
    "rtp://example.com:1234",
    "hls+http://example.com/a.m3u8",
    "crypto+http://example.com/a",
    "example.com/live",
    "//example.com/live",
    # Whitespace and control characters inside, which urlsplit would drop and ffmpeg would keep
    "http://exa mple.com/",
    "http://example.com/a b",
    "http://example.com/\x00",
    "\x00http://example.com/",
    "http://example.com/a\rb",
    "http://example.com/a\nfile:///etc/passwd",
    "http://example.com/a\tb",
    "http://exam\tple.com/",
    "http://example.com/\x7f",
    "http://example.com/\x1b[0m",
    # Malformed hosts and ports
    "http://[::1/x",
    "http://[notanip]/",
    "http://::1/",
    "http://example.com:99999/",
    "http://example.com:abc/",
    "http://example.com:-1/",
    # No host
    "http:///path",
    "http://:8080/",
    "http://user@/x",
    "http:example.com",
    "srt://?mode=caller",
    # SRT modes that bind a port on the server
    "srt://relay.example.com:9000?mode=listener",
    "srt://relay.example.com:9000?mode=rendezvous",
    "srt://relay.example.com:9000?mode=LISTENER",
    "srt://relay.example.com:9000?Mode=listener",
    "srt://relay.example.com:9000?mode=caller&mode=listener",
    "srt://relay.example.com:9000?mode=",
    # `listen` on any scheme, with any value
    "http://example.com/?listen=1",
    "https://example.com/a?LISTEN=1",
    "rtmp://example.com/app?listen",
    "rtsp://example.com/s?listen=0",
    "srt://relay.example.com:9000?listen=1",
    "rtmps://example.com/app?a=1&listen=1",
]

REDACTIONS = [
    ("http://user:secret@example.com:8080/live/stream?token=abc#frag", "http://example.com:8080/live/stream"),
    ("rtsp://admin:pw@[fe80::1]:554/cam?x=1", "rtsp://[fe80::1]:554/cam"),
    ("https://example.com/a.m3u8", "https://example.com/a.m3u8"),
    ("srt://relay.example.com:9000?passphrase=hunter2&mode=caller", "srt://relay.example.com:9000"),
    ("http://[::1]/radio", "http://[::1]/radio"),
]

ORIGIN_CASES = [
    # (headers, CORS_ORIGINS, allowed)
    ([(b"host", b"stt.example.com")], ["*"], True),
    ([(b"origin", b"http://stt.example.com:5053"), (b"host", b"stt.example.com:5051")], ["*"], True),
    ([(b"Origin", b"https://stt.example.com"), (b"Host", b"stt.example.com")], ["*"], True),
    ([(b"origin", b"http://STT.Example.com"), (b"host", b"stt.example.com")], ["*"], True),
    ([(b"origin", b"https://evil.example"), (b"host", b"stt.example.com")], ["*"], False),
    ([(b"origin", b"https://app.example.org"), (b"host", b"stt.example.com")], ["https://app.example.org"], True),
    ([(b"origin", b"https://app.example.org:8443"), (b"host", b"stt.example.com")], ["https://app.example.org"], False),
    ([(b"origin", b"http://[::1"), (b"host", b"stt.example.com")], ["*"], False),
    ([(b"origin", b"null"), (b"host", b"stt.example.com")], ["*"], False),
    ([(b"origin", b"http://stt.example.com")], ["*"], False),
    ([(b"origin", b"http://stt.example.com"), (b"host", b"[::1")], ["*"], False),
]


@pytest.fixture
def free_slots(monkeypatch):
    """Start every test from zero URL sessions, and put the real count back afterwards."""
    monkeypatch.setattr(url_source, "URL_SESSIONS", 0)


def build_fake_process() -> types.SimpleNamespace:
    """A stand-in for an asyncio subprocess: only the two pipes this module reads. Needs a running loop."""
    return types.SimpleNamespace(stdout=asyncio.StreamReader(), stderr=asyncio.StreamReader())


async def drain_fed_stderr(chunks: list[bytes], url: str) -> list[str]:
    """Feed ffmpeg's stderr with the given bytes, close it, and return the tail drain_stderr kept."""
    process = build_fake_process()
    for chunk in chunks:
        process.stderr.feed_data(chunk)
    process.stderr.feed_eof()
    tail: deque = deque(maxlen=url_source.STDERR_LINES)
    await url_source.drain_stderr(process, url, tail)
    return list(tail)


async def read_fed_pcm(data: bytes) -> list[bytes]:
    """Feed ffmpeg's stdout with the given bytes, close it, and collect read_pcm results through the first b""."""
    process = build_fake_process()
    process.stdout.feed_data(data)
    process.stdout.feed_eof()
    reads = []
    while True:
        chunk = await url_source.read_pcm(process)
        reads.append(chunk)
        if not chunk:
            return reads


@pytest.mark.parametrize("raw, expected", ACCEPTED_URLS)
def test_normalize_accepts_network_sources(raw, expected):
    """A network URL comes back trimmed, with only its scheme lower-cased."""
    assert url_source.normalize_url(raw) == expected


@pytest.mark.parametrize("raw", REFUSED_URLS)
def test_normalize_refuses_everything_else(raw):
    """Anything that is not a plain outbound network source is refused, never repaired."""
    assert url_source.normalize_url(raw) is None


@pytest.mark.parametrize("value", [None, 42, b"http://example.com/", ["http://example.com/"], {"url": "http://example.com/"}])
def test_normalize_refuses_non_strings(value):
    """Whatever JSON the client sent in place of a string is refused."""
    assert url_source.normalize_url(value) is None


@pytest.mark.parametrize("raw", ["srt://0.0.0.0:9000#?mode=listener", "srt://relay.example.com:9000#?mode=rendezvous"])
def test_normalize_refuses_an_srt_mode_hidden_in_the_fragment(raw):
    """ffmpeg takes SRT options from the first `?` anywhere in the URL, so a fragment can carry them too."""
    assert url_source.normalize_url(raw) is None


@pytest.mark.parametrize("raw, expected", REDACTIONS)
def test_redact_url_drops_credentials_query_and_fragment(raw, expected):
    """The logged form keeps scheme, host, port and path, and nothing that may be a secret."""
    assert url_source.redact_url(raw) == expected


@pytest.mark.parametrize("headers, cors_origins, allowed", ORIGIN_CASES)
def test_is_allowed_origin(monkeypatch, headers, cors_origins, allowed):
    """Only a non-browser client, a page from this host (any port) or an explicitly listed origin passes."""
    monkeypatch.setattr(config, "CORS_ORIGINS", cors_origins)
    assert url_source.is_allowed_origin({"type": "websocket", "headers": headers}) is allowed


def test_slots_are_limited_and_given_back(free_slots):
    """MAX_URL_SESSIONS claims succeed, the next is refused, and a release frees one again."""
    assert all(url_source.claim_slot() for unused_index in range(url_source.MAX_URL_SESSIONS))
    assert url_source.URL_SESSIONS == url_source.MAX_URL_SESSIONS
    assert url_source.claim_slot() is False
    url_source.release_slot()
    assert url_source.claim_slot() is True
    assert url_source.claim_slot() is False


def test_release_never_goes_below_zero(free_slots):
    """An extra release cannot mint a slot that was never claimed."""
    url_source.release_slot()
    url_source.release_slot()
    assert url_source.URL_SESSIONS == 0
    assert all(url_source.claim_slot() for unused_index in range(url_source.MAX_URL_SESSIONS))
    assert url_source.claim_slot() is False


@pytest.mark.parametrize(
    "url, timeout_option, other_option",
    [
        ("rtsp://cam.example.com/stream", "-timeout", "-rw_timeout"),
        ("http://example.com/live", "-rw_timeout", "-timeout"),
        ("srt://relay.example.com:9000", "-rw_timeout", "-timeout"),
        ("rtmp://example.com/app", "-rw_timeout", "-timeout"),
    ],
)
def test_ffmpeg_command_picks_the_timeout_option_for_the_protocol(url, timeout_option, other_option):
    """RTSP takes -timeout and everything else -rw_timeout, as an input option before -i."""
    command = url_source.build_ffmpeg_command(url)
    assert other_option not in command
    position = command.index(timeout_option)
    assert command[position + 1] == str(url_source.FFMPEG_TIMEOUT_US)
    assert position < command.index("-i")


def test_ffmpeg_command_from_a_normalized_rtsp_url_gets_the_rtsp_timeout():
    """The upper-case scheme a user typed is lower-cased first, so the RTSP check still matches."""
    command = url_source.build_ffmpeg_command(url_source.normalize_url("RTSP://cam.example.com/stream"))
    assert "-timeout" in command
    assert "-rw_timeout" not in command


def test_ffmpeg_command_is_held_to_network_protocols_and_paced_reading():
    """Whitelist, burst-then-realtime pacing and raw PCM out; no -re, and the URL is the only input."""
    url = "http://example.com/live"
    command = url_source.build_ffmpeg_command(url)
    input_position = command.index("-i")
    assert command[input_position + 1] == url
    assert command.count("-i") == 1

    whitelist_position = command.index("-protocol_whitelist")
    assert whitelist_position < input_position
    protocols = command[whitelist_position + 1].split(",")
    assert protocols == url_source.FFMPEG_PROTOCOLS.split(",")
    for forbidden in ("file", "pipe", "concat", "data", "subfile", "fd"):
        assert forbidden not in protocols

    assert command[command.index("-readrate") + 1] == "1"
    assert command[command.index("-readrate_initial_burst") + 1] == str(url_source.READRATE_BURST_SECONDS)
    assert command.index("-readrate_initial_burst") < input_position
    assert "-re" not in command
    assert "-nostdin" in command

    output = command[input_position + 2 :]
    assert output == ["-vn", "-ac", "1", "-ar", str(stream.SAMPLE_RATE), "-f", "s16le", "pipe:1"]


def test_drain_stderr_keeps_lines_redacts_the_url_and_survives_a_huge_line():
    """Lines are kept in order with the URL redacted; a 70 KB line neither raises nor grows without bound."""
    url = "http://user:pw@example.com/live?token=secret"
    chunks = [
        b"first line\n",
        f"Error opening {url}: 404 Not Found\n".encode(),
        b"x" * 70000 + b"\n",
        b"\xff\xfe broken bytes\n",
        b"   \n",
        b"last words without a newline",
    ]
    tail = asyncio.run(drain_fed_stderr(chunks, url))
    assert tail[0] == "first line"
    assert tail[1] == "Error opening http://example.com/live: 404 Not Found"
    assert set(tail[2]) == {"x"}
    assert 0 < len(tail[2]) <= 2 * 4096
    assert "\ufffd" in tail[3]
    assert tail[4] == "last words without a newline"
    assert len(tail) == 5
    assert not any("secret" in line or "pw@" in line for line in tail)


def test_drain_stderr_redacts_a_url_split_across_two_reads():
    """A line is redacted once it is whole, so a URL cut in half by the 4096-byte read is still caught."""
    url = "srt://relay.example.com:9000?passphrase=hunter2"
    line = b"a" * 4080 + f" connecting to {url}\n".encode()
    tail = asyncio.run(drain_fed_stderr([line], url))
    assert tail == ["a" * 4080 + " connecting to srt://relay.example.com:9000"]


def test_drain_stderr_keeps_only_the_last_lines():
    """The tail is bounded by the deque the caller passes, however much ffmpeg complains."""
    lines = [f"complaint {number}\n".encode() for number in range(url_source.STDERR_LINES + 10)]
    tail = asyncio.run(drain_fed_stderr(lines, "http://example.com/live"))
    assert len(tail) == url_source.STDERR_LINES
    assert tail[-1] == f"complaint {url_source.STDERR_LINES + 9}"


def test_read_pcm_returns_whole_reads_then_the_remainder_then_nothing():
    """READ_BYTES at a time, a short read at the end of the stream, and b"" once it is over."""
    data = bytes(range(256)) * ((2 * url_source.READ_BYTES + 3) // 256 + 1)
    data = data[: 2 * url_source.READ_BYTES + 3]
    reads = asyncio.run(read_fed_pcm(data))
    assert [len(chunk) for chunk in reads] == [url_source.READ_BYTES, url_source.READ_BYTES, 3, 0]
    assert b"".join(reads) == data


def test_read_pcm_is_a_tenth_of_a_second():
    """One read is 100 ms of the stream format, so a session is fed at a steady, small grain."""
    assert url_source.READ_BYTES == stream.SAMPLE_RATE // 10 * stream.SAMPLE_WIDTH


async def decode_with_ffmpeg(url: str) -> tuple[bytes, int | None]:
    """Run the real ffmpeg command on the URL and return all the PCM it wrote and its exit code."""
    process = await url_source.start_ffmpeg(url)
    tail: deque = deque(maxlen=url_source.STDERR_LINES)
    drain = asyncio.create_task(url_source.drain_stderr(process, url, tail))
    pcm = b""
    while True:
        chunk = await url_source.read_pcm(process)
        if not chunk:
            break
        pcm += chunk
    returncode = await asyncio.wait_for(process.wait(), timeout=10)
    await drain
    return pcm, returncode


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs the ffmpeg binary")
def test_real_ffmpeg_accepts_the_command_and_decodes_a_local_http_source(tmp_path):
    """The argv is one the installed ffmpeg accepts, and a WAV served over local HTTP comes out sample-exact."""
    samples = make_tone(1.0)
    (tmp_path / "tone.wav").write_bytes(stream.encode_wav(samples).getvalue())
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/tone.wav"
        pcm, returncode = asyncio.run(decode_with_ffmpeg(url))
    finally:
        server.shutdown()
        server.server_close()
    assert returncode == 0
    assert np.array_equal(np.frombuffer(pcm, dtype="<i2"), samples)

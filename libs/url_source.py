#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audio from a network address for /api/stream: vet the URL, run ffmpeg on it, read its PCM.

A URL source makes the server fetch an address a client chose, so everything here leans towards
refusing: one normalised string is both what is checked and what ffmpeg is given, ffmpeg may use
network protocols only and never listen, a browser page may use it only from its own site, and
only a few such sessions run at once.
"""

import asyncio
import logging
from collections import deque
from typing import Any
from urllib.parse import parse_qs, urlsplit

# Local imports
from libs import config, stream

logger = logging.getLogger(__name__)

# What a URL source may be. Network media protocols only: ffmpeg also reads local files and a
# dozen pseudo-protocols (file:, concat:, data:, pipe:), and a playlist fetched over http can
# point at any of them, so the scheme is checked here and ffmpeg is held to a whitelist below.
URL_SCHEMES = ("http", "https", "rtmp", "rtmps", "rtsp", "srt")
FFMPEG_PROTOCOLS = "http,https,tls,tcp,udp,rtp,rtmp,rtmps,rtsp,srt,hls,crypto,httpproxy"

# How long ffmpeg may wait on a silent connection before giving up, in microseconds. RTSP is
# opened by a demuxer that takes `-timeout`, and ffmpeg aborts on an input option nobody used,
# so passing `-rw_timeout` there would fail every RTSP source before it read a byte.
FFMPEG_TIMEOUT_US = 15_000_000

# ffmpeg reads at the source's own rate after an initial burst: a live stream's backlog is taken
# at once instead of becoming permanent lag (plain `-re` paces the backlog too, measured 7-35 s
# behind a live HLS or Icecast source), and a finite file still arrives as a broadcast would.
READRATE_BURST_SECONDS = 60

# Bytes handed to the session at a time: 100 ms of 16 kHz mono 16-bit audio. A pipe read alone
# returns one packet, a few hundred bytes, and every chunk costs the pause detector a walk.
READ_BYTES = int(stream.SAMPLE_RATE * 0.1) * stream.SAMPLE_WIDTH

# ffmpeg's last lines of complaint, kept for the log when it fails.
STDERR_LINES = 20

# Each URL session is an ffmpeg process and an outbound connection; a handful is a demo, a
# hundred is a way to make the server attack something.
MAX_URL_SESSIONS = 4

URL_SESSIONS = 0


def normalize_url(url: Any) -> str | None:
    """The exact string ffmpeg will be given, or None when it is not an allowed network source.

    Surrounding whitespace is trimmed and the scheme lower-cased, because ffmpeg matches schemes
    case-sensitively. Anything else unusual is refused rather than repaired: urlsplit silently
    drops tabs and newlines that ffmpeg would keep, so validating a cleaned copy and running the
    raw one is how a URL passes the check and then does something else.
    """
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or any(ord(character) < 33 or ord(character) == 127 for character in url):
        return None
    try:
        parts = urlsplit(url)
        # Both properties raise ValueError on a malformed host or port.
        hostname, unused_port = parts.hostname, parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in URL_SCHEMES or not hostname or opens_listener(scheme, parts.query):
        return None
    return scheme + url[len(parts.scheme) :]


def opens_listener(scheme: str, query: str) -> bool:
    """Whether the URL asks ffmpeg to wait for a connection instead of making one.

    SRT takes its mode from the query: `listener` or `rendezvous` would bind a port on the server
    and transcribe whatever anybody sends to it. A `listen` parameter is refused on every scheme.
    """
    params = {key.lower(): values for key, values in parse_qs(query, keep_blank_values=True).items()}
    if "listen" in params:
        return True
    if scheme == "srt":
        return any(value.lower() != "caller" for value in params.get("mode", []))
    return False


def redact_url(url: str) -> str:
    """The URL without credentials, query or fragment, for the log: those may carry secrets."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}{parts.path}"


def read_headers(scope: dict[str, Any]) -> dict[str, str]:
    """The handshake headers by lower-case name."""
    return {name.decode("latin-1").lower(): value.decode("latin-1") for name, value in scope.get("headers", [])}


def is_allowed_origin(scope: dict[str, Any]) -> bool:
    """Whether the page that opened the socket may make this server fetch a URL.

    Browsers apply no CORS to websockets, so without this any site a user on the network happens
    to open could drive the server into fetching internal addresses. A client that sends no Origin
    is not a browser page. Hosts are compared without ports, because nginx forwards `Host` without
    one; an origin listed explicitly in CORS_ORIGINS is allowed as well (`*` does not count).
    """
    headers = read_headers(scope)
    origin = headers.get("origin")
    if not origin:
        return True
    if origin in config.CORS_ORIGINS:
        return True
    try:
        origin_host = urlsplit(origin).hostname
        request_host = urlsplit("//" + headers.get("host", "")).hostname
    except ValueError:
        return False
    return bool(origin_host) and origin_host == request_host


def claim_slot() -> bool:
    """Take one of the URL session slots; False when all are in use."""
    global URL_SESSIONS
    if URL_SESSIONS >= MAX_URL_SESSIONS:
        return False
    URL_SESSIONS += 1
    return True


def release_slot() -> None:
    """Give a URL session slot back."""
    global URL_SESSIONS
    URL_SESSIONS = max(0, URL_SESSIONS - 1)


def build_ffmpeg_command(url: str) -> list[str]:
    """The ffmpeg argv that decodes the URL into the stream protocol's PCM on stdout."""
    timeout_option = "-timeout" if url.startswith("rtsp:") else "-rw_timeout"
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        FFMPEG_PROTOCOLS,
        timeout_option,
        str(FFMPEG_TIMEOUT_US),
        "-readrate",
        "1",
        "-readrate_initial_burst",
        str(READRATE_BURST_SECONDS),
        "-i",
        url,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(stream.SAMPLE_RATE),
        "-f",
        "s16le",
        "pipe:1",
    ]


async def start_ffmpeg(url: str):
    """Start ffmpeg on the URL. Raises OSError or ValueError when the process cannot start."""
    return await asyncio.create_subprocess_exec(
        *build_ffmpeg_command(url),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def drain_stderr(process, url: str, tail: deque) -> None:
    """Read ffmpeg's stderr as it comes, keeping the last lines with the URL redacted.

    Read concurrently, not after exit: a source that keeps ffmpeg complaining fills the pipe,
    ffmpeg then blocks writing to it and stops producing audio, and the session freezes silently.
    """
    redacted = redact_url(url)
    pending = b""
    while True:
        # Chunks rather than readline(): one line past the reader's 64 KiB limit would raise.
        data = await process.stderr.read(4096)
        if not data:
            break
        *lines, pending = (pending + data).split(b"\n")
        pending = pending[-4096:]
        tail.extend(line.decode("utf-8", "replace").strip().replace(url, redacted) for line in lines if line.strip())
    if pending.strip():
        tail.append(pending.decode("utf-8", "replace").strip().replace(url, redacted))


async def read_pcm(process) -> bytes:
    """The next READ_BYTES of PCM, fewer at the end of the stream, b"" once it is over."""
    try:
        return await process.stdout.readexactly(READ_BYTES)
    except asyncio.IncompleteReadError as exc:
        return exc.partial


def main():
    """No-op entry point: libs/live.py uses this module for URL sources."""
    pass


if __name__ == "__main__":
    main()

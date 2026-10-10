#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""STT_BACKEND reaches the endpoints: the Parakeet stub answers differently from the Whisper one."""

import io

import pytest

# Local imports
from libs import config
from tests.helpers import make_wav


def post_transcript(client, query=""):
    """POST a short silent WAV to /api/transcript as a multipart upload."""
    return client.post(
        "/api/transcript" + query,
        data={"file": (io.BytesIO(make_wav(duration_ms=50)), "meeting.wav")},
        content_type="multipart/form-data",
    )


def test_stt_under_parakeet_returns_the_parakeet_transcription(client, monkeypatch):
    """/api/stt transcribes with the configured backend, not always with Whisper."""
    monkeypatch.setattr(config, "STT_BACKEND", "parakeet")
    resp = client.post("/api/stt", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert resp.get_json()["text"] == "parakeet transcription"


def test_transcript_under_parakeet_returns_the_parakeet_segments(diarize_client, monkeypatch):
    """/api/transcript joins the configured backend's segments with the speaker turns."""
    monkeypatch.setattr(config, "STT_BACKEND", "parakeet")
    body = post_transcript(diarize_client).get_json()
    assert body["text"] == "parakeet first parakeet second"
    assert [segment["text"] for segment in body["segments"]] == ["parakeet first", "parakeet second"]
    assert [segment["speaker"] for segment in body["segments"]] == [0, 1]


@pytest.mark.parametrize(("backend", "status"), [("parakeet", 200), ("whisper", 400)])
def test_stt_unknown_language_depends_on_the_backend(client, monkeypatch, backend, status):
    """Parakeet takes no language and accepts any value; Whisper refuses one it does not know."""
    monkeypatch.setattr(config, "STT_BACKEND", backend)
    resp = client.post("/api/stt?language=zz", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == status


@pytest.mark.parametrize(("backend", "status"), [("parakeet", 200), ("whisper", 400)])
def test_transcript_unknown_language_depends_on_the_backend(diarize_client, monkeypatch, backend, status):
    """The same rule holds for the speaker transcript."""
    monkeypatch.setattr(config, "STT_BACKEND", backend)
    resp = post_transcript(diarize_client, "?language=zz")
    assert resp.status_code == status

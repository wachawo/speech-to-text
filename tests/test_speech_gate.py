#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The speech gate: segments nobody spoke are dropped from every transcript, the detector replaced."""

import io
import queue

import numpy as np
import pytest
import soundfile as sf

from libs import config, model_pool, speech_gate, stream
from tests.helpers import make_silence, make_tone, make_wav

RATE = stream.SAMPLE_RATE

# Whisper's literal Russian output, written as escapes: the subtitle credit "subtitles created by
# DimaTorzok" and its variants (made, made in capitals, prepared), the subtitle editor and
# proofreader credit, "to be continued...", and an ordinary sentence thanking DimaTorzok for the
# subtitles of a film, which only mentions the credit.
CREDIT_CREATED = " \u0421\u0443\u0431\u0442\u0438\u0442\u0440\u044b \u0441\u043e\u0437\u0434\u0430\u0432\u0430\u043b DimaTorzok"
CREDIT_MADE = "\u0421\u0443\u0431\u0442\u0438\u0442\u0440\u044b \u0441\u0434\u0435\u043b\u0430\u043b DimaTorzok."
CREDIT_SHOUTED = "  \u0421\u0423\u0411\u0422\u0418\u0422\u0420\u042b \u0414\u0415\u041b\u0410\u041b DIMATORZOK!"
CREDIT_PREPARED = (
    "\u0421\u0443\u0431\u0442\u0438\u0442\u0440\u044b \u043f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u0438\u043b DimaTorzok"
)
CREDIT_EDITORS = "\u0420\u0435\u0434\u0430\u043a\u0442\u043e\u0440 \u0441\u0443\u0431\u0442\u0438\u0442\u0440\u043e\u0432 \u0410.\u0421\u0435\u043c\u043a\u0438\u043d \u041a\u043e\u0440\u0440\u0435\u043a\u0442\u043e\u0440 \u0410.\u0415\u0433\u043e\u0440\u043e\u0432\u0430"
TO_BE_CONTINUED = (
    "\u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435 \u0441\u043b\u0435\u0434\u0443\u0435\u0442..."
)
THANKS_TO_DIMATORZOK = "\u0421\u043f\u0430\u0441\u0438\u0431\u043e DimaTorzok \u0437\u0430 \u0441\u0443\u0431\u0442\u0438\u0442\u0440\u044b \u043a \u044d\u0442\u043e\u043c\u0443 \u0444\u0438\u043b\u044c\u043c\u0443"


@pytest.fixture
def gate_on(monkeypatch):
    """Switch the gate on with a detector that reports whatever ranges the test sets."""
    detected: dict = {"ranges": [], "calls": 0}

    def fake_detect_speech(samples):
        """Stand in for Silero: count the call, return the ranges the test chose."""
        detected["calls"] += 1
        return detected["ranges"]

    monkeypatch.setattr(config, "SPEECH_GATE", True)
    monkeypatch.setattr(speech_gate, "detect_speech", fake_detect_speech)
    return detected


def segment(start: float, end: float, text: str) -> dict:
    """A transcriber segment."""
    return {"start": start, "end": end, "text": text}


@pytest.mark.parametrize(
    "text",
    [
        CREDIT_CREATED,
        CREDIT_MADE,
        CREDIT_SHOUTED,
        CREDIT_PREPARED,
        CREDIT_EDITORS,
        "Subtitles by the Amara.org community",
    ],
)
def test_credit_lines_are_recognised(text):
    """Whole-segment subtitle credits, whatever their case, spacing or trailing punctuation."""
    assert speech_gate.is_credit_line(text)


@pytest.mark.parametrize(
    "text",
    [
        TO_BE_CONTINUED,
        "Thank you for watching.",
        THANKS_TO_DIMATORZOK,
        "The real world can be hard",
        "",
    ],
)
def test_ordinary_text_is_not_a_credit_line(text):
    """Phrases a person can say, including ones that only mention a credit, are not credits."""
    assert not speech_gate.is_credit_line(text)


def test_speech_share_counts_the_overlap_only():
    """The share is the part of the segment inside speech, over its own length."""
    ranges = [(0.0, 1.0), (1.5, 1.7)]
    assert speech_gate.speech_share(segment(0.5, 2.5, "x"), ranges) == pytest.approx((0.5 + 0.2) / 2.0)
    assert speech_gate.speech_share(segment(3.0, 4.0, "x"), ranges) == 0.0
    assert speech_gate.speech_share(segment(1.0, 1.0, "x"), ranges) == 0.0


def test_the_share_is_measured_on_the_audio_not_the_padding():
    """A last segment Whisper ends past the audio is measured up to the end of the audio."""
    whole_phrase = segment(0.0, 7.0, " final smoke test")
    ranges = [(0.1, 1.6)]
    assert speech_gate.speech_share(whole_phrase, ranges) < 0.3
    assert speech_gate.speech_share(whole_phrase, ranges, duration=1.7) == pytest.approx(1.5 / 1.7)
    assert speech_gate.keep_spoken([whole_phrase], ranges, duration=1.7) == [whole_phrase]


def test_keep_spoken_drops_what_was_not_spoken():
    """Too little speech, or a credit line even inside speech, is dropped; the rest is kept in order."""
    segments = [
        segment(0.0, 2.0, " spoken"),
        segment(2.0, 4.0, " mostly music"),
        segment(4.0, 6.0, CREDIT_MADE),
        segment(6.0, 7.0, " spoken again"),
    ]
    ranges = [(0.0, 2.0), (3.8, 7.0)]
    kept = speech_gate.keep_spoken(segments, ranges)
    assert [item["text"] for item in kept] == [" spoken", " spoken again"]


def test_keep_spoken_passes_everything_without_ranges():
    """No ranges means no detector: every segment goes out as the transcriber produced it."""
    segments = [segment(0.0, 1.0, " " + TO_BE_CONTINUED)]
    assert speech_gate.keep_spoken(segments, None) == segments


def test_a_broken_detector_fails_open_once(monkeypatch):
    """A detector that raises is logged once, then skipped: transcripts pass through unfiltered."""
    calls = {"count": 0}

    def broken_detect_speech(samples):
        """Fail the way a missing silero-vad fails."""
        calls["count"] += 1
        raise ModuleNotFoundError("No module named 'silero_vad'")

    monkeypatch.setattr(speech_gate, "detect_speech", broken_detect_speech)
    assert speech_gate.find_speech(np.zeros(RATE, dtype=np.float32)) is None
    assert speech_gate.find_speech(np.zeros(RATE, dtype=np.float32)) is None
    assert calls["count"] == 1


def test_gate_wav_reads_the_buffer_and_rewinds_it(gate_on):
    """The WAV is read for the detector and handed back at position 0 for whoever reads it next."""
    gate_on["ranges"] = [(0.0, 1.0)]
    bio = io.BytesIO(make_wav(duration_ms=500))
    kept = speech_gate.gate_wav(bio, [segment(0.0, 0.5, " yes"), segment(2.0, 3.0, " no")])
    assert [item["text"] for item in kept] == [" yes"]
    assert bio.tell() == 0
    assert gate_on["calls"] == 1


def test_gate_wav_averages_a_stereo_buffer(gate_on, monkeypatch):
    """A two-channel buffer reaches the detector as one mono signal."""
    seen = {}

    def record_samples(samples):
        """Keep what the detector was given."""
        seen["shape"] = samples.shape
        return [(0.0, 1.0)]

    monkeypatch.setattr(speech_gate, "detect_speech", record_samples)
    bio = io.BytesIO()
    sf.write(bio, np.zeros((RATE // 10, 2), dtype=np.float32), RATE, format="WAV")
    speech_gate.gate_wav(bio, [segment(0.0, 0.1, " x")])
    assert seen["shape"] == (RATE // 10,)


def post_wav(client, path: str, **params):
    """POST a 3 s WAV, long enough to hold the stub transcriber's segments, and return the response."""
    return client.post(path, query_string=params, data={"file": (io.BytesIO(make_wav(duration_ms=3000)), "a.wav")})


def test_stt_without_the_gate_is_unchanged(client):
    """Gate off: /api/stt answers exactly what the transcriber's own text was."""
    body = post_wav(client, "/api/stt").get_json()
    assert body["text"] == "stub transcription"


def test_stt_keeps_only_spoken_segments(client, gate_on):
    """Gate on: the text is the spoken segments joined, the unspoken one gone."""
    gate_on["ranges"] = [(0.0, 1.1)]
    body = post_wav(client, "/api/stt").get_json()
    assert body["text"] == "first phrase"


def test_stt_with_no_speech_answers_empty_text(client, gate_on):
    """A recording with nothing spoken in it reads empty, not as a subtitle credit."""
    gate_on["ranges"] = []
    response = post_wav(client, "/api/stt")
    assert response.status_code == 200
    assert response.get_json()["text"] == ""


def test_transcript_drops_unspoken_segments_before_the_join(diarize_client, gate_on):
    """/api/transcript attributes and joins only what was spoken."""
    gate_on["ranges"] = [(1.3, 2.4)]
    body = post_wav(diarize_client, "/api/transcript").get_json()
    assert [item["text"] for item in body["segments"]] == ["second phrase"]
    assert body["text"] == "second phrase"


@pytest.fixture
def stream_pool(monkeypatch):
    """A one-slot model pool with the whisper stub as the transcriber."""
    pool: queue.Queue = queue.Queue()
    pool.put("model-sentinel")
    monkeypatch.setattr(model_pool, "MODEL_POOL", pool)
    monkeypatch.setattr(config, "STT_BACKEND", "whisper")
    return pool


def utterance_buffer(samples: np.ndarray) -> dict:
    """A stream buffer holding one signal."""
    buffer = stream.new_buffer()
    stream.append_samples(buffer, samples)
    return buffer


def test_an_utterance_with_no_speech_is_not_transcribed(stream_pool, gate_on, stt_module, monkeypatch):
    """No detected speech: no model is borrowed, the transcriber is never called, nothing comes out."""
    called = {"count": 0}

    def counting_segments(bio, model=None, device=None, language=None):
        """Count calls to the transcriber."""
        called["count"] += 1
        return [segment(0.0, 1.0, CREDIT_CREATED)]

    monkeypatch.setattr(stt_module, "get_stt_segments", counting_segments)
    gate_on["ranges"] = []
    samples = make_tone(2.0)
    result = stream.transcribe_utterance(utterance_buffer(samples), {"start": 0, "end": samples.size}, None)
    assert result == []
    assert called["count"] == 0
    assert stream_pool.qsize() == 1


def test_an_utterance_keeps_its_spoken_segments_in_stream_time(stream_pool, gate_on):
    """Speech in the first phrase only: that phrase comes out, offset by the utterance start."""
    gate_on["ranges"] = [(0.0, 1.1)]
    samples = np.concatenate([make_silence(1.0), make_tone(3.0)])
    buffer = utterance_buffer(samples)
    result = stream.transcribe_utterance(buffer, {"start": RATE, "end": samples.size}, None)
    assert [(item["start"], item["end"], item["text"]) for item in result] == [(1.0, 2.1, "first phrase")]
    assert stream_pool.qsize() == 1


def test_a_broken_detector_lets_the_utterance_through(stream_pool, monkeypatch):
    """Without a working detector the utterance is transcribed as before, nothing dropped."""
    monkeypatch.setattr(config, "SPEECH_GATE", True)

    def broken_detect_speech(samples):
        """Fail like a missing silero-vad."""
        raise RuntimeError("no detector")

    monkeypatch.setattr(speech_gate, "detect_speech", broken_detect_speech)
    samples = make_tone(3.0)
    result = stream.transcribe_utterance(utterance_buffer(samples), {"start": 0, "end": samples.size}, None)
    assert [item["text"] for item in result] == ["first phrase", "second phrase"]

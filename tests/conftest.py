#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test fixtures: stub the model backends before stt_server is imported, expose a Flask test client.

Helpers live in tests/helpers.py. Importing them from here instead would make a test module do
`from tests.conftest import ...`, which executes this file a SECOND time under a second name and
leaves two rival sets of stubs in sys.modules.
"""

import os
import queue
import sys
import types

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import libs  # noqa: E402  (the real package; only the backend modules below are replaced)


def fake_get_model():
    """Stand in for stt.get_model() - the tests never load real Whisper weights."""
    return object()


def fake_get_stt_bio(bio, model=None, device=None, language=None):
    """Stand in for stt.get_stt_bio() with a fixed transcription."""
    return "stub transcription"


def fake_get_stt_segments(bio, model=None, device=None, language=None):
    """Stand in for stt.get_stt_segments() with two phrases straddling the stub speaker turns."""
    return [
        {"start": 0.0, "end": 1.1, "text": " first phrase"},
        {"start": 1.3, "end": 2.4, "text": " second phrase"},
    ]


def fake_describe_whisper():
    """Stand in for stt.describe_backend(): a two-language model that is on disk."""
    return {
        "backend": "whisper",
        "model": "small.en-stub",
        "aliases": [],
        "status": "installed",
        "multilingual": True,
        "accepts_language": True,
        "languages_source": "derived",
        "languages": ["en", "ru"],
        "default_language": "en",
    }


def fake_normalize_language_code(language):
    """Stand in for stt.normalize_language_code(): knows English and Russian only."""
    known = {"en": "en", "english": "en", "ru": "ru", "russian": "ru"}
    return known.get(language.strip().lower())


def fake_get_diarizer(model_id=None):
    """Stand in for diarize.get_diarizer() - the tests never load real diarization weights."""
    return object()


def fake_describe_diarizer():
    """Stand in for diarize.describe_backend(): installed, and with no languages by nature."""
    return {
        "backend": "diarize",
        "model": "nvidia/Nemotron-3-Diarization-stub",
        "aliases": [],
        "status": "installed",
        "multilingual": None,
        "accepts_language": False,
        "languages_source": None,
        "languages": None,
        "max_speakers": 8,
    }


def fake_diarize_wav(bio, diarizer=None, threshold=None):
    """Stand in for diarize.diarize_wav() with two fixed, overlapping speaker turns."""
    return [
        {"speaker": 0, "start": 0.0, "end": 1.2},
        {"speaker": 1, "start": 1.0, "end": 2.5},
    ]


# Replace every backend module so the tests need neither torch, whisper, soundfile nor
# transformers installed. Must run before stt_server (and therefore libs.model_pool) is
# imported anywhere.
fake_stt = types.ModuleType("libs.stt")
fake_stt.get_model = fake_get_model
fake_stt.get_stt_bio = fake_get_stt_bio
fake_stt.describe_backend = fake_describe_whisper
fake_stt.get_stt_segments = fake_get_stt_segments
fake_stt.normalize_language_code = fake_normalize_language_code
sys.modules["libs.stt"] = fake_stt
libs.stt = fake_stt


def fake_describe_parakeet():
    """Stand in for parakeet.describe_backend(): present but not installed, and language-blind."""
    return {
        "backend": "parakeet",
        "model": "nvidia/parakeet-tdt-0.6b-v3",
        "aliases": [],
        "status": "absent",
        "multilingual": True,
        "accepts_language": False,
        "languages_source": "model card, read 2026-09-24",
        "languages": ["en", "ru"],
        "default_language": None,
    }


fake_parakeet = types.ModuleType("libs.parakeet")
fake_parakeet.get_model = fake_get_model
fake_parakeet.get_stt_bio = fake_get_stt_bio
fake_parakeet.get_stt_segments = fake_get_stt_segments
fake_parakeet.describe_backend = fake_describe_parakeet
sys.modules["libs.parakeet"] = fake_parakeet
libs.parakeet = fake_parakeet


def fake_find_handover(state, start, end):
    """Stand in for diarize.find_handover(): no speaker change unless a test says otherwise."""
    return None


fake_diarize = types.ModuleType("libs.diarize")
fake_diarize.get_diarizer = fake_get_diarizer
fake_diarize.diarize_wav = fake_diarize_wav
fake_diarize.describe_backend = fake_describe_diarizer
fake_diarize.find_handover = fake_find_handover
fake_diarize.STREAM_FRAME_SECONDS = 0.01
sys.modules["libs.diarize"] = fake_diarize
libs.diarize = fake_diarize

import stt_server  # noqa: E402  (must follow the backend stubs)
from libs import config, model_pool, speech_gate  # noqa: E402  (must follow the backend stubs)


@pytest.fixture(autouse=True)
def speech_gate_off(monkeypatch):
    """Run every test with the speech gate off unless the test switches it on.

    CI installs no silero-vad, and a detector that failed once stays off for the process; the
    gate's own tests replace the detector and switch the gate on themselves.
    """
    monkeypatch.setattr(config, "SPEECH_GATE", False)
    monkeypatch.setattr(speech_gate, "VAD_BROKEN", False)


@pytest.fixture
def client(monkeypatch):
    """Flask test client backed by a one-slot model pool holding a sentinel model."""
    pool: queue.Queue = queue.Queue()
    pool.put("model-sentinel")
    monkeypatch.setattr(model_pool, "MODEL_POOL", pool)
    monkeypatch.setattr(config, "MODEL_POOL_SIZE", 1)
    # Pinned rather than inherited: a machine with DIARIZE_ENABLED set in its environment would
    # otherwise turn the disabled-build test into a real pool wait.
    monkeypatch.setattr(config, "DIARIZE_ENABLED", False)
    return stt_server.app.test_client()


@pytest.fixture
def stt_module():
    """The stubbed libs.stt module, so a test can swap get_stt_bio for its own."""
    return fake_stt


@pytest.fixture
def diarize_module():
    """The stubbed libs.diarize module, so a test can swap diarize_wav for its own."""
    return fake_diarize


@pytest.fixture
def diarize_client(client, monkeypatch):
    """Test client with diarization switched on and a one-slot diarizer pool."""
    pool: queue.Queue = queue.Queue()
    pool.put("diarizer-sentinel")
    monkeypatch.setattr(model_pool, "DIARIZER_POOL", pool)
    monkeypatch.setattr(config, "DIARIZE_ENABLED", True)
    monkeypatch.setattr(config, "DIARIZE_POOL_SIZE", 1)
    return client

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

# What the Whisper stub knows. `small.en-stub` is the single-model default and, despite its
# name, multilingual; `medium` is known to the backend and never loaded by any fixture.
FAKE_WHISPER_MODELS = {
    "small.en-stub": {"languages": ["en", "ru"], "aliases": []},
    "tiny.en": {"languages": ["en"], "aliases": []},
    "turbo": {"languages": ["en", "ru", "de"], "aliases": ["large-v3-turbo"]},
    "medium": {"languages": ["en", "ru", "de"], "aliases": []},
}
FAKE_PARAKEET_LANGUAGES = {"nvidia/parakeet-tdt-0.6b-v3": ["en", "ru"]}

LEGACY_WHISPER_MODEL = "small.en-stub"
LEGACY_PARAKEET_MODEL = "nvidia/parakeet-tdt-0.6b-v3"


def fake_get_model(device=None, model_name=None):
    """Stand in for get_model() - the tests never load real weights, so the instance names its model."""
    return {"stub_model": model_name}


def read_stub_model_name(model):
    """The model name a stub instance carries, or "" for anything else a test put in a pool."""
    return model.get("stub_model") or "" if isinstance(model, dict) else ""


def fake_get_stt_segments(bio, model=None, device=None, language=None):
    """Stand in for stt.get_stt_segments() with two phrases straddling the stub speaker turns."""
    return [
        {"start": 0.0, "end": 1.1, "text": " first phrase"},
        {"start": 1.3, "end": 2.4, "text": " second phrase"},
    ]


def fake_get_stt_result(bio, model=None, device=None, language=None, prompt=None):
    """Stand in for stt.get_stt_result(): fixed text, the stub phrases, and the language Whisper would report.

    An English-only checkpoint reports `en` whatever it was told; otherwise autodetect reports
    `en` and an explicit code is reported back as given. The segments are what the speech gate
    filters on /api/stt. `prompt` is taken, like the real module's, and changes nothing here.
    """
    segments = fake_get_stt_segments(bio, model=model, device=device, language=language)
    if read_stub_model_name(model).endswith(".en") or language in (None, "auto"):
        return {"text": "stub transcription", "language": "en", "segments": segments}
    return {"text": "stub transcription", "language": language, "segments": segments}


def fake_get_stt_bio(bio, model=None, device=None, language=None):
    """Stand in for stt.get_stt_bio(), which is get_stt_result() without the language."""
    return fake_get_stt_result(bio, model=model, device=device, language=language)["text"]


def fake_resolve_whisper_languages(model_name):
    """Stand in for stt.resolve_languages(): the table, else what the name implies.

    Unlike the real module it does not reduce a file path to its name, on purpose: a caller
    that handed it the load path instead of the id would then get the wrong list, and fail.
    """
    entry = FAKE_WHISPER_MODELS.get(model_name)
    if entry is not None:
        return list(entry["languages"])
    return ["en"] if model_name.endswith(".en") else ["en", "ru"]


def fake_list_whisper_aliases(model_name):
    """Stand in for stt.list_aliases(): other names of the same stub checkpoint."""
    return list(FAKE_WHISPER_MODELS.get(model_name, {}).get("aliases", []))


def fake_list_known_whisper_models():
    """Stand in for stt.list_known_models(): every stub name, aliases included, like whisper._MODELS."""
    names = set(FAKE_WHISPER_MODELS)
    for entry in FAKE_WHISPER_MODELS.values():
        names.update(entry["aliases"])
    return sorted(names)


def fake_describe_whisper(model_name=None):
    """Stand in for stt.describe_backend(): a stub checkpoint that is on disk."""
    model_name = LEGACY_WHISPER_MODEL if model_name is None else model_name
    return {
        "backend": "whisper",
        "model": model_name,
        "aliases": fake_list_whisper_aliases(model_name),
        "status": "installed",
        "multilingual": not model_name.endswith(".en"),
        "accepts_language": True,
        "languages_source": "derived",
        "languages": fake_resolve_whisper_languages(model_name),
        "default_language": "en",
    }


def fake_normalize_language_code(language):
    """Stand in for stt.normalize_language_code(): knows English, Russian and German only."""
    known = {"en": "en", "english": "en", "ru": "ru", "russian": "ru", "de": "de", "german": "de"}
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
fake_stt.get_stt_result = fake_get_stt_result
fake_stt.get_stt_bio = fake_get_stt_bio
fake_stt.describe_backend = fake_describe_whisper
fake_stt.get_stt_segments = fake_get_stt_segments
fake_stt.normalize_language_code = fake_normalize_language_code
fake_stt.resolve_languages = fake_resolve_whisper_languages
fake_stt.list_aliases = fake_list_whisper_aliases
fake_stt.list_known_models = fake_list_known_whisper_models
sys.modules["libs.stt"] = fake_stt
libs.stt = fake_stt


def fake_resolve_parakeet_languages(model_name):
    """Stand in for parakeet.resolve_languages(): the table's codes, or None for an id it lacks."""
    languages = FAKE_PARAKEET_LANGUAGES.get(model_name)
    return list(languages) if languages else None


def fake_list_parakeet_aliases(model_name):
    """Stand in for parakeet.list_aliases(): the short name after the last slash."""
    short_name = model_name.rsplit("/", 1)[-1]
    return [short_name] if short_name != model_name else []


def fake_list_known_parakeet_models():
    """Stand in for parakeet.list_known_models(): the ids the language table covers."""
    return sorted(FAKE_PARAKEET_LANGUAGES)


def fake_describe_parakeet(model_name=None):
    """Stand in for parakeet.describe_backend(): present but not installed, and language-blind."""
    model_name = LEGACY_PARAKEET_MODEL if model_name is None else model_name
    languages = fake_resolve_parakeet_languages(model_name)
    return {
        "backend": "parakeet",
        "model": model_name,
        "aliases": fake_list_parakeet_aliases(model_name),
        "status": "absent",
        "multilingual": True,
        "accepts_language": False,
        "languages_source": "model card, read 2026-09-24" if languages else None,
        "languages": languages,
        "default_language": None,
    }


def fake_parakeet_get_stt_segments(bio, model=None, device=None, language=None):
    """Stand in for parakeet.get_stt_segments(): the Whisper stub's timing, but its own words."""
    return [
        {"start": 0.0, "end": 1.1, "text": " parakeet first"},
        {"start": 1.3, "end": 2.4, "text": " parakeet second"},
    ]


def fake_parakeet_get_stt_result(bio, model=None, device=None, language=None, prompt=None):
    """Stand in for parakeet.get_stt_result(): its own text and words, and no language, as the model reports none.

    `prompt` is accepted and ignored, as the real module does.
    """
    segments = fake_parakeet_get_stt_segments(bio, model=model, device=device, language=language)
    return {"text": "parakeet transcription", "language": None, "segments": segments}


def fake_parakeet_get_stt_bio(bio, model=None, device=None, language=None):
    """Stand in for parakeet.get_stt_bio() with a transcription the Whisper stub never gives."""
    return fake_parakeet_get_stt_result(bio, model=model, device=device, language=language)["text"]


# No normalize_language_code on purpose, exactly like the real module: Parakeet has no language
# table, and the server tells the two kinds of backend apart by that absence.
fake_parakeet = types.ModuleType("libs.parakeet")
fake_parakeet.get_model = fake_get_model
fake_parakeet.get_stt_result = fake_parakeet_get_stt_result
fake_parakeet.get_stt_bio = fake_parakeet_get_stt_bio
fake_parakeet.get_stt_segments = fake_parakeet_get_stt_segments
fake_parakeet.describe_backend = fake_describe_parakeet
fake_parakeet.resolve_languages = fake_resolve_parakeet_languages
fake_parakeet.list_aliases = fake_list_parakeet_aliases
fake_parakeet.list_known_models = fake_list_known_parakeet_models
fake_parakeet.WORD_SEGMENTS = True
sys.modules["libs.parakeet"] = fake_parakeet
libs.parakeet = fake_parakeet


def fake_find_handover(state, start, end):
    """Stand in for diarize.find_handover(): no speaker change unless a test says otherwise."""
    return None


def fake_trim_activity(state, keep_from):
    """Stand in for diarize.trim_activity(): the fake diarizer keeps no activity to drop."""
    return None


fake_diarize = types.ModuleType("libs.diarize")
fake_diarize.get_diarizer = fake_get_diarizer
fake_diarize.diarize_wav = fake_diarize_wav
fake_diarize.describe_backend = fake_describe_diarizer
fake_diarize.find_handover = fake_find_handover
fake_diarize.trim_activity = fake_trim_activity
fake_diarize.STREAM_FRAME_SECONDS = 0.01
sys.modules["libs.diarize"] = fake_diarize
libs.diarize = fake_diarize

import stt_server  # noqa: E402  (must follow the backend stubs)
from libs import config, model_pool, speech_gate  # noqa: E402  (must follow the backend stubs)
from tests.helpers import make_model_sentinel  # noqa: E402  (imports libs.model_pool, so it follows too)


def build_pool(model_id, count):
    """A queue holding `count` stub instances of one model, as init_model_pool would fill it."""
    pool: queue.Queue = queue.Queue()
    for unused_number in range(count):
        pool.put(make_model_sentinel(model_id))
    return pool


@pytest.fixture(autouse=True)
def speech_gate_off(monkeypatch):
    """Run every test with the speech gate off unless the test switches it on.

    CI installs no silero-vad, and a detector that cannot be loaded stays off for the process; the
    gate's own tests replace the detector and switch the gate on themselves.
    """
    monkeypatch.setattr(config, "SPEECH_GATE", False)
    monkeypatch.setattr(speech_gate, "VAD_BROKEN", False)


@pytest.fixture
def legacy_pool(monkeypatch):
    """A single-model deployment, the Whisper stub with one pooled instance; returns that model's queue."""
    monkeypatch.setattr(config, "STT_MODELS", ())
    monkeypatch.setattr(config, "STT_DEFAULT_MODEL", "")
    monkeypatch.setattr(config, "STT_BACKEND", "whisper")
    monkeypatch.setattr(config, "WHISPER_MODEL", LEGACY_WHISPER_MODEL)
    monkeypatch.setattr(config, "PARAKEET_MODEL", LEGACY_PARAKEET_MODEL)
    monkeypatch.setattr(config, "MODEL_POOL_SIZE", 1)
    pool = build_pool(LEGACY_WHISPER_MODEL, 1)
    monkeypatch.setattr(model_pool, "MODEL_POOLS", {LEGACY_WHISPER_MODEL: pool})
    monkeypatch.setattr(model_pool, "MODELS_LOADED", {})
    # Pinned rather than inherited: a machine with DIARIZE_ENABLED set in its environment would
    # otherwise turn the disabled-build test into a real pool wait.
    monkeypatch.setattr(config, "DIARIZE_ENABLED", False)
    return pool


@pytest.fixture
def client(legacy_pool):
    """Flask test client for a single-model deployment: one pooled instance of the Whisper stub."""
    return stt_server.app.test_client()


# Three models side by side: the Whisper stub (the default, being first), an English-only
# Whisper with two instances, and Parakeet.
MULTI_MODELS = (
    {"backend": "whisper", "model": "small.en-stub", "pool_size": 1},
    {"backend": "whisper", "model": "tiny.en", "pool_size": 2},
    {"backend": "parakeet", "model": "nvidia/parakeet-tdt-0.6b-v3", "pool_size": 1},
)


@pytest.fixture
def multi_client(client, monkeypatch):
    """Test client for a deployment with STT_MODELS set: three models, each with its own pool."""
    monkeypatch.setattr(config, "STT_MODELS", MULTI_MODELS)
    pools = {entry["model"]: build_pool(entry["model"], entry["pool_size"]) for entry in MULTI_MODELS}
    monkeypatch.setattr(model_pool, "MODEL_POOLS", pools)
    return client


@pytest.fixture
def stt_module():
    """The stubbed libs.stt module, so a test can swap get_stt_result for its own."""
    return fake_stt


@pytest.fixture
def parakeet_module():
    """The stubbed libs.parakeet module, so a test can swap one of its functions."""
    return fake_parakeet


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

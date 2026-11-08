#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The REAL libs/stt.py file reader, which every other test replaces with a stub."""

import importlib.util
import io
import os
import shutil
import sys
import types
import wave

import pytest

# Local imports
from tests.helpers import make_wav

MODULE_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)), "libs", "stt.py")

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs the ffmpeg binary")


def install_fake_whisper(monkeypatch):
    """Put stand-ins for torch, torchaudio and whisper in sys.modules: CI installs none of them.

    Only what libs/stt.py touches at import time is there; the reader under test never reaches
    the model, because get_stt_bio is replaced.
    """
    fake_whisper = types.ModuleType("whisper")
    fake_whisper.Whisper = type("Whisper", (), {})
    fake_whisper._MODELS = {}
    fake_tokenizer = types.ModuleType("whisper.tokenizer")
    fake_tokenizer.LANGUAGES = {"en": "english"}
    fake_tokenizer.TO_LANGUAGE_CODE = {"english": "en"}
    fake_whisper.tokenizer = fake_tokenizer
    monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))
    monkeypatch.setitem(sys.modules, "torchaudio", types.ModuleType("torchaudio"))
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)
    monkeypatch.setitem(sys.modules, "whisper.tokenizer", fake_tokenizer)


@pytest.fixture
def real_stt(monkeypatch):
    """libs/stt.py loaded from its file, with get_stt_bio recording the buffer it is handed.

    Not registered in sys.modules: the stub is what the rest of the suite needs. Returns the
    module and the list of buffers get_stt_bio received.
    """
    install_fake_whisper(monkeypatch)
    spec = importlib.util.spec_from_file_location("libs_stt_real", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    received = []

    def record_buffer(bio, model=None, device=None, language=None):
        """Stand in for get_stt_bio: keep the bytes the model would have decoded."""
        received.append(bio.getvalue())
        return "transcribed"

    monkeypatch.setattr(module, "get_stt_bio", record_buffer)
    return module, received


def read_wav_format(data: bytes) -> tuple[int, int, int]:
    """(channels, sample rate, sample width in bytes) of a WAV payload."""
    with wave.open(io.BytesIO(data), "rb") as reader:
        return reader.getnchannels(), reader.getframerate(), reader.getsampwidth()


def write_stereo_wav(path, sample_rate: int = 44100, duration_ms: int = 200) -> None:
    """Write a silent 16-bit stereo WAV at a rate the model does not take."""
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00\x00\x00" * (sample_rate * duration_ms // 1000))


def test_a_file_already_in_the_target_format_is_passed_on_untouched(real_stt, tmp_path):
    """A 16 kHz mono 16-bit WAV takes the server's pass-through: the model gets the file's own bytes."""
    module, received = real_stt
    wav = make_wav(duration_ms=200)
    path = tmp_path / "phrase.wav"
    path.write_bytes(wav)
    assert module.get_stt_filename(str(path)) == "transcribed"
    assert received == [wav]


@needs_ffmpeg
def test_a_file_in_another_format_is_converted_as_an_upload_is(real_stt, tmp_path):
    """44.1 kHz stereo reaches the model as 16 kHz mono 16-bit, exactly what /api/stt would hand it."""
    module, received = real_stt
    path = tmp_path / "stereo.wav"
    write_stereo_wav(path)
    module.get_stt_filename(str(path))
    assert read_wav_format(received[0]) == (1, 16000, 2)


def test_a_missing_file_is_reported_before_anything_is_decoded(real_stt, tmp_path):
    """A path that does not exist raises FileNotFoundError and never reaches the model."""
    module, received = real_stt
    with pytest.raises(FileNotFoundError):
        module.get_stt_filename(str(tmp_path / "absent.wav"))
    assert received == []

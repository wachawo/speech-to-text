#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audio pre-processing: turn an arbitrary upload into the exact WAV format Whisper expects."""

import io
import logging

from pydub import AudioSegment

logger = logging.getLogger(__name__)

# Whisper consumes 16 kHz mono 16-bit PCM. Producing it here is what lets
# libs/stt.py skip its torchaudio resampling branch on the request hot path.
TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
TARGET_SAMPLE_WIDTH = 2


def convert_to_wav(bio: io.BytesIO) -> io.BytesIO:
    """Decode any pydub-supported audio buffer and re-export it as 16 kHz mono 16-bit WAV.

    Raises whatever pydub raises when the payload is not decodable audio; the
    caller turns that into a 400.
    """
    audio = AudioSegment.from_file(bio)
    audio = (
        audio.set_channels(TARGET_CHANNELS)
        .set_frame_rate(TARGET_SAMPLE_RATE)
        .set_sample_width(TARGET_SAMPLE_WIDTH)
    )
    wav_bio = io.BytesIO()
    audio.export(wav_bio, format="wav")
    wav_bio.seek(0)
    return wav_bio


def main():
    """No-op entry point: this module is imported for its conversion helper."""
    pass


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audio pre-processing: turn an arbitrary upload into the exact WAV format Whisper expects."""

import io
import logging
import struct

from pydub import AudioSegment

logger = logging.getLogger(__name__)

# Whisper consumes 16 kHz mono 16-bit PCM. Producing it here is what lets
# libs/stt.py skip its torchaudio resampling branch on the request hot path.
TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
TARGET_SAMPLE_WIDTH = 2

# A RIFF chunk header: a four-byte id and a little-endian 32-bit size. A chunk of odd size is
# followed by one pad byte, which its size does not count.
CHUNK_HEADER = struct.Struct("<4sI")
# The start of a fmt chunk: format tag, channels, sample rate, byte rate, block align, bits per sample.
FMT_FIELDS = struct.Struct("<HHIIHH")
# Plain integer PCM. WAVE_FORMAT_EXTENSIBLE and every compressed format take the pydub path.
WAVE_FORMAT_PCM = 1


def read_chunk_header(bio: io.BytesIO) -> tuple[bytes, int] | None:
    """Read the next chunk's id and size from the buffer's position; None at the end of the data."""
    header = bio.read(CHUNK_HEADER.size)
    if len(header) < CHUNK_HEADER.size:
        return None
    chunk_id, size = CHUNK_HEADER.unpack(header)
    return chunk_id, size


def is_target_wav(bio: io.BytesIO) -> bool:
    """Whether the buffer already is a RIFF/WAVE file of 16 kHz mono 16-bit PCM; the buffer is rewound.

    Only the headers are read: the chunks are walked up to `data`, skipping any other (LIST, fact,
    cue) together with its pad byte, and the fmt chunk may be longer than its 16 required bytes.
    Anything unexpected - no fmt before data, another format tag, rate, channel count or width, a
    truncated header, a data chunk that declares no bytes - answers False and the upload goes through pydub exactly as before: a miss
    costs that conversion, a false yes would hand the transcriber a file it cannot read.
    """
    bio.seek(0)
    try:
        riff = bio.read(12)
        if len(riff) < 12 or riff[0:4] != b"RIFF" or riff[8:12] != b"WAVE":
            return False
        seen_fmt = False
        while (chunk := read_chunk_header(bio)) is not None:
            chunk_id, size = chunk
            if chunk_id == b"data":
                # A size of 0 is the header a streaming writer leaves when it cannot seek back:
                # soundfile reads it as no samples, ffmpeg reads to the end, so it takes pydub.
                return seen_fmt and size > 0
            if chunk_id == b"fmt ":
                body = bio.read(size)
                if size < FMT_FIELDS.size or len(body) < size:
                    return False
                format_tag, channels, sample_rate, unused_byte_rate, block_align, bits = FMT_FIELDS.unpack_from(body)
                if (format_tag, channels, sample_rate, block_align, bits) != (
                    WAVE_FORMAT_PCM,
                    TARGET_CHANNELS,
                    TARGET_SAMPLE_RATE,
                    TARGET_CHANNELS * TARGET_SAMPLE_WIDTH,
                    TARGET_SAMPLE_WIDTH * 8,
                ):
                    return False
                seen_fmt = True
                bio.seek(size % 2, io.SEEK_CUR)
            else:
                bio.seek(size + size % 2, io.SEEK_CUR)
        return False
    finally:
        bio.seek(0)


def convert_to_wav(bio: io.BytesIO) -> io.BytesIO:
    """Hand on a buffer as 16 kHz mono 16-bit WAV: as it is when it already is one, else decoded by pydub.

    The pass-through is the short-phrase path: decoding a WAV that needs nothing done to it cost
    70 ms per request through pydub and ffmpeg, against well under a millisecond to read its header.
    Every reader downstream decodes with soundfile, which takes the extra chunks and the longer fmt
    a recorder may write exactly as it takes pydub's plain header. The pass-through adds no
    resampling anywhere: a file at another rate, width or channel count goes through pydub as it
    always did.

    Raises whatever pydub raises when the payload is not decodable audio; the
    caller turns that into a 400.
    """
    if is_target_wav(bio):
        return bio
    audio = AudioSegment.from_file(bio)
    audio = audio.set_channels(TARGET_CHANNELS).set_frame_rate(TARGET_SAMPLE_RATE).set_sample_width(TARGET_SAMPLE_WIDTH)
    wav_bio = io.BytesIO()
    audio.export(wav_bio, format="wav")
    wav_bio.seek(0)
    return wav_bio


def main():
    """No-op entry point: this module is imported for its conversion helper."""
    pass


if __name__ == "__main__":
    main()

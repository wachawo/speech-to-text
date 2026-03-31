#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Get STT from audio file using Whisper
Usage: python stt.py file.wav
"""

import logging
import io
import soundfile as sf
import sys
import os
import time
import torch
import torchaudio
import warnings

warnings.filterwarnings(
    "ignore", message="FP16 is not supported on CPU; using FP32 instead"
)

# import traceback
import urllib3
import whisper
import numpy as np
from typing import Optional
from pydub import AudioSegment

LOGGING = {
    "format": "%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s.%(funcName)s) %(message)s",
    "level": logging.INFO,
    "datefmt": "%Y-%m-%d %H:%M:%S",
    "handlers": [
        logging.StreamHandler(),
        # logging.handlers.RotatingFileHandler(filename=f'{SCRIPT_NAME}.log', maxBytes=1024 * 1024 * 10, backupCount=3),
    ],
}
logging.basicConfig(**LOGGING)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small.en").lower()
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "auto").lower()
WHISPER_DOWNLOAD_ROOT = os.getenv("WHISPER_DOWNLOAD_ROOT", "models")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "en").lower()


def get_model(device: str = COMPUTE_TYPE):
    """Load the Whisper model."""
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device not in ["cpu", "cuda"]:
        raise ValueError("Device must be 'cpu' or 'cuda'.")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available on this machine.")
    os.makedirs(WHISPER_DOWNLOAD_ROOT, exist_ok=True)
    model = whisper.load_model(
        WHISPER_MODEL,
        device=device,
        download_root=WHISPER_DOWNLOAD_ROOT,
    )
    return model


def convert_to_wav(input_filename: str, output_filename: str = None) -> str:
    """Convert audio file to WAV format."""
    # ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a pcm_s16le output.wav
    audio = AudioSegment.from_file(input_filename)
    # Set to mono and 16kHz
    audio = (
        audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
    )  # 2 bytes = 16 bits
    # Export as WAV
    audio.export(output_filename, format="wav")
    return str(output_filename)


def get_stt_bio(
    bio: io.BytesIO = io.BytesIO(),
    model: Optional[whisper.Whisper] = None,
    device: Optional[str] = COMPUTE_TYPE,
) -> str:
    if not model:
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device not in ["cpu", "cuda"]:
            raise ValueError("Device must be 'cpu' or 'cuda'.")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available on this machine.")
        # Load the Whisper model
        model = get_model(device=device)
    # Read the audio file
    data, sr = sf.read(bio)
    # Resample to 16000 Hz (Whisper's expected sampling rate)
    if sr != 16000:
        data = torch.from_numpy(data).float()
        if data.ndim == 2:
            data = data.mean(dim=1)
        resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=16000)
        data = resampler(data)
        data = data.numpy()
    elif isinstance(data, np.ndarray):
        if data.ndim == 2:
            data = data.mean(axis=1)
        data = data.astype(np.float32)
    # Normalize the waveform to [-1.0, 1.0]
    if np.abs(data).max() > 0:
        data = data / np.abs(data).max()

    # Force deterministic decoding so repeated requests for the same input
    # produce stable output.
    torch.manual_seed(0)
    np.random.seed(0)
    result = model.transcribe(
        audio=data,
        language=WHISPER_LANGUAGE,
        task="transcribe",
        temperature=0.0,
        beam_size=1,
        best_of=1,
        condition_on_previous_text=False,
    )
    logger.debug(f"result: {result['text']}")
    return result["text"].strip()


def get_stt_filename(
    filename: str, model: Optional[whisper.Whisper] = None, device: str = COMPUTE_TYPE
) -> str:
    """Transcribe audio using Whisper model."""
    if not os.path.exists(filename):
        raise FileNotFoundError(f"File '{filename}' does not exist.")
    # Get transcription using audio file
    audio = AudioSegment.from_file(filename)
    channels = audio.split_to_mono()
    if len(channels) > 1:
        audio = AudioSegment.from_mono_audiosegments(*channels)
    # Write audio to a BytesIO
    bio = io.BytesIO()
    audio.export(bio, format="wav")
    bio.seek(0)
    return get_stt_bio(bio, model=model, device=device)


def main():
    if len(sys.argv) < 2:
        sys.exit(1)
    filename = sys.argv[1]
    start_time = time.monotonic()
    text = get_stt_filename(filename)
    logger.info(f"STT: {text}\n({time.monotonic() - start_time:.3f} sec)")


if __name__ == "__main__":
    main()

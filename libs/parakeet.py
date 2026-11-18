#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NVIDIA Parakeet TDT as a transcription backend, with the same surface as libs/stt.py."""

import io
import logging
import os
import sys
import threading
import time
import traceback
from typing import Any

import numpy as np
import soundfile as sf

# Local imports
from libs import batching, config, logs

logger = logging.getLogger(__name__)

# The processor refuses anything else, and libs/audio.py already exports exactly this.
TARGET_SAMPLE_RATE = 16000

# Read from the model card on 2026-09-24 for nvidia/parakeet-tdt-0.6b-v3 and valid for that id
# alone. It is in no config file the runtime can read, so reporting it means carrying it. The
# model detects the language itself and takes no language argument at all.
LANGUAGES = (
    "en",
    "es",
    "fr",
    "de",
    "bg",
    "hr",
    "cs",
    "da",
    "nl",
    "et",
    "fi",
    "el",
    "hu",
    "it",
    "lv",
    "lt",
    "mt",
    "pl",
    "pt",
    "ro",
    "sk",
    "sl",
    "sv",
    "ru",
    "uk",
)
LANGUAGES_BY_MODEL = {"nvidia/parakeet-tdt-0.6b-v3": LANGUAGES}

# get_stt_segments returns words, not phrases (see group_tokens). The live stream reads this to
# join them into phrases before sending; a backend without the name returns phrases.
WORD_SEGMENTS = True

# Feature frames (10 ms each) of the longest audio decoded together with others. A batch costs
# its longest member for everyone in it, so a short phrase must not wait behind a long job piece:
# anything longer is decoded alone, after the batch.
BATCH_FRAMES = 3000

# One engine per (device, model) in this process: the weights and the thread that decodes on
# them. get_model hands out the same engine for every instance of a pool, so a pool of N holds
# one copy of the weights and lets N requests into the engine at once - which is also the
# largest batch it can form.
ENGINES: dict[tuple[str, str], dict[str, Any]] = {}
ENGINES_LOCK = threading.Lock()


def resolve_device(device: str | None = None) -> str:
    """Resolve "auto" to cuda/cpu and reject a device this machine cannot serve."""
    import torch

    device = config.COMPUTE_TYPE if device is None else device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device not in ("cpu", "cuda"):
        raise ValueError("Device must be 'cpu' or 'cuda'.")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available on this machine.")
    return device


def resolve_languages(model_name: str) -> list[str] | None:
    """The language codes this table carries for a model id, or None for an id it does not cover."""
    return list(LANGUAGES_BY_MODEL.get(model_name) or []) or None


def list_aliases(model_name: str) -> list[str]:
    """The short name after the last `/` (`parakeet-tdt-0.6b-v3`), when it differs from the id."""
    short_name = model_name.rsplit("/", 1)[-1]
    return [short_name] if short_name and short_name != model_name else []


def list_known_models() -> list[str]:
    """Every model id this module can describe with confidence, loaded or not."""
    return sorted(LANGUAGES_BY_MODEL)


def describe_backend(model_name: str | None = None) -> dict:
    """Describe one Parakeet model for GET /api/models, loading nothing; None means PARAKEET_MODEL."""
    model_id = config.PARAKEET_MODEL if model_name is None else model_name
    cached = os.path.join(config.PARAKEET_DOWNLOAD_ROOT, "models--" + model_id.replace("/", "--"))
    languages = LANGUAGES_BY_MODEL.get(model_id)
    return {
        "backend": "parakeet",
        "model": model_id,
        "aliases": list_aliases(model_id),
        "status": "installed" if os.path.isdir(cached) else "absent",
        "multilingual": True,
        # The model detects the language itself; there is no language argument to honour, so a
        # `?language=` against this backend would be a promise nothing keeps.
        "accepts_language": False,
        "languages_source": "model card, read 2026-09-24" if languages else None,
        # Refused rather than guessed for an id this table does not cover.
        "languages": list(languages) if languages else None,
        "default_language": None,
    }


def load_parakeet_model(model_id: str, device: str) -> tuple[Any, Any]:
    """Load the Parakeet processor and model as one pair, ready for inference.

    transformers is imported inside the function for the same reason libs/diarize.py does it:
    it pulls torch, and the Gunicorn master must be able to import this module without either.

    The device comes from COMPUTE_TYPE rather than `device_map="auto"`, which the model card
    uses: automatic placement would quietly ignore an operator who forced cpu or cuda, and it
    needs accelerate, which nothing else here does.

    Two settings are fixed here, both measured on 246 LibriSpeech phrases. The processor's decoder
    type is resolved once and pinned: a checkpoint that does not declare one has it inferred again
    on every token, through a call that copies the whole vocabulary, and that cost 31 ms per phrase
    - four times the GPU's share of a batch of 32. And TF32 is switched off for cuDNN, for the
    whole process: with it, cuDNN picks its convolution algorithm by batch size, and one phrase in
    246 lost its final period at batch 8 and 32. Without it every phrase decodes token for token
    as it does alone, at the same speed. Whisper in fp16 and faster-whisper do not use TF32, so
    only fp32 convolutions elsewhere (the diarizer's, or Whisper's with WHISPER_FP16=false) see it.
    """
    import torch
    from transformers import AutoModelForTDT, AutoProcessor

    torch.backends.cudnn.allow_tf32 = False
    os.makedirs(config.PARAKEET_DOWNLOAD_ROOT, exist_ok=True)
    processor = AutoProcessor.from_pretrained(model_id, cache_dir=config.PARAKEET_DOWNLOAD_ROOT)
    processor.decoder_type = processor._decoder_type
    model = AutoModelForTDT.from_pretrained(model_id, cache_dir=config.PARAKEET_DOWNLOAD_ROOT)
    model.to(device)
    model.eval()
    return processor, model


def get_model(device: str | None = None, model_name: str | None = None) -> dict[str, Any]:
    """The engine of one Parakeet model, loaded on first use; every later call returns the same engine.

    `model_name` None means PARAKEET_MODEL, the single-model deployment's id. init_model_pool
    calls this once per pool slot, so the first call loads and the others share.
    """
    model_id = config.PARAKEET_MODEL if model_name is None else model_name
    device = resolve_device(device)
    key = (device, model_id)
    with ENGINES_LOCK:
        engine = ENGINES.get(key)
        if engine is None:
            engine = batching.start_engine(load_parakeet_model(model_id, device), f"parakeet {model_id}", serve_batch)
            ENGINES[key] = engine
    return engine


def read_mono_16k(bio: io.BytesIO) -> np.ndarray:
    """Decode a WAV buffer into the mono float32 waveform the processor accepts.

    Refuses another sampling rate rather than resampling: libs/audio.py already hands on 16 kHz
    mono for every request, so a mismatch means the caller skipped it.
    """
    data, sample_rate = sf.read(bio)
    if sample_rate != TARGET_SAMPLE_RATE:
        raise ValueError(f"Parakeet needs {TARGET_SAMPLE_RATE} Hz audio, got {sample_rate} Hz.")
    if data.ndim == 2:
        data = data.mean(axis=1)
    return data.astype(np.float32)


def serve_batch(model: tuple[Any, Any], batch: list[dict[str, Any]]) -> None:
    """Decode a batch: everything up to BATCH_FRAMES together, the rest alone."""
    short = [item for item in batch if item["frames"] <= BATCH_FRAMES]
    logger.debug("Decoding a batch of %d, %d of them together", len(batch), len(short))
    if short:
        batching.run_safely(short, decode_batch, model, short)
    for item in batch:
        if item["result"] is None and item["error"] is None:
            batching.run_safely([item], decode_batch, model, [item])


def decode_batch(model: tuple[Any, Any], batch: list[dict[str, Any]]) -> None:
    """Decode every item of a batch in one generate call and set each its text and token timestamps.

    Each item's features were computed on its own, so they are exactly what a decode of that item
    alone would see; the batch pads them with the zeros and the mask the feature extractor itself
    gives a padded batch. The encoder masks padding in its subsampling, its convolutions and its
    attention, and the transducer decodes every row on its own, so a row's tokens do not depend
    on its batch-mates.
    """
    import torch

    processor, decoder = model
    longest = max(item["frames"] for item in batch)
    width = batch[0]["features"].shape[-1]
    features = torch.zeros((len(batch), longest, width), dtype=batch[0]["features"].dtype)
    mask = torch.zeros((len(batch), longest), dtype=torch.bool)
    for row, item in enumerate(batch):
        features[row, : item["frames"]] = item["features"]
        mask[row, : item["frames"]] = True
    with torch.inference_mode():
        output = decoder.generate(
            input_features=features.to(decoder.device),
            attention_mask=mask.to(decoder.device),
            return_dict_in_generate=True,
        )
    texts, timestamps = processor.decode(output.sequences, durations=output.durations, skip_special_tokens=True)
    for item, text, tokens in zip(batch, texts, timestamps, strict=True):
        item["result"] = {"text": text, "tokens": list(tokens)}


def transcribe_tokens(
    bio: io.BytesIO, model: dict[str, Any] | None = None, device: str | None = None
) -> tuple[str, list[dict]]:
    """Transcribe a WAV buffer, returning the text and its token-level timestamps in seconds.

    `model` is an engine from get_model; the call waits for the batch it joins. The features are
    computed here, on the caller's thread, so the engine thread spends its time on the GPU.
    """
    engine = get_model(device=device) if model is None else model
    processor = engine["model"][0]
    inputs = processor.feature_extractor(read_mono_16k(bio), sampling_rate=TARGET_SAMPLE_RATE, return_tensors="pt")
    frames = int(inputs["attention_mask"][0].sum())
    item: dict[str, Any] = {"features": inputs["input_features"][0, :frames], "frames": frames}
    result = batching.submit_request(engine, item)
    return result["text"], result["tokens"]


def group_tokens(tokens: list[dict]) -> list[dict]:
    """Group subword tokens into words, each with its own start and end.

    Words, not phrases. Speakers hand over faster than any pause threshold that would still
    keep one person's sentence together, so a phrase built by splitting on silence swallows the
    handover and is then attributed whole to whoever spoke longer. A word is short enough to
    belong to one speaker, and libs/align.py merges consecutive words back into runs.

    A token that begins with whitespace starts a new word; anything else, including punctuation,
    continues the current one. The tokens are concatenated exactly as the decoder emitted them.
    """
    words: list[dict] = []
    for token in tokens:
        chunk = token["token"]
        start, end = float(token["start"]), float(token["end"])
        if words and not chunk[:1].isspace():
            words[-1]["end"] = max(words[-1]["end"], end)
            words[-1]["text"] += chunk
            continue
        words.append({"start": start, "end": end, "text": chunk})
    return words


def get_stt_result(
    bio: io.BytesIO,
    model: Any = None,
    device: str | None = None,
    language: str | None = None,
    prompt: str | None = None,
) -> dict:
    """Transcribe a WAV buffer and return `{"text", "language", "segments"}` from one decode.

    `language` is accepted and ignored, so this module is interchangeable with libs/stt.py:
    the model detects the language itself and takes no such argument. GET /api/models reports
    `accepts_language: false` so a caller is told rather than left to wonder. The reported
    language is always None, because the model does not say which one it detected. `segments`
    are the words get_stt_segments returns, from the same decode. `prompt` is accepted and
    ignored as well: the model takes no prompt. Its text is never logged.
    """
    if language:
        logger.debug("Parakeet detects the language itself; ignoring the requested %s", language)
    if prompt:
        logger.debug("Parakeet takes no prompt; ignoring the one the request carried")
    text, tokens = transcribe_tokens(bio, model=model, device=device)
    segments = group_tokens(tokens)
    logger.debug("Transcribed %d words from %d tokens", len(segments), len(tokens))
    return {"text": text.strip(), "language": None, "segments": segments}


def get_stt_bio(
    bio: io.BytesIO,
    model: Any = None,
    device: str | None = None,
    language: str | None = None,
) -> str:
    """Transcribe a WAV buffer and return the text alone; see get_stt_result."""
    return get_stt_result(bio, model=model, device=device, language=language)["text"]


def get_stt_segments(
    bio: io.BytesIO,
    model: Any = None,
    device: str | None = None,
    language: str | None = None,
) -> list[dict]:
    """Transcribe a WAV buffer and return its words with their times, for the speaker join; see get_stt_result."""
    return get_stt_result(bio, model=model, device=device, language=language)["segments"]


def main():
    """CLI entry point: transcribe the audio file given as the first argument."""
    logs.setup_logging()
    if len(sys.argv) < 2:
        logger.error("Usage: python3 -m libs.parakeet <16 kHz mono wav>")
        sys.exit(1)

    filename = sys.argv[1]
    start_time = time.monotonic()
    try:
        with open(filename, "rb") as audio_file:
            text = get_stt_bio(io.BytesIO(audio_file.read()))
    except Exception as exc:
        logger.error("%s: %s\n%s", type(exc).__name__, exc, traceback.format_exc())
        sys.exit(1)
    logger.info("STT: %s (%.3f sec)", text, time.monotonic() - start_time)


if __name__ == "__main__":
    main()

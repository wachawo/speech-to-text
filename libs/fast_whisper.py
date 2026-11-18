#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""faster-whisper (CTranslate2) as a transcription backend that decodes concurrent requests in one batch."""

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
from libs import batching, config, logs, stt

logger = logging.getLogger(__name__)

# The name this backend is selected by, in STT_MODELS and in a request's `model`.
BACKEND_NAME = "faster-whisper"

# The rate the feature extractor is built for; libs/audio.py already hands on exactly this.
TARGET_SAMPLE_RATE = 16000

# Mel frames in one encoder window (30 s). A request whose audio fits in one window is decoded
# together with whatever else is waiting; a longer one is decoded alone, window after window.
WINDOW_FRAMES = 3000

# The decoding settings libs/stt.py gets from whisper's defaults, set here explicitly so both
# backends decide alike: a window whose no-speech probability is over 0.6 while its average
# log-probability is under -1.0 is silence, and the first timestamp may not be later than 1 s.
NO_SPEECH_THRESHOLD = 0.6
LOG_PROB_THRESHOLD = -1.0
MAX_INITIAL_TIMESTAMP = 1.0

# Seconds per timestamp token, and the longest decoded sequence, prompt included. Both are the
# model's own and the same for every checkpoint.
TIME_PRECISION = 0.02
MAX_LENGTH = 448

# One engine per (device, model) in this process: the weights and the thread that decodes on
# them. get_model hands out the same engine for every instance of a pool, so a pool of N holds
# one copy of the weights and lets N requests into the engine at once - which is also the
# largest batch it can form.
ENGINES: dict[tuple[str, str], dict[str, Any]] = {}
ENGINES_LOCK = threading.Lock()


def resolve_device(device: str | None = None) -> str:
    """Resolve "auto" to cuda/cpu by asking CTranslate2, and reject a device it cannot serve."""
    import ctranslate2

    device = config.COMPUTE_TYPE if device is None else device
    has_cuda = ctranslate2.get_cuda_device_count() > 0
    if device == "auto":
        device = "cuda" if has_cuda else "cpu"
    if device not in stt.SUPPORTED_DEVICES:
        raise ValueError("Device must be 'cpu' or 'cuda'.")
    if device == "cuda" and not has_cuda:
        raise RuntimeError(
            "CTranslate2 sees no CUDA device; its aarch64 PyPI wheels are CPU-only, build it with CTRANSLATE2=source."
        )
    return device


def resolve_languages(model_name: str) -> list[str]:
    """The language codes a checkpoint accepts, without loading it: whisper's rule, plus distil-* is English only."""
    if config.build_model_name(model_name).lower().startswith("distil-"):
        return ["en"]
    return stt.resolve_languages(model_name)


def normalize_language_code(language: str) -> str | None:
    """Map a requested language onto a Whisper code; the vocabulary is whisper's own."""
    return stt.normalize_language_code(language)


def get_language_name(code: str | None) -> str | None:
    """The lower-case English name whisper gives a language code (`en` -> `english`), or None."""
    return stt.get_language_name(code)


def list_aliases(model_name: str) -> list[str]:
    """Other names of the same checkpoint (`turbo` and `large-v3-turbo`), as whisper names them."""
    return stt.list_aliases(model_name)


def list_known_models() -> list[str]:
    """Every checkpoint name faster-whisper can download, or whisper's names when it is not installed."""
    try:
        from faster_whisper import available_models
    except ImportError:
        return stt.list_known_models()
    return sorted(available_models())


def is_installed(model_name: str) -> bool:
    """Whether the converted checkpoint is already on disk; False when faster-whisper itself is not installed."""
    try:
        from faster_whisper.utils import download_model
    except ImportError:
        return False
    if config.is_model_path(model_name):
        return os.path.isdir(model_name)
    try:
        download_model(model_name, local_files_only=True, cache_dir=config.WHISPER_DOWNLOAD_ROOT)
    except Exception:
        return False
    return True


def describe_backend(model_name: str | None = None) -> dict:
    """Describe one checkpoint for GET /api/models, loading nothing; None means WHISPER_MODEL."""
    model_name = config.WHISPER_MODEL if model_name is None else model_name
    languages = resolve_languages(model_name)
    return {
        "backend": BACKEND_NAME,
        "model": model_name,
        "aliases": list_aliases(model_name),
        "status": "installed" if is_installed(model_name) else "absent",
        "multilingual": languages != ["en"],
        "accepts_language": True,
        "languages_source": "derived",
        "languages": languages,
        "default_language": config.WHISPER_LANGUAGE,
    }


def load_whisper_model(model_name: str, device: str) -> Any:
    """Load the CTranslate2 model, downloading the converted checkpoint into WHISPER_DOWNLOAD_ROOT if needed."""
    from faster_whisper import WhisperModel

    os.makedirs(config.WHISPER_DOWNLOAD_ROOT, exist_ok=True)
    return WhisperModel(
        model_name,
        device=device,
        compute_type=config.FASTER_WHISPER_COMPUTE_TYPE,
        download_root=config.WHISPER_DOWNLOAD_ROOT,
    )


def get_model(device: str | None = None, model_name: str | None = None) -> dict[str, Any]:
    """The engine of one checkpoint, loaded on first use; every later call returns the same engine.

    `model_name` None means WHISPER_MODEL, the single-model deployment's checkpoint. init_model_pool
    calls this once per pool slot, so the first call loads and the others share.
    """
    model_name = config.WHISPER_MODEL if model_name is None else model_name
    device = resolve_device(device)
    key = (device, model_name)
    with ENGINES_LOCK:
        engine = ENGINES.get(key)
        if engine is None:
            engine = batching.start_engine(load_whisper_model(model_name, device), f"{BACKEND_NAME} {model_name}", serve_batch)
            ENGINES[key] = engine
    return engine


def read_waveform(bio: io.BytesIO) -> np.ndarray:
    """Decode a 16 kHz WAV buffer into a mono float32 waveform with its peak at 1.0, as libs/stt.py does.

    The same level normalisation as the openai-whisper backend, so the two hear the same input.
    Another sampling rate is refused rather than resampled: libs/audio.py always sends 16 kHz.
    """
    data, sample_rate = sf.read(bio, dtype="float32")
    if sample_rate != TARGET_SAMPLE_RATE:
        raise ValueError(f"faster-whisper needs {TARGET_SAMPLE_RATE} Hz audio, got {sample_rate} Hz.")
    if data.ndim == 2:
        data = data.mean(axis=1)
    peak = np.abs(data).max() if data.size else 0.0
    if peak > 0:
        data = data / peak
    return data.astype(np.float32)


def serve_batch(model: Any, batch: list[dict[str, Any]]) -> None:
    """Decode a batch: everything that fits one window together, in halves if the GPU runs short, the rest alone."""
    short = [item for item in batch if item["frames"] <= WINDOW_FRAMES]
    logger.debug("Decoding a batch of %d, %d of them in one window", len(batch), len(short))
    if short:
        batching.decode_in_halves(short, decode_window_batch, model)
    for item in batch:
        if item["result"] is None and item["error"] is None:
            batching.run_safely([item], decode_alone, model, item)


def build_tokenizer(model: Any, language: str | None) -> Any:
    """faster-whisper's tokenizer for one request: transcribe, in the given language."""
    from faster_whisper.tokenizer import Tokenizer

    return Tokenizer(model.hf_tokenizer, model.model.is_multilingual, task="transcribe", language=language)


def detect_languages(model: Any, encoder_output: Any, batch: list[dict[str, Any]]) -> list[str]:
    """The language of every item: the one it was given, or the one detected on its own window.

    Detected on the encoder output the decode uses rather than on a second encoding, so a batch
    costs one encoder pass. faster-whisper's own transcribe encodes once more for detection, with
    one extra frame of padding, which can only matter when two languages are nearly tied.
    """
    if not model.model.is_multilingual:
        return ["en"] * len(batch)
    wanted = [item["language"] for item in batch]
    if all(wanted):
        return wanted
    detected = model.model.detect_language(encoder_output)
    return [language or detected[index][0][0][2:-2] for index, language in enumerate(wanted)]


def build_prompt(model: Any, tokenizer: Any, prompt: str | None) -> list[int]:
    """The decoder prompt: the request's prompt as previous text, then the start-of-transcript tokens."""
    previous = tokenizer.encode(" " + prompt.strip()) if prompt else []
    return model.get_prompt(tokenizer, previous, without_timestamps=False)


def decode_window_batch(model: Any, batch: list[dict[str, Any]]) -> None:
    """Decode every item of a batch whose audio fits one window: one encoder pass, one batched beam search.

    The result of each item is what faster-whisper's own transcribe gives for that audio with the
    settings below, window for window. An item whose window ends inside a segment would need a
    second window, so it is left without a result and serve_batch decodes it alone from the start.
    """
    from faster_whisper.audio import pad_or_trim
    from faster_whisper.transcribe import get_compression_ratio, get_suppressed_tokens

    features = np.stack([pad_or_trim(item["features"][:, : item["frames"]]) for item in batch])
    encoder_output = model.encode(features)
    languages = detect_languages(model, encoder_output, batch)
    tokenizers = [build_tokenizer(model, language) for language in languages]
    prompts = [build_prompt(model, tokenizer, item["prompt"]) for tokenizer, item in zip(tokenizers, batch, strict=True)]
    results = model.model.generate(
        encoder_output,
        prompts,
        beam_size=config.WHISPER_BEAM_SIZE,
        patience=1,
        length_penalty=1,
        repetition_penalty=1,
        no_repeat_ngram_size=0,
        max_length=MAX_LENGTH,
        return_scores=True,
        return_no_speech_prob=True,
        suppress_blank=True,
        suppress_tokens=get_suppressed_tokens(tokenizers[0], [-1]),
        max_initial_timestamp_index=int(round(MAX_INITIAL_TIMESTAMP / TIME_PRECISION)),
    )
    for item, tokenizer, language, result in zip(batch, tokenizers, languages, results, strict=True):
        tokens = result.sequences_ids[0]
        avg_logprob = result.scores[0] * len(tokens) / (len(tokens) + 1)
        decoded = {
            "tokens": tokens,
            "avg_logprob": avg_logprob,
            "no_speech_prob": result.no_speech_prob,
            "compression_ratio": get_compression_ratio(tokenizer.decode(tokens).strip()),
        }
        segments = split_window(model, tokenizer, item["frames"], decoded)
        if segments is not None:
            item["result"] = {"language": language, "segments": segments}


def split_window(model: Any, tokenizer: Any, frames: int, decoded: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The segments of one decoded window, or None when its audio did not end inside this window.

    Silence (no_speech_prob over NO_SPEECH_THRESHOLD with avg_logprob under LOG_PROB_THRESHOLD)
    has no segments, as faster-whisper skips it. Segments of no length or no text are dropped as
    faster-whisper drops them.
    """
    if decoded["no_speech_prob"] > NO_SPEECH_THRESHOLD and decoded["avg_logprob"] < LOG_PROB_THRESHOLD:
        return []
    pieces, seek, unused_single_ending = model._split_segments_by_timestamps(
        tokenizer=tokenizer,
        tokens=decoded["tokens"],
        time_offset=0.0,
        segment_size=frames,
        segment_duration=frames * model.feature_extractor.time_per_frame,
        seek=0,
    )
    if seek < frames:
        return None
    segments = []
    for piece in pieces:
        text = tokenizer.decode(piece["tokens"])
        if piece["start"] == piece["end"] or not text.strip():
            continue
        segments.append(
            {
                "seek": 0,
                "start": piece["start"],
                "end": piece["end"],
                "text": text,
                "tokens": piece["tokens"],
                "temperature": 0.0,
                "avg_logprob": decoded["avg_logprob"],
                "compression_ratio": decoded["compression_ratio"],
                "no_speech_prob": decoded["no_speech_prob"],
            }
        )
    return segments


def decode_alone(model: Any, item: dict[str, Any]) -> None:
    """Decode one item by faster-whisper's own transcribe, window after window, with the same settings."""
    pieces, info = model.transcribe(
        item["waveform"],
        language=item["language"],
        task="transcribe",
        beam_size=config.WHISPER_BEAM_SIZE,
        best_of=1,
        temperature=0.0,
        condition_on_previous_text=False,
        initial_prompt=item["prompt"],
        without_timestamps=False,
        no_speech_threshold=NO_SPEECH_THRESHOLD,
        log_prob_threshold=LOG_PROB_THRESHOLD,
        max_initial_timestamp=MAX_INITIAL_TIMESTAMP,
        vad_filter=False,
    )
    segments = [
        {
            "seek": piece.seek,
            "start": piece.start,
            "end": piece.end,
            "text": piece.text,
            "tokens": piece.tokens,
            "temperature": piece.temperature,
            "avg_logprob": piece.avg_logprob,
            "compression_ratio": piece.compression_ratio,
            "no_speech_prob": piece.no_speech_prob,
        }
        for piece in pieces
    ]
    item["result"] = {"language": info.language, "segments": segments}


def submit_request(engine: dict[str, Any], waveform: np.ndarray, language: str | None, prompt: str | None) -> dict:
    """Hand one waveform to the engine and wait for its decode; raises whatever the decode raised.

    The features are computed here, on the caller's thread, so the engine thread spends its time
    on the GPU rather than on numpy.
    """
    features = engine["model"].feature_extractor(waveform)
    item: dict[str, Any] = {
        "waveform": waveform,
        "features": features,
        "frames": features.shape[-1] - 1,
        "language": language,
        "prompt": prompt or None,
    }
    return batching.submit_request(engine, item)


def build_segment_details(segments: list[dict[str, Any]]) -> list[dict]:
    """The segments with every field whisper reports, as plain JSON values, numbered from 0 like whisper's."""
    return [
        {
            "id": number,
            "seek": int(segment["seek"]),
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": segment["text"],
            "tokens": [int(token) for token in segment["tokens"]],
            "temperature": float(segment["temperature"]),
            "avg_logprob": float(segment["avg_logprob"]),
            "compression_ratio": float(segment["compression_ratio"]),
            "no_speech_prob": float(segment["no_speech_prob"]),
        }
        for number, segment in enumerate(segments)
    ]


def normalize_language(language: str | None) -> str | None:
    """None falls back to WHISPER_LANGUAGE, "auto" and "" mean autodetect (None), anything else is passed on."""
    value = config.WHISPER_LANGUAGE if language is None else language
    value = (value or "").strip().lower()
    return None if value in stt.AUTODETECT_VALUES else value


def get_stt_result(
    bio: io.BytesIO,
    model: dict[str, Any] | None = None,
    device: str | None = None,
    language: str | None = None,
    prompt: str | None = None,
) -> dict:
    """Transcribe a WAV buffer and return `{"text", "language", "segments", "segment_details"}`, as libs/stt.py does.

    `model` is an engine from get_model; the call waits for the batch it joins. Decoding is at
    temperature 0 with a beam of WHISPER_BEAM_SIZE and no previous-text conditioning, the
    settings of libs/stt.py, so the same audio gives the same text. `prompt` is whisper's
    initial prompt and is never logged.
    """
    engine = get_model(device=device) if model is None else model
    waveform = read_waveform(bio)
    result = submit_request(engine, waveform, normalize_language(language), prompt)
    pieces = result["segments"]
    segments = [{"start": float(piece["start"]), "end": float(piece["end"]), "text": piece["text"]} for piece in pieces]
    text = "".join(piece["text"] for piece in pieces).strip()
    logger.debug("Transcribed %d chars in %d segments (language %s)", len(text), len(segments), result["language"])
    return {
        "text": text,
        "language": result["language"],
        "segments": segments,
        "segment_details": build_segment_details(pieces),
    }


def get_stt_bio(
    bio: io.BytesIO,
    model: dict[str, Any] | None = None,
    device: str | None = None,
    language: str | None = None,
) -> str:
    """Transcribe a WAV buffer and return the text alone; see get_stt_result."""
    return get_stt_result(bio, model=model, device=device, language=language)["text"]


def get_stt_segments(
    bio: io.BytesIO,
    model: dict[str, Any] | None = None,
    device: str | None = None,
    language: str | None = None,
) -> list[dict]:
    """Transcribe a WAV buffer and return its segments with their times; see get_stt_result."""
    return get_stt_result(bio, model=model, device=device, language=language)["segments"]


def main():
    """CLI entry point: transcribe the 16 kHz mono WAV given as the first argument."""
    logs.setup_logging()
    if len(sys.argv) < 2:
        logger.error("Usage: python3 -m libs.fast_whisper <16 kHz mono wav>")
        sys.exit(1)
    start_time = time.monotonic()
    try:
        with open(sys.argv[1], "rb") as audio_file:
            text = get_stt_bio(io.BytesIO(audio_file.read()))
    except Exception as exc:
        logger.error("%s: %s\n%s", type(exc).__name__, exc, traceback.format_exc())
        sys.exit(1)
    logger.info("STT: %s (%.3f sec)", text, time.monotonic() - start_time)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The OpenAI-compatible surface under /v1: its form options, its transcription answer and its model list."""

import io
import logging
import re
from typing import Any

import soundfile as sf
from flask import jsonify

# Local imports
from libs import backends, config, metrics, registry, speech_gate
from libs.errors import build_openai_error_response, get_request_id

logger = logging.getLogger(__name__)

TRANSCRIPTIONS_PATH = "/v1/audio/transcriptions"
MODELS_PATH = "/v1/models"

# The answers this service can give. `srt` and `vtt` are OpenAI formats it does not produce.
RESPONSE_FORMATS = ("json", "text", "verbose_json")

# Segment timestamps exist; word timestamps would need whisper's word_timestamps=True, which
# changes the transcription itself (see AGENTS.md), and Parakeet's words are not phrases.
TIMESTAMP_GRANULARITIES = ("segment",)

# Both spellings of the list field: OpenAI's SDKs send `timestamp_granularities[]`.
GRANULARITY_FIELDS = ("timestamp_granularities[]", "timestamp_granularities")

# Whisper's special tokens (`<|endoftext|>`, `<|en|>`, `<|0.00|>`): its tokenizer refuses to encode
# them in a prompt, which would fail the decode as a 500 for what is the client's input.
SPECIAL_TOKEN_PATTERN = re.compile(r"<\|[^|]*\|>")


def read_temperature_refusal(raw: str | None) -> Any:
    """The 400 for a `temperature` other than 0, or None: decoding is deterministic at 0 only."""
    if raw is None or not raw.strip():
        return None
    try:
        temperature = float(raw)
    except ValueError:
        return build_openai_error_response("Invalid temperature", 400, param="temperature")
    if temperature != 0:
        return build_openai_error_response("Unsupported temperature", 400, param="temperature")
    return None


def read_granularity_refusal(form: Any) -> Any:
    """The 400 for a timestamp granularity other than `segment`, or None."""
    for field in GRANULARITY_FIELDS:
        for granularity in form.getlist(field):
            if granularity.strip().lower() not in TIMESTAMP_GRANULARITIES:
                return build_openai_error_response("Unsupported timestamp granularity", 400, param="timestamp_granularities")
    return None


def read_transcription_options(form: Any) -> tuple[dict[str, Any] | None, Any]:
    """Read the OpenAI-only form fields: (options, None), or (None, the 400 to answer).

    `options` holds `response_format` and `prompt`; `model` and `language` are resolved by the
    server exactly as on /api/stt. Every check runs before the audio is decoded.
    """
    refusal = read_temperature_refusal(form.get("temperature"))
    if refusal is not None:
        return None, refusal
    response_format = (form.get("response_format") or "json").strip().lower()
    if response_format not in RESPONSE_FORMATS:
        return None, build_openai_error_response("Unsupported response format", 400, param="response_format")
    refusal = read_granularity_refusal(form)
    if refusal is not None:
        return None, refusal
    prompt = (form.get("prompt") or "").strip() or None
    if prompt is not None and SPECIAL_TOKEN_PATTERN.search(prompt):
        return None, build_openai_error_response("Invalid prompt", 400, param="prompt")
    return {"response_format": response_format, "prompt": prompt}, None


def build_phrase_segment(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One verbose_json segment made of a backend's words, or none when nothing was said.

    For a backend without per-segment details (Parakeet): the whole input is one window, so
    `seek` is 0, and it decodes greedily, so `temperature` is 0. The confidence figures it does
    not produce are null and `tokens` is empty, rather than numbers it never reported.
    """
    text = "".join(word["text"] for word in words)
    if not text.strip():
        return []
    return [
        {
            "id": 0,
            "seek": 0,
            "start": float(words[0]["start"]),
            "end": max(float(word["end"]) for word in words),
            "text": text,
            "tokens": [],
            "temperature": 0.0,
            "avg_logprob": None,
            "compression_ratio": None,
            "no_speech_prob": None,
        }
    ]


def read_duration(wav_bio: io.BytesIO) -> float:
    """The length of a WAV buffer in seconds, from its header; the buffer is rewound."""
    wav_bio.seek(0)
    try:
        return float(sf.info(wav_bio).duration)
    finally:
        wav_bio.seek(0)


def read_language_name(spec: dict[str, Any], code: str | None) -> str | None:
    """The full lower-case name of the language the backend reported, as OpenAI gives it, or None.

    None for a backend that does not report the language it detected (Parakeet): a name is never
    guessed from what the request asked for.
    """
    get_language_name = getattr(backends.transcriber_for_backend(spec["backend"]), "get_language_name", None)
    if get_language_name is None:
        return None
    return get_language_name(code)


def transcribe_wav(wav_bio: io.BytesIO, model: Any, language: str | None, spec: dict[str, Any], prompt: str | None) -> dict:
    """One decode by the spec's backend, through the speech gate, as `{text, language, language_code, duration, segments}`.

    The text is built as /api/stt builds it: the transcriber's own text without the gate, the
    joined texts of the segments the gate keeps with it. `segments` are Whisper's own segments
    with every field it reports, or for a backend that reports none one segment made of its words.
    """
    with metrics.measure_inference(spec["id"], spec["backend"]):
        result = backends.transcriber_for_backend(spec["backend"]).get_stt_result(
            wav_bio, model=model, language=language, prompt=prompt
        )
    details = result.get("segment_details")
    segments = result["segments"] if details is None else details
    text = result["text"]
    if config.SPEECH_GATE:
        segments = speech_gate.gate_wav(wav_bio, segments, get_request_id())
        text = "".join(segment["text"] for segment in segments).strip()
    if details is None:
        segments = build_phrase_segment(segments)
    return {
        "text": text,
        "language": read_language_name(spec, result["language"]),
        "language_code": result["language"],
        "duration": read_duration(wav_bio),
        "segments": segments,
    }


def build_transcription_response(result: dict, response_format: str) -> Any:
    """The answer in the format the request asked for: OpenAI's json, text or verbose_json."""
    if response_format == "text":
        return result["text"], 200, {"Content-Type": "text/plain; charset=utf-8"}
    if response_format == "verbose_json":
        body = {
            "task": "transcribe",
            "language": result["language"],
            "duration": result["duration"],
            "text": result["text"],
            "segments": result["segments"],
        }
        return jsonify(body), 200
    return jsonify({"text": result["text"]}), 200


def list_openai_models() -> dict[str, Any]:
    """Every loaded model, by the same id /api/models gives it, in OpenAI's model list shape."""
    data = [
        {"id": spec["id"], "object": "model", "created": 0, "owned_by": spec["backend"]} for spec in registry.get_model_specs()
    ]
    return {"object": "list", "data": data}


def main():
    """No-op entry point: this module is imported for its OpenAI-compatible helpers."""
    pass


if __name__ == "__main__":
    main()

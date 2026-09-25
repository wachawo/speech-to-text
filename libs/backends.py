#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Which module transcribes. Resolved at call time so STT_BACKEND and STT_MODELS are obeyed, not cached."""

import logging
from types import ModuleType
from typing import Any

# Local imports
from libs import config, parakeet, stt

logger = logging.getLogger(__name__)

# Every value here exports the same names with the same signatures - get_model, get_stt_result,
# get_stt_bio, get_stt_segments, describe_backend, resolve_languages, list_aliases and
# list_known_models - so callers resolve the MODULE and then call it by name. A dispatcher that
# resolved the function instead would silently defeat every test that patches
# `stt.get_stt_result`.
TRANSCRIBERS: dict[str, ModuleType] = {"whisper": stt, "parakeet": parakeet}

DEFAULT_TRANSCRIBER = "whisper"

# The value that asks the backend to detect the language rather than be told it.
AUTODETECT = "auto"

# Error categories a requested language can earn.
INVALID_LANGUAGE = "Invalid language"
UNSUPPORTED_LANGUAGE = "Unsupported language"


def transcriber_name() -> str:
    """The configured backend name, falling back to the default when it names nothing real."""
    name = config.STT_BACKEND
    if name in TRANSCRIBERS:
        return name
    logger.warning("STT_BACKEND=%s is not a known backend; using %s", name, DEFAULT_TRANSCRIBER)
    return DEFAULT_TRANSCRIBER


def transcriber_for_backend(name: str) -> ModuleType:
    """The module of one named backend; raises KeyError for a name that is not a backend."""
    return TRANSCRIBERS[name]


def resolve_self_detected_language(language: str, spec: dict[str, Any], explicit: bool) -> tuple[str | None, str | None]:
    """Check a hint for a backend that detects the language itself and takes no language argument.

    A caller that did not choose a model gets today's behaviour: the value is accepted and
    ignored, whatever it is. One that did choose read the catalogue, so a code outside that
    model's list is refused; an id the table does not cover accepts anything.
    """
    if not explicit:
        return language, None
    languages = transcriber_for_backend(spec["backend"]).resolve_languages(spec["id"])
    if languages is None or language in languages:
        return language, None
    return None, UNSUPPORTED_LANGUAGE


def resolve_language_code(language: str | None, spec: dict[str, Any]) -> tuple[str | None, str | None]:
    """Map a requested language onto the code the model's backend takes, without consulting the model's own list.

    Returns (code to pass on, None), or (None, INVALID_LANGUAGE) for a value that is no language
    at all. This is the whole check a request got before models were selectable. A backend that
    detects the language itself has no table to check against, so its value passes unchanged.
    """
    if language is None:
        return None, None
    if language == AUTODETECT:
        return AUTODETECT, None
    module = transcriber_for_backend(spec["backend"])
    if not hasattr(module, "normalize_language_code"):
        return language, None
    code = module.normalize_language_code(language)
    if code is None:
        return None, INVALID_LANGUAGE
    return code, None


def is_unlisted_language_forgiven(code: str, spec: dict[str, Any], languages: list[str]) -> bool:
    """Whether a request that did not choose its model may hand this model a code outside its list.

    Two cases keep the leniency every request had before models were selectable. An English-only
    checkpoint has always been handed any known code and quietly decoded English, and the
    response says `en`. A checkpoint whose name matches no known one (a fine-tune at
    `/models/my-large-v3-finetune.pt`) has a list that is only a guess from that name, so the
    code is passed on rather than refused on the guess.
    """
    if len(languages) == 1:
        logger.warning("Model %s knows only %s; transcribing a %s request anyway", spec["id"], languages[0], code)
        return True
    known_models = transcriber_for_backend(spec["backend"]).list_known_models()
    if spec["id"].lower() not in known_models:
        logger.warning("Model %s is no known checkpoint, so its languages are a guess; passing %s on", spec["id"], code)
        return True
    return False


def resolve_language(language: str | None, spec: dict[str, Any], explicit: bool) -> tuple[str | None, str | None]:
    """Resolve a requested language against what the chosen model actually knows.

    Returns (code to pass on, None), or (None, error category), which the caller turns into a
    refusal. `explicit` is whether the request named its model. A shape check cannot do this
    job in either direction: `zz` looks like a code and is not one, and `russian` is not a code
    but is a spelling Whisper accepts.
    """
    module = transcriber_for_backend(spec["backend"])
    # A backend that detects the language itself has no table to check against and no argument
    # to honour; see resolve_self_detected_language for what is still refused.
    if language not in (None, AUTODETECT) and not hasattr(module, "normalize_language_code"):
        return resolve_self_detected_language(language, spec, explicit)
    code, error = resolve_language_code(language, spec)
    if code is None or code == AUTODETECT:
        return code, error
    # By the id, never the load path: `/models/tiny.en.pt` is tiny.en and knows English only.
    languages = module.resolve_languages(spec["id"])
    if code in languages:
        return code, None
    if not explicit and is_unlisted_language_forgiven(code, spec, languages):
        return code, None
    return None, UNSUPPORTED_LANGUAGE


def main():
    """No-op entry point: this module is imported for its dispatch helpers."""
    pass


if __name__ == "__main__":
    main()

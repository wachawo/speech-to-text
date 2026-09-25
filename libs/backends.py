#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Which module transcribes. Resolved at call time so STT_BACKEND is obeyed, not cached."""

import logging
from types import ModuleType

# Local imports
from libs import config, parakeet, stt

logger = logging.getLogger(__name__)

# Every value here exports the same four names with the same signatures - get_model,
# get_stt_bio, get_stt_segments and describe_backend - so callers resolve the MODULE and
# then call it by name. A dispatcher that resolved the function instead would silently
# defeat every test that patches `stt.get_stt_bio`.
TRANSCRIBERS: dict[str, ModuleType] = {"whisper": stt, "parakeet": parakeet}

DEFAULT_TRANSCRIBER = "whisper"

# The value that asks the backend to detect the language rather than be told it.
AUTODETECT = "auto"


def transcriber_name() -> str:
    """The configured backend name, falling back to the default when it names nothing real."""
    name = config.STT_BACKEND
    if name in TRANSCRIBERS:
        return name
    logger.warning("STT_BACKEND=%s is not a known backend; using %s", name, DEFAULT_TRANSCRIBER)
    return DEFAULT_TRANSCRIBER


def transcriber() -> ModuleType:
    """The module that transcribes for this deployment."""
    return TRANSCRIBERS[transcriber_name()]


def resolve_language(language: str) -> str | None:
    """Resolve a requested language against what the backend actually knows.

    Returns the code to pass on, or None when the backend knows no such language, which the
    caller turns into a refusal. A shape check cannot do this job in either direction: `zz` looks
    like a code and is not one, and `russian` is not a code but is a spelling Whisper accepts.
    """
    if language == AUTODETECT:
        return AUTODETECT
    module = transcriber()
    # A backend that detects the language itself has no table to check against and no argument
    # to honour, so the value is accepted and ignored rather than refused on a foreign table.
    if not hasattr(module, "normalize_language_code"):
        return language
    return module.normalize_language_code(language)


def main():
    """No-op entry point: this module is imported for its dispatch helpers."""
    pass


if __name__ == "__main__":
    main()

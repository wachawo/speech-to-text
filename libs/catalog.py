#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What this server can do, assembled for GET /api/models from each backend's own description."""

import logging
import traceback
from typing import Any

# Local imports
from libs import backends, config, diarize, model_pool

logger = logging.getLogger(__name__)

# A backend is only listed as available when it is switched on; the diarizer is optional and a
# deployment that never wanted it should not advertise it.
BACKENDS = ("whisper", "parakeet", "diarize")


def describe_transcriber(name: str) -> dict[str, Any]:
    """A transcription row, upgraded to "loaded" when this backend is the active one and loaded.

    Loaded means instances were loaded into the pool, not that one is free right now: with one
    instance per pool, a free count would read "installed" whenever a request held the model.
    """
    row = backends.TRANSCRIBERS[name].describe_backend()
    active = name == backends.transcriber_name()
    row["default"] = active
    if active and model_pool.model_ready():
        row["status"] = "loaded"
    return row


def describe_diarizer() -> dict[str, Any] | None:
    """The diarization row, or None when diarization is switched off entirely."""
    if not config.DIARIZE_ENABLED:
        return None
    row = diarize.describe_backend()
    row["default"] = False
    if model_pool.diarizer_ready():
        row["status"] = "loaded"
    return row


def describe_backend(name: str) -> dict[str, Any] | None:
    """One backend row, or None when that backend is not part of this deployment.

    A backend that cannot describe itself is logged and skipped rather than failing the whole
    listing: a broken optional extra must not take the endpoint with it.
    """
    try:
        if name in backends.TRANSCRIBERS:
            return describe_transcriber(name)
        if name == "diarize":
            return describe_diarizer()
    except Exception as exc:
        logger.error("Backend %s could not describe itself: %s: %s\n%s", name, type(exc).__name__, exc, traceback.format_exc())
    return None


def list_models() -> dict[str, Any]:
    """The whole catalogue: every backend this deployment carries, with its languages.

    `languages` is per row and never a union. The sets genuinely diverge, so a merged list
    would be wrong for every backend taken on its own.
    """
    rows = [row for row in (describe_backend(name) for name in BACKENDS) if row is not None]
    return {"default": backends.transcriber_name(), "models": rows}


def main():
    """No-op entry point: this module is imported for its catalogue helpers."""
    pass


if __name__ == "__main__":
    main()

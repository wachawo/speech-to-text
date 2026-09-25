#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What this server can do, assembled for GET /api/models from each backend's own description."""

import logging
import traceback
from collections.abc import Callable
from functools import partial
from typing import Any

# Local imports
from libs import backends, config, diarize, model_pool, registry

logger = logging.getLogger(__name__)

# Rows are grouped by backend in this order, and within a backend in STT_MODELS order. A backend
# is only listed as available when it is switched on; the diarizer is optional and a deployment
# that never wanted it should not advertise it.
BACKENDS = ("whisper", "parakeet", "diarize")


def describe_configured_model(spec: dict[str, Any], default_id: str) -> dict[str, Any]:
    """The row of one loaded model, upgraded to "loaded" while any instance of it exists.

    `model` is set to the canonical id, which for a file path is its basename: where the
    weights live on this host is not something the catalogue hands out.
    """
    row = backends.transcriber_for_backend(spec["backend"]).describe_backend(model_name=spec["model"])
    row["id"] = spec["id"]
    row["model"] = spec["id"]
    row["default"] = spec["id"] == default_id
    row["selectable"] = True
    row["pool_size"] = spec["pool_size"]
    row["available"] = model_pool.count_available(spec["id"])
    if model_pool.is_model_loaded(spec["id"]):
        row["status"] = "loaded"
    return row


def describe_unconfigured_backend(name: str) -> dict[str, Any]:
    """The row of a transcriber with no loaded model: its configured model, which no request can select."""
    row = backends.transcriber_for_backend(name).describe_backend()
    row["id"] = row["model"] = registry.build_model_id(row["model"])
    row["default"] = False
    row["selectable"] = False
    row["pool_size"] = 0
    row["available"] = 0
    return row


def describe_diarizer() -> dict[str, Any] | None:
    """The diarization row, or None when diarization is switched off entirely."""
    if not config.DIARIZE_ENABLED:
        return None
    row = diarize.describe_backend()
    row["id"] = row["model"]
    row["default"] = False
    row["selectable"] = False
    row["pool_size"] = config.DIARIZE_POOL_SIZE
    row["available"] = model_pool.DIARIZER_POOL.qsize()
    if not model_pool.DIARIZER_POOL.empty():
        row["status"] = "loaded"
    return row


def describe_safely(label: str, describe: Callable[[], dict[str, Any] | None]) -> list[dict[str, Any]]:
    """Run one row's description, or log and skip it when that model cannot describe itself.

    Per row, not per backend: a broken optional extra or one broken model must not take the
    rest of the listing with it.
    """
    try:
        row = describe()
    except Exception as exc:
        logger.error("Model %s could not describe itself: %s: %s\n%s", label, type(exc).__name__, exc, traceback.format_exc())
        return []
    return [] if row is None else [row]


def describe_backend_rows(name: str, specs: list[dict[str, Any]], default_id: str) -> list[dict[str, Any]]:
    """Every row one backend contributes: a row per loaded model, or its single unconfigured row."""
    if name == "diarize":
        return describe_safely(name, describe_diarizer)
    if name not in backends.TRANSCRIBERS:
        return []
    configured = [spec for spec in specs if spec["backend"] == name]
    if not configured:
        return describe_safely(name, partial(describe_unconfigured_backend, name))
    rows: list[dict[str, Any]] = []
    for spec in configured:
        rows.extend(describe_safely(spec["id"], partial(describe_configured_model, spec, default_id)))
    return rows


def list_models() -> dict[str, Any]:
    """The whole catalogue: every model this deployment carries, with its languages.

    `languages` is per row and never a union. The sets genuinely diverge, so a merged list
    would be wrong for every model taken on its own. `default` is the default model's backend,
    as it always was, and `default_model` its id.
    """
    specs = registry.get_model_specs()
    default_spec = registry.get_default_spec()
    rows: list[dict[str, Any]] = []
    for name in BACKENDS:
        rows.extend(describe_backend_rows(name, specs, default_spec["id"]))
    return {"default": default_spec["backend"], "default_model": default_spec["id"], "models": rows}


def main():
    """No-op entry point: this module is imported for its catalogue helpers."""
    pass


if __name__ == "__main__":
    main()

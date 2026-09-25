#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Which transcription models this server loads, and what a request may select among them."""

import logging
from typing import Any

# Local imports
from libs import backends, config

logger = logging.getLogger(__name__)

# Error categories a request's `model` can earn; each one is a 400. The language ones live in
# libs/backends.py beside resolve_language.
INVALID_MODEL = "Invalid model"
MODEL_NOT_LOADED = "Model not loaded"


def build_model_id(model: str) -> str:
    """The public name of a model: the value itself, or for a file path its basename without `.pt`.

    A path is where the weights live on this host, which is not the client's business: the id
    reaches the open /api/health, the catalogue and every /api/stt response.
    """
    return config.build_model_name(model)


def get_legacy_backend() -> str:
    """STT_BACKEND when it names a backend, else the default one.

    Silent on purpose: this runs on every request and every healthcheck, so the warning about
    an unknown STT_BACKEND is logged once, by validate_model_specs at startup.
    """
    if config.STT_BACKEND in backends.TRANSCRIBERS:
        return config.STT_BACKEND
    return backends.DEFAULT_TRANSCRIBER


def build_legacy_spec() -> dict[str, Any]:
    """The single spec implied by STT_BACKEND / WHISPER_MODEL / PARAKEET_MODEL / STT_POOL_SIZE.

    Computed on every call, so a changed STT_BACKEND is obeyed rather than cached.
    """
    backend = get_legacy_backend()
    model = config.PARAKEET_MODEL if backend == "parakeet" else config.WHISPER_MODEL
    return {"id": build_model_id(model), "backend": backend, "model": model, "pool_size": config.MODEL_POOL_SIZE}


def build_model_spec(entry: dict[str, Any]) -> dict[str, Any]:
    """Turn one parsed STT_MODELS entry into a spec, filling pool_size from STT_POOL_SIZE when absent."""
    pool_size = config.MODEL_POOL_SIZE if entry["pool_size"] is None else entry["pool_size"]
    return {"id": build_model_id(entry["model"]), "backend": entry["backend"], "model": entry["model"], "pool_size": pool_size}


def get_model_specs() -> list[dict[str, Any]]:
    """Every model this deployment loads, in STT_MODELS order, or the one legacy spec."""
    if not config.STT_MODELS:
        return [build_legacy_spec()]
    return [build_model_spec(entry) for entry in config.STT_MODELS]


def find_default_spec(specs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The spec STT_DEFAULT_MODEL names, or None.

    Besides every name a request may use, it accepts a file-path entry exactly as STT_MODELS
    spells it: the path is operator-side configuration, so matching it reveals nothing, while a
    request's `model` never matches a path.
    """
    wanted = config.STT_DEFAULT_MODEL.strip()
    for spec in specs:
        if config.is_model_path(spec["model"]) and spec["model"] == wanted:
            return spec
    return find_spec(wanted, specs)


def get_default_spec() -> dict[str, Any]:
    """The spec a request without `model` uses: STT_DEFAULT_MODEL when set, else the first spec."""
    specs = get_model_specs()
    if config.STT_MODELS and config.STT_DEFAULT_MODEL:
        spec = find_default_spec(specs)
        if spec is not None:
            return spec
    return specs[0]


def get_default_model_id() -> str:
    """The canonical id of the default model."""
    return get_default_spec()["id"]


def list_spec_names(spec: dict[str, Any]) -> list[str]:
    """Every lower-cased name that selects this spec: id, backend aliases and the backend:model form.

    The bare backend name is not among them: several specs share it, and which one it selects
    is decided by find_spec and resolve_request_model rather than counted as a clash.
    """
    backend = spec["backend"]
    names = [spec["id"]]
    if not config.is_model_path(spec["model"]):
        names.extend(backends.transcriber_for_backend(backend).list_aliases(spec["model"]))
    names.extend([f"{backend}:{name}" for name in list(names)])
    return list(dict.fromkeys(name.lower() for name in names))


def find_spec(name: str, specs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The spec a requested name selects, case-insensitively, or None.

    A bare backend name selects the first spec of that backend in STT_MODELS order; preferring
    the default model is resolve_request_model's job, which keeps STT_DEFAULT_MODEL=whisper
    from resolving through itself.
    """
    wanted = name.strip().lower()
    for spec in specs:
        if wanted in list_spec_names(spec):
            return spec
    for spec in specs:
        if spec["backend"] == wanted:
            return spec
    return None


def list_known_names() -> set[str]:
    """Every lower-cased name any backend could describe, loaded or not, in every accepted form.

    A configured WHISPER_MODEL / PARAKEET_MODEL counts by its name, never its path: otherwise
    `model=<that path>` would earn `Model not loaded` where any other path earns
    `Invalid model`, which confirms the host path the public id is meant to hide.
    """
    names: set[str] = set()
    for backend, module in backends.TRANSCRIBERS.items():
        models = set(module.list_known_models())
        configured = config.PARAKEET_MODEL if backend == "parakeet" else config.WHISPER_MODEL
        models.add(config.build_model_name(configured))
        for model in models:
            for name in [model, *module.list_aliases(model)]:
                names.update((name.lower(), f"{backend}:{name}".lower()))
        names.add(backend)
    return names


def is_known_model(name: str) -> bool:
    """Whether a name is a model some installed backend could describe, loaded or not."""
    return name.strip().lower() in list_known_names()


def resolve_request_model(requested: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """Map the request's `model` onto a loaded spec; returns (spec, None) or (None, error category).

    Nothing is ever loaded lazily: a name that is real but not loaded here is refused.
    """
    default = get_default_spec()
    if requested is None or not requested.strip():
        return default, None
    wanted = requested.strip().lower()
    if wanted == default["backend"]:
        return default, None
    spec = find_spec(wanted, get_model_specs())
    if spec is not None:
        return spec, None
    return None, MODEL_NOT_LOADED if is_known_model(wanted) else INVALID_MODEL


def check_backend_name_clash(spec: dict[str, Any]) -> None:
    """Refuse a spec whose id or alias is a backend name, which the bare backend name would then shadow.

    `whisper:/models/parakeet.pt` would be served as `parakeet`, and `?model=parakeet` would
    reach that Whisper file instead of the Parakeet model.
    """
    for name in list_spec_names(spec):
        if name in backends.TRANSCRIBERS:
            raise ValueError(f"STT_MODELS entry '{spec['model']}' would be served as '{name}', which is a backend name")


def check_duplicate_specs(specs: list[dict[str, Any]]) -> None:
    """Refuse two specs that one name would select, and any spec a bare backend name would shadow.

    A shared name is not proof of the same weights (two files called model.pt, or two Hugging
    Face repos with one short name), so the error names the clash rather than guessing why.
    """
    owners: dict[str, dict[str, Any]] = {}
    for spec in specs:
        check_backend_name_clash(spec)
        for name in list_spec_names(spec):
            other = owners.get(name)
            if other is not None and other is not spec:
                raise ValueError(
                    f"STT_MODELS entries '{other['model']}' and '{spec['model']}' would both be served as '{name}'"
                )
            owners[name] = spec


def check_pool_sizes(specs: list[dict[str, Any]]) -> None:
    """Refuse a spec that would load no instance, which an entry without @pool gets from STT_POOL_SIZE=0.

    An explicit `@0` is already refused by the parser; an implicit one would load nothing,
    report healthy, and leave every request for that model waiting out the acquire timeout.
    """
    for spec in specs:
        if spec["pool_size"] < 1:
            raise ValueError(
                f"STT_MODELS entry '{spec['model']}' gets STT_POOL_SIZE={spec['pool_size']}; give it an explicit @N"
            )


def warn_about_implicit_pools() -> None:
    """Point out entries that silently take STT_POOL_SIZE, which is 8 outside the Docker files."""
    implicit = [entry["model"] for entry in config.STT_MODELS if entry["pool_size"] is None]
    if len(implicit) > 1:
        logger.warning(
            "STT_MODELS entries without @pool each load STT_POOL_SIZE=%d instances (%s); give each one an explicit @N",
            config.MODEL_POOL_SIZE,
            ", ".join(implicit),
        )


def validate_model_specs() -> None:
    """Refuse at startup a model list the server cannot serve unambiguously; raises ValueError."""
    if not config.STT_MODELS:
        # Logs the fallback when STT_BACKEND names nothing real, once per process.
        backends.transcriber_name()
        if config.STT_DEFAULT_MODEL:
            logger.warning("STT_DEFAULT_MODEL=%s is ignored without STT_MODELS", config.STT_DEFAULT_MODEL)
        return
    logger.info("STT_MODELS is set; STT_BACKEND, WHISPER_MODEL and PARAKEET_MODEL do not choose what is loaded")
    for entry in config.STT_MODELS:
        if entry["backend"] not in backends.TRANSCRIBERS:
            raise ValueError(f"STT_MODELS names unknown backend '{entry['backend']}'")
    specs = get_model_specs()
    check_pool_sizes(specs)
    check_duplicate_specs(specs)
    if config.STT_DEFAULT_MODEL and find_default_spec(specs) is None:
        raise ValueError(f"STT_DEFAULT_MODEL '{config.STT_DEFAULT_MODEL}' is not in STT_MODELS")
    warn_about_implicit_pools()


def describe_model_specs() -> str:
    """One log line naming every loaded model, its pool size and which one is the default."""
    specs = get_model_specs()
    default_id = get_default_model_id()
    parts = [
        f"{spec['id']} ({spec['backend']}) x{spec['pool_size']}{' default' if spec['id'] == default_id else ''}"
        for spec in specs
    ]
    total = sum(spec["pool_size"] for spec in specs)
    return f"{', '.join(parts)} - {total} instance(s) in total"


def main():
    """No-op entry point: this module is imported for its registry helpers."""
    pass


if __name__ == "__main__":
    main()

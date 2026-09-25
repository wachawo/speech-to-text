#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""libs/registry.py: which models are loaded, and what a request may select among them."""

import logging
import re

import pytest

from libs import backends, config, model_pool, registry


def use_models(monkeypatch, raw, default=""):
    """Configure STT_MODELS and STT_DEFAULT_MODEL the way the environment would."""
    monkeypatch.setattr(config, "STT_MODELS", config.parse_model_list(raw))
    monkeypatch.setattr(config, "STT_DEFAULT_MODEL", default)


def test_legacy_mode_is_one_whisper_spec(client):
    """Without STT_MODELS the one spec comes from WHISPER_MODEL and STT_POOL_SIZE."""
    assert registry.get_model_specs() == [
        {"id": "small.en-stub", "backend": "whisper", "model": "small.en-stub", "pool_size": 1}
    ]


def test_legacy_mode_follows_stt_backend(client, monkeypatch):
    """STT_BACKEND=parakeet makes the one spec Parakeet's, with PARAKEET_MODEL."""
    monkeypatch.setattr(config, "STT_BACKEND", "parakeet")
    spec = registry.get_default_spec()
    assert (spec["backend"], spec["model"]) == ("parakeet", "nvidia/parakeet-tdt-0.6b-v3")


def test_the_first_entry_is_the_default(multi_client):
    """With no STT_DEFAULT_MODEL the first STT_MODELS entry serves requests without `model`."""
    assert registry.get_default_model_id() == "small.en-stub"


def test_stt_default_model_picks_another_entry(multi_client, monkeypatch):
    """STT_DEFAULT_MODEL accepts any name that selects an entry, the qualified form included."""
    monkeypatch.setattr(config, "STT_DEFAULT_MODEL", "whisper:tiny.en")
    assert registry.get_default_model_id() == "tiny.en"


def test_a_bare_backend_as_the_default_is_that_backends_first_entry(multi_client, monkeypatch):
    """STT_DEFAULT_MODEL=parakeet resolves without going through the default it is defining."""
    monkeypatch.setattr(config, "STT_DEFAULT_MODEL", "parakeet")
    assert registry.get_default_model_id() == "nvidia/parakeet-tdt-0.6b-v3"
    monkeypatch.setattr(config, "STT_DEFAULT_MODEL", "whisper")
    assert registry.get_default_model_id() == "small.en-stub"
    registry.validate_model_specs()


def test_an_entry_without_a_pool_takes_stt_pool_size(client, monkeypatch):
    """The size is read at call time, so a changed STT_POOL_SIZE is obeyed."""
    use_models(monkeypatch, "whisper:turbo,whisper:tiny.en@3")
    monkeypatch.setattr(config, "MODEL_POOL_SIZE", 5)
    assert [spec["pool_size"] for spec in registry.get_model_specs()] == [5, 3]


@pytest.mark.parametrize(
    ("raw", "default", "message"),
    [
        ("vosk:x", "", "unknown backend 'vosk'"),
        ("whisper:turbo,whisper:large-v3-turbo", "", "'turbo' and 'large-v3-turbo' would both be served as 'large-v3-turbo'"),
        ("whisper:turbo@1,whisper:turbo@2", "", "'turbo' and 'turbo' would both be served as 'turbo'"),
        (
            "parakeet:nvidia/parakeet-x@1,parakeet:acme/parakeet-x@1",
            "",
            "'nvidia/parakeet-x' and 'acme/parakeet-x' would both be served as 'parakeet-x'",
        ),
        ("whisper:/models/parakeet.pt@1", "", "'/models/parakeet.pt' would be served as 'parakeet', which is a backend name"),
        ("whisper:turbo", "medium", "STT_DEFAULT_MODEL 'medium' is not in STT_MODELS"),
    ],
)
def test_validation_refuses_what_cannot_be_served(client, monkeypatch, raw, default, message):
    """An unknown backend, one name for two entries, a backend name as an id, or a default nobody loads stops startup."""
    use_models(monkeypatch, raw, default)
    with pytest.raises(ValueError, match=re.escape(message)):
        registry.validate_model_specs()


def test_an_implicit_pool_of_zero_is_refused(client, monkeypatch):
    """STT_POOL_SIZE=0 would give an entry without @pool no instance, which an explicit @0 cannot."""
    use_models(monkeypatch, "whisper:tiny.en")
    monkeypatch.setattr(config, "MODEL_POOL_SIZE", 0)
    with pytest.raises(ValueError, match=re.escape("'tiny.en' gets STT_POOL_SIZE=0; give it an explicit @N")):
        registry.validate_model_specs()


def test_two_entries_of_one_backend_are_not_a_clash(multi_client):
    """The bare backend name is shared by design, so two Whisper models validate fine."""
    registry.validate_model_specs()


def test_implicit_pools_are_pointed_out(client, monkeypatch, caplog):
    """Outside Docker STT_POOL_SIZE is 8, so two entries without @pool would load sixteen models."""
    use_models(monkeypatch, "whisper:turbo,parakeet:nvidia/parakeet-tdt-0.6b-v3")
    monkeypatch.setattr(config, "MODEL_POOL_SIZE", 8)
    with caplog.at_level(logging.WARNING, logger="libs.registry"):
        registry.validate_model_specs()
    assert "explicit @N" in caplog.text
    assert "16 instance(s)" in registry.describe_model_specs()


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("tiny.en", "tiny.en"),
        ("TINY.EN", "tiny.en"),
        (" whisper:tiny.en ", "tiny.en"),
        ("parakeet", "nvidia/parakeet-tdt-0.6b-v3"),
        ("parakeet-tdt-0.6b-v3", "nvidia/parakeet-tdt-0.6b-v3"),
        ("whisper", "small.en-stub"),
        (None, "small.en-stub"),
        ("", "small.en-stub"),
    ],
)
def test_names_that_select_a_loaded_model(multi_client, requested, expected):
    """An id, an alias, the backend:model form or a bare backend all select, case-insensitively."""
    spec, error = registry.resolve_request_model(requested)
    assert error is None
    assert spec["id"] == expected


def test_a_bare_backend_prefers_the_default_model(multi_client, monkeypatch):
    """`whisper` is the default model when that is a Whisper model, not merely the first one."""
    monkeypatch.setattr(config, "STT_DEFAULT_MODEL", "tiny.en")
    spec, unused_error = registry.resolve_request_model("whisper")
    assert spec["id"] == "tiny.en"


@pytest.mark.parametrize(
    ("requested", "error"),
    [
        ("nope", "Invalid model"),
        ("medium", "Model not loaded"),
        ("turbo", "Model not loaded"),
        ("whisper:large-v3-turbo", "Model not loaded"),
    ],
)
def test_names_that_select_nothing(multi_client, requested, error):
    """A real model that is not loaded is told apart from a name nobody knows; neither loads anything."""
    assert registry.resolve_request_model(requested) == (None, error)


def test_a_backend_with_nothing_loaded_is_not_loaded(client):
    """`parakeet` on a Whisper-only server is a real backend with no model here."""
    assert registry.resolve_request_model("parakeet") == (None, "Model not loaded")


def test_an_unknown_parakeet_id_accepts_any_hint(client):
    """With no language table for the id, an explicit request's hint is not second-guessed."""
    spec = {"id": "nvidia/other", "backend": "parakeet", "model": "nvidia/other", "pool_size": 1}
    unused_value, error = backends.resolve_language("ja", spec, explicit=True)
    assert error is None


def test_a_file_path_is_served_under_its_basename(client, monkeypatch):
    """Where the weights live on the host never reaches a client; the file name without .pt does."""
    use_models(monkeypatch, "whisper:/opt/models/Custom@2.pt@1")
    spec = registry.get_default_spec()
    assert spec["id"] == "Custom@2"
    assert spec["model"] == "/opt/models/Custom@2.pt"
    assert registry.resolve_request_model("custom@2") == (spec, None)


def test_two_paths_with_one_basename_are_refused(client, monkeypatch):
    """Two files that would be served under the same id are ambiguous, so startup stops."""
    use_models(monkeypatch, "whisper:/a/model.pt@1,whisper:/b/model.pt@1")
    with pytest.raises(ValueError, match="'/a/model.pt' and '/b/model.pt' would both be served as 'model'"):
        registry.validate_model_specs()


def test_stt_default_model_may_name_a_path_entry_as_written(client, monkeypatch):
    """The path exactly as STT_MODELS spells it is accepted as the default, next to its basename."""
    use_models(monkeypatch, "whisper:/opt/models/Custom.pt@1,whisper:tiny.en@1", "/opt/models/Custom.pt")
    registry.validate_model_specs()
    assert registry.get_default_model_id() == "Custom"
    monkeypatch.setattr(config, "STT_DEFAULT_MODEL", "custom")
    assert registry.get_default_model_id() == "Custom"


def test_a_request_cannot_name_a_path(client, monkeypatch):
    """Only STT_DEFAULT_MODEL matches the path; a client's `model` never does."""
    use_models(monkeypatch, "whisper:/opt/models/Custom.pt@1")
    assert registry.resolve_request_model("/opt/models/Custom.pt") == (None, "Invalid model")


@pytest.mark.parametrize("raw", ["", "whisper:tiny.en@1"])
def test_the_configured_path_answers_like_any_other_path(client, monkeypatch, raw):
    """A request naming WHISPER_MODEL's path learns nothing a different path would not tell it."""
    use_models(monkeypatch, raw)
    monkeypatch.setattr(config, "WHISPER_MODEL", "/models/large-v3.pt")
    assert registry.resolve_request_model("/models/large-v3.pt") == (None, "Invalid model")
    assert registry.resolve_request_model("/models/other.pt") == (None, "Invalid model")


def test_a_path_entry_is_checked_against_its_names_languages(client, monkeypatch):
    """`/opt/tiny.en.pt` is tiny.en, English-only, so an explicit Russian request is refused."""
    use_models(monkeypatch, "whisper:/opt/tiny.en.pt@1")
    spec, unused_error = registry.resolve_request_model("tiny.en")
    assert spec["model"] == "/opt/tiny.en.pt"
    assert backends.resolve_language("ru", spec, explicit=True) == (None, "Unsupported language")
    assert backends.resolve_language("en", spec, explicit=True) == ("en", None)


def test_a_legacy_path_model_keeps_its_full_language_list(client, monkeypatch):
    """WHISPER_MODEL=/models/turbo.pt knows what turbo knows, so a code outside the default slice still passes."""
    monkeypatch.setattr(config, "WHISPER_MODEL", "/models/turbo.pt")
    spec = registry.get_default_spec()
    assert spec["id"] == "turbo"
    assert backends.resolve_language("de", spec, explicit=False) == ("de", None)


def test_an_unknown_path_named_default_keeps_the_old_leniency(client, monkeypatch):
    """A fine-tune whose name matches no checkpoint has a guessed list, so a model-less request's code passes on."""
    monkeypatch.setattr(config, "WHISPER_MODEL", "/models/my-large-v3-finetune.pt")
    spec = registry.get_default_spec()
    assert spec["id"] == "my-large-v3-finetune"
    assert backends.resolve_language("de", spec, explicit=False) == ("de", None)
    assert backends.resolve_language("zz", spec, explicit=False) == (None, "Invalid language")
    assert backends.resolve_language("de", spec, explicit=True) == (None, "Unsupported language")


def test_a_known_checkpoint_still_refuses_a_code_outside_its_list(client):
    """The default stub is a known checkpoint, so its list is certain and `de` is refused without `model` too."""
    spec = registry.get_default_spec()
    assert backends.resolve_language("de", spec, explicit=False) == (None, "Unsupported language")


def test_init_fills_one_pool_per_model(client, monkeypatch):
    """Startup loads every entry into its own queue, each instance built for its own model."""
    use_models(monkeypatch, "whisper:tiny.en@2,parakeet:nvidia/parakeet-tdt-0.6b-v3@1")
    monkeypatch.setattr(model_pool, "MODEL_POOLS", {})
    monkeypatch.setattr(model_pool, "MODELS_LOADED", {})
    model_pool.init_model_pool()
    assert {model_id: pool.qsize() for model_id, pool in model_pool.MODEL_POOLS.items()} == {
        "tiny.en": 2,
        "nvidia/parakeet-tdt-0.6b-v3": 1,
    }
    assert model_pool.MODELS_LOADED == {"tiny.en": 2, "nvidia/parakeet-tdt-0.6b-v3": 1}
    assert model_pool.acquire_model(model_id="tiny.en") == {"stub_model": "tiny.en"}


def test_init_refuses_an_invalid_list_before_loading_anything(client, monkeypatch):
    """Validation runs first, so a bad list loads no weights at all."""
    use_models(monkeypatch, "whisper:tiny.en,vosk:x")
    monkeypatch.setattr(model_pool, "MODEL_POOLS", {})
    with pytest.raises(ValueError):
        model_pool.init_model_pool()
    assert model_pool.MODEL_POOLS == {}


def test_an_unknown_stt_backend_warns_at_startup_only(client, monkeypatch, caplog):
    """The fallback is announced once by validation, not on every healthcheck that resolves the spec."""
    monkeypatch.setattr(config, "STT_BACKEND", "parrakeet")
    with caplog.at_level(logging.WARNING):
        assert client.get("/api/health").get_json()["default_model"] == "small.en-stub"
    assert "not a known backend" not in caplog.text
    with caplog.at_level(logging.WARNING):
        registry.validate_model_specs()
    assert "not a known backend" in caplog.text

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""STT_MODELS syntax: libs/config.py::parse_model_list, which runs at import time."""

import re

import pytest

from libs import config


def test_empty_means_the_single_model_deployment():
    """Nothing configured is an empty tuple, which keeps STT_BACKEND in charge."""
    assert config.parse_model_list("") == ()


def test_an_entry_without_a_pool_leaves_the_size_to_stt_pool_size():
    """`@pool` is optional; None is resolved against STT_POOL_SIZE later, at call time."""
    assert config.parse_model_list("whisper:turbo") == ({"backend": "whisper", "model": "turbo", "pool_size": None},)


def test_several_entries_with_their_pools_and_surrounding_spaces():
    """Entries are comma-separated and trimmed; each carries its own pool size."""
    entries = config.parse_model_list(" whisper:turbo@2 , parakeet:nvidia/parakeet-tdt-0.6b-v3@1 ")
    assert entries == (
        {"backend": "whisper", "model": "turbo", "pool_size": 2},
        {"backend": "parakeet", "model": "nvidia/parakeet-tdt-0.6b-v3", "pool_size": 1},
    )


def test_whisper_names_are_lower_cased_and_parakeet_ids_are_not():
    """Whisper names are case-insensitive like WHISPER_MODEL; a Hugging Face id keeps its case."""
    whisper_entry, parakeet_entry = config.parse_model_list("Whisper:Small.EN,parakeet:NVIDIA/Parakeet-X")
    assert (whisper_entry["backend"], whisper_entry["model"]) == ("whisper", "small.en")
    assert (parakeet_entry["backend"], parakeet_entry["model"]) == ("parakeet", "NVIDIA/Parakeet-X")


def test_empty_entries_are_skipped():
    """A doubled or trailing comma is not an entry."""
    assert len(config.parse_model_list("whisper:turbo,,")) == 1


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("turbo", "must look like backend:model[@pool]"),
        ("whisper:", "has no model"),
        ("whisper:turbo@x", "has an invalid pool size"),
        ("whisper:turbo@0", "has an invalid pool size"),
        ("whisper:turbo@1_0", "has an invalid pool size"),
        ("whisper:turbo@+2", "has an invalid pool size"),
        ("whisper:turbo@\uff11", "has an invalid pool size"),
    ],
)
def test_malformed_entries_fail_at_startup(raw, message):
    """A syntax error is a ValueError naming the entry, raised before any model loads."""
    with pytest.raises(ValueError, match=re.escape(message)):
        config.parse_model_list(raw)


def test_a_path_may_contain_an_at_sign_when_the_pool_is_explicit():
    """The pool starts at the LAST `@`, so a path keeps the ones before it, and its case."""
    assert config.parse_model_list("whisper:/opt/M@x.pt@1") == ({"backend": "whisper", "model": "/opt/M@x.pt", "pool_size": 1},)


@pytest.mark.parametrize(
    ("model", "name"),
    [
        ("turbo", "turbo"),
        ("nvidia/parakeet-tdt-0.6b-v3", "nvidia/parakeet-tdt-0.6b-v3"),
        ("/models/large-v3.pt", "large-v3"),
        ("/opt/small.en.pt", "small.en"),
        ("./weights/Custom", "Custom"),
    ],
)
def test_a_path_stands_for_its_file_name_without_pt(model, name):
    """Everything derived from a model's name (its id, a Whisper language list) sees the name, not the path."""
    assert config.build_model_name(model) == name

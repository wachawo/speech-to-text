#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The REAL libs/parakeet.py, which every other test replaces with a stub."""

import importlib.util
import os

MODULE_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)), "libs", "parakeet.py")


def load_real_parakeet():
    """Load libs/parakeet.py from its file, bypassing the stub in sys.modules.

    Not registered in sys.modules: the stub is what the rest of the suite needs, and replacing
    it here would leak into whatever runs next.
    """
    spec = importlib.util.spec_from_file_location("libs_parakeet_real", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def token(text, start, end):
    """Build one token timestamp as the processor emits it, in seconds."""
    return {"token": text, "start": start, "end": end}


def test_module_imports_and_exposes_the_same_surface_as_whisper():
    """Interchangeability is the whole design, so the names and their absence both matter."""
    module = load_real_parakeet()
    for name in (
        "get_model",
        "get_stt_result",
        "get_stt_bio",
        "get_stt_segments",
        "describe_backend",
        "resolve_languages",
        "list_aliases",
        "list_known_models",
        "group_tokens",
    ):
        assert callable(getattr(module, name)), name
    # It detects the language itself, so it deliberately has no language table to resolve against.
    assert not hasattr(module, "normalize_language_code")


def test_subword_tokens_join_into_one_word():
    """Tokens are subwords; a token without leading whitespace continues the current word."""
    module = load_real_parakeet()
    words = module.group_tokens([token(" Hel", 0.0, 0.2), token("lo", 0.2, 0.4)])
    assert words == [{"start": 0.0, "end": 0.4, "text": " Hello"}]


def test_whitespace_starts_a_new_word():
    """Each word keeps its own times, which is what lets align.py follow a quick handover."""
    module = load_real_parakeet()
    words = module.group_tokens([token(" so", 0.0, 0.3), token(" where", 0.3, 0.6), token(" green", 0.7, 1.0)])
    assert [w["text"] for w in words] == [" so", " where", " green"]
    assert [w["start"] for w in words] == [0.0, 0.3, 0.7]


def test_punctuation_stays_with_its_word():
    """Punctuation arrives as its own zero-length token and belongs to the word before it."""
    module = load_real_parakeet()
    words = module.group_tokens([token(" hi", 0.0, 0.2), token(",", 0.2, 0.2), token(" there", 0.3, 0.5)])
    assert [w["text"] for w in words] == [" hi,", " there"]


def test_a_first_token_without_whitespace_still_starts_a_word():
    """The decoder does not always open with a space, as the deployment host showed ("Р")."""
    module = load_real_parakeet()
    words = module.group_tokens([token("Р", 0.08, 0.16), token("е", 0.16, 0.32)])
    assert words == [{"start": 0.08, "end": 0.32, "text": "Ре"}]


def test_no_tokens_is_no_words():
    """Silence transcribes to nothing rather than to an empty word."""
    assert load_real_parakeet().group_tokens([]) == []


def test_describe_backend_reports_a_language_blind_backend():
    """The catalogue must say this backend takes no language, or ?language= becomes a lie."""
    row = load_real_parakeet().describe_backend()
    assert row["backend"] == "parakeet"
    assert row["accepts_language"] is False
    assert row["default_language"] is None
    assert len(row["languages"]) == 25
    assert "ru" in row["languages"] and "uk" in row["languages"]


def test_languages_are_refused_for_an_unknown_model_id(monkeypatch):
    """The 25 codes are carried for one id; another gets null rather than that list."""
    module = load_real_parakeet()
    monkeypatch.setattr(module.config, "PARAKEET_MODEL", "nvidia/parakeet-something-else")
    row = module.describe_backend()
    assert row["languages"] is None
    assert row["languages_source"] is None


def test_describe_backend_takes_the_model_to_describe():
    """Each loaded model gets its own row, so the id is an argument; an uncovered one reports null."""
    assert load_real_parakeet().describe_backend(model_name="nvidia/parakeet-something-else")["languages"] is None


def test_the_short_name_is_an_alias():
    """A client may name the model without its organisation prefix."""
    module = load_real_parakeet()
    assert module.list_aliases("nvidia/parakeet-tdt-0.6b-v3") == ["parakeet-tdt-0.6b-v3"]
    assert module.describe_backend()["aliases"] == ["parakeet-tdt-0.6b-v3"]


def test_languages_and_known_models_come_from_the_table():
    """The table is what the module can vouch for: its ids, and their languages or None."""
    module = load_real_parakeet()
    assert module.list_known_models() == ["nvidia/parakeet-tdt-0.6b-v3"]
    assert len(module.resolve_languages("nvidia/parakeet-tdt-0.6b-v3")) == 25
    assert module.resolve_languages("nvidia/parakeet-something-else") is None

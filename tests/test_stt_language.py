#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POST /api/stt - per-request ``language`` option."""

import io
import re

import pytest

from libs import config, model_pool
from tests.helpers import make_model_sentinel, make_wav

REQ_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def capture_language(stt_module, monkeypatch) -> dict:
    """Swap get_stt_result for a stub that records the language it was called with."""
    seen = {}

    def record_language(bio, model=None, device=None, language=None):
        """Stand in for stt.get_stt_result() and remember the language argument."""
        seen["language"] = language
        return {"text": "stub transcription", "language": language}

    monkeypatch.setattr(stt_module, "get_stt_result", record_language)
    return seen


def test_language_query_passed(client, stt_module, monkeypatch):
    """?language=ru reaches the backend unchanged."""
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post("/api/stt?language=ru", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen["language"] == "ru"


def test_language_form_field_passed(client, stt_module, monkeypatch):
    """A multipart ``language`` field works the same as the query string."""
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post(
        "/api/stt",
        data={"file": (io.BytesIO(make_wav()), "sample.wav"), "language": "ru"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert seen["language"] == "ru"


def test_language_default_none(client, stt_module, monkeypatch):
    """Without the option the backend receives None and applies WHISPER_LANGUAGE."""
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post("/api/stt", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen["language"] is None


def test_language_auto_passed(client, stt_module, monkeypatch):
    """``auto`` is lower-cased and forwarded; autodetect is resolved in libs/stt.py."""
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post("/api/stt?language=AUTO", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen["language"] == "auto"


def test_language_empty_is_none(client, stt_module, monkeypatch):
    """An empty value is treated as "not given"."""
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post("/api/stt?language=", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen["language"] is None


def test_unknown_language_400(client):
    """A language the backend does not know is refused here, rather than raising there.

    `zz` has the shape of a code and is not one. The old shape check let it through, Whisper
    raised on it, and the broad handler turned that into a 500.
    """
    resp = client.post("/api/stt?language=zz", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "Invalid language"
    assert set(body.keys()) == {"error", "request_id"}
    assert REQ_ID_RE.match(body["request_id"])


def test_language_name_is_resolved_to_its_code(client, stt_module, monkeypatch):
    """A full English name is what Whisper itself accepts, so the server accepts it too.

    The previous behaviour refused `russian` with a 400 although the backend understood it.
    """
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post("/api/stt?language=russian", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen["language"] == "ru"


def test_language_name_is_case_insensitive(client, stt_module, monkeypatch):
    """Casing is the caller's business, not the server's."""
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post("/api/stt?language=RUSSIAN", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen["language"] == "ru"


def test_a_typo_is_still_refused(client):
    """Resolution must not be so generous that a misspelling silently transcribes as something else."""
    resp = client.post("/api/stt?language=russsian", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Invalid language"


def post_language(client, query):
    """POST a short WAV to /api/stt with the given query string."""
    return client.post(f"/api/stt?{query}", data=make_wav(), content_type="audio/wav")


def use_legacy_model(monkeypatch, backend, model_id):
    """Switch the single-model deployment to another backend or checkpoint, with a pool to match."""
    monkeypatch.setattr(config, "STT_BACKEND", backend)
    monkeypatch.setattr(config, "WHISPER_MODEL" if backend == "whisper" else "PARAKEET_MODEL", model_id)
    pool = model_pool.get_model_pool(model_id)
    pool.put(make_model_sentinel(model_id))


def test_an_explicit_english_only_model_refuses_another_language(multi_client):
    """A client that chose tiny.en is told `ru` is not something that model does."""
    resp = post_language(multi_client, "model=tiny.en&language=ru")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Unsupported language"


@pytest.mark.parametrize("language", ["en", "auto"])
def test_an_explicit_english_only_model_takes_english_and_auto(multi_client, language):
    """English, and autodetect, are fine on an English-only model."""
    assert post_language(multi_client, f"model=tiny.en&language={language}").status_code == 200


def test_a_name_is_resolved_for_an_explicit_model(multi_client, stt_module, monkeypatch):
    """`russian` still reaches the backend as `ru` when the model is named."""
    seen = capture_language(stt_module, monkeypatch)
    assert post_language(multi_client, "model=small.en-stub&language=russian").status_code == 200
    assert seen["language"] == "ru"


def test_garbage_is_invalid_for_an_explicit_model(multi_client):
    """A value that is no language at all is `Invalid language`, not `Unsupported language`."""
    resp = post_language(multi_client, "model=small.en-stub&language=zz")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Invalid language"


def test_a_known_language_outside_the_models_slice_is_a_400(client):
    """`de` is a real code the default stub model does not know: a 400 now, where it used to be a 500."""
    resp = post_language(client, "language=de")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Unsupported language"


def test_an_english_only_default_keeps_accepting_other_codes(client, stt_module, monkeypatch):
    """Without `model`, an English-only checkpoint is handed `ru` as before, and the response says `en`."""
    use_legacy_model(monkeypatch, "whisper", "tiny.en")
    seen = {}
    original = stt_module.get_stt_result

    def record_language(bio, model=None, device=None, language=None):
        """Stand in for stt.get_stt_result(), remembering the language before answering like the stub."""
        seen["language"] = language
        return original(bio, model=model, device=device, language=language)

    monkeypatch.setattr(stt_module, "get_stt_result", record_language)
    resp = post_language(client, "language=ru")
    assert resp.status_code == 200
    assert seen["language"] == "ru"
    assert resp.get_json()["language"] == "en"


def test_an_explicit_parakeet_takes_a_listed_code(multi_client):
    """A code from Parakeet's own list is accepted as a hint; the model reports no language."""
    resp = post_language(multi_client, "model=parakeet&language=ru")
    assert resp.status_code == 200
    assert resp.get_json()["language"] is None


def test_an_explicit_parakeet_refuses_an_unlisted_code(multi_client):
    """A client that chose Parakeet read its list, so a code outside it is a mistake worth a 400."""
    resp = post_language(multi_client, "model=parakeet&language=de")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Unsupported language"


def test_a_parakeet_default_still_ignores_any_value(client, monkeypatch):
    """Without `model`, Parakeet accepts and ignores even garbage, exactly as it always did."""
    use_legacy_model(monkeypatch, "parakeet", "nvidia/parakeet-tdt-0.6b-v3")
    resp = post_language(client, "language=zz")
    assert resp.status_code == 200
    assert resp.get_json()["model"] == "nvidia/parakeet-tdt-0.6b-v3"


def test_a_legacy_path_model_accepts_what_its_checkpoint_knows(client, stt_module, monkeypatch):
    """WHISPER_MODEL=/models/turbo.pt is judged as turbo: `de` passes, as it did before model selection."""
    monkeypatch.setattr(config, "WHISPER_MODEL", "/models/turbo.pt")
    monkeypatch.setattr(model_pool, "MODEL_POOLS", {})
    model_pool.get_model_pool("turbo").put(make_model_sentinel("turbo"))
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post("/api/stt?language=de", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen["language"] == "de"
    assert resp.get_json()["model"] == "turbo"


def test_a_path_model_of_no_known_checkpoint_passes_the_code_on(client, stt_module, monkeypatch):
    """WHISPER_MODEL=/models/my-large-v3-finetune.pt matches no checkpoint name: `de` reaches it, as before."""
    monkeypatch.setattr(config, "WHISPER_MODEL", "/models/my-large-v3-finetune.pt")
    monkeypatch.setattr(model_pool, "MODEL_POOLS", {})
    model_pool.get_model_pool("my-large-v3-finetune").put(make_model_sentinel("my-large-v3-finetune"))
    seen = capture_language(stt_module, monkeypatch)
    resp = client.post("/api/stt?language=de", data=make_wav(), content_type="audio/wav")
    assert resp.status_code == 200
    assert seen["language"] == "de"


def test_an_explicit_english_only_path_model_refuses_another_language(client, monkeypatch):
    """`whisper:/opt/tiny.en.pt` is served as tiny.en and knows English only, like the named checkpoint."""
    monkeypatch.setattr(config, "STT_MODELS", config.parse_model_list("whisper:/opt/tiny.en.pt@1"))
    monkeypatch.setattr(model_pool, "MODEL_POOLS", {})
    model_pool.get_model_pool("tiny.en").put(make_model_sentinel("tiny.en"))
    resp = post_language(client, "model=tiny.en&language=ru")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Unsupported language"

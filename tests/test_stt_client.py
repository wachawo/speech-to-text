#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stt_client.py: the --model and --language options and the form fields it sends."""

import pytest

import stt_client


def test_model_and_language_in_both_spellings():
    """`--flag VALUE` and `--flag=VALUE` both work, and the files keep their order."""
    args = stt_client.build_parser().parse_args(["--model", "turbo", "--language=ru", "a.wav", "b.mp3"])
    assert (args.model, args.language, args.files, args.list) == ("turbo", "ru", ["a.wav", "b.mp3"], False)


def test_options_default_to_none():
    """Without the flags nothing is chosen, so the server's own defaults apply."""
    args = stt_client.build_parser().parse_args(["a.wav"])
    assert (args.model, args.language) == (None, None)


def test_list_needs_no_files():
    """`--list` alone asks for the catalogue."""
    assert stt_client.build_parser().parse_args(["--list"]).list is True


def test_empty_options_are_not_sent():
    """Only what the user gave goes into the form, so the server default applies otherwise."""
    assert stt_client.build_form_fields(None, "") == {}
    assert stt_client.build_form_fields("turbo", "ru") == {"model": "turbo", "language": "ru"}


@pytest.mark.parametrize(
    ("model", "language", "expected"),
    [("turbo", "ru", {"model": "turbo", "language": "ru"}), (None, None, {})],
)
def test_transcribe_file_posts_the_chosen_model_and_language(tmp_path, monkeypatch, model, language, expected):
    """--model and --language reach the request as form fields, and nothing is sent without them."""
    sent = {}

    class FakeResponse:
        """Just enough of requests.Response for transcribe_file."""

        def raise_for_status(self):
            """A successful answer raises nothing."""

        def json(self):
            """The decoded body."""
            return {"text": "ok"}

    def fake_post(url, **kwargs):
        """Record what would have been posted."""
        sent.update(kwargs)
        return FakeResponse()

    audio_path = tmp_path / "a.wav"
    audio_path.write_bytes(b"RIFF")
    monkeypatch.setattr(stt_client.requests, "post", fake_post)
    assert stt_client.transcribe_file(str(audio_path), model=model, language=language) == {"text": "ok"}
    assert sent["data"] == expected


def test_the_stream_start_message_names_a_model_only_when_given():
    """`--stream --model` puts the model in the start message; without it the server default serves."""
    assert stt_client.build_start_message("ru", True, "tiny.en") == {
        "type": "start",
        "language": "ru",
        "diarize": True,
        "model": "tiny.en",
    }
    assert "model" not in stt_client.build_start_message(None, False)

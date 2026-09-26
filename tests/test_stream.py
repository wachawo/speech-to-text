#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""libs/stream.py: the sample buffer, the pause detector, and one utterance through a pooled model."""

import queue
import random
import types

import numpy as np
import pytest
import soundfile as sf

# Local imports
from libs import config, model_pool, stream
from tests.helpers import make_silence, make_tone

RATE = stream.SAMPLE_RATE
FRAME = stream.FRAME_SAMPLES
PAUSE = int(stream.PAUSE_SECONDS * RATE)
PRE_ROLL = int(stream.PRE_ROLL_SECONDS * RATE)
POST_ROLL = int(stream.POST_ROLL_SECONDS * RATE)


@pytest.fixture
def model_queue(monkeypatch):
    """A one-slot model pool holding a sentinel, with the whisper stub as the transcriber."""
    pool: queue.Queue = queue.Queue()
    pool.put("model-sentinel")
    monkeypatch.setattr(model_pool, "MODEL_POOL", pool)
    monkeypatch.setattr(config, "STT_BACKEND", "whisper")
    return pool


def build_buffer(*chunks) -> dict:
    """A buffer holding the given int16 chunks, appended one by one."""
    buffer = stream.new_buffer()
    for chunk in chunks:
        stream.append_samples(buffer, np.asarray(chunk, dtype=np.int16))
    return buffer


def segment_audio(samples: np.ndarray, final: bool = True) -> list[dict]:
    """Run the pause detector over the whole signal at once."""
    buffer = build_buffer(samples)
    return stream.advance_segmenter(stream.new_segmenter(), buffer, final=final)


def segment_in_pieces(samples: np.ndarray, sizes: list[int]) -> list[dict]:
    """Run the pause detector as the signal arrives in pieces of the given sizes, then end the stream."""
    buffer = stream.new_buffer()
    segmenter = stream.new_segmenter()
    closed = []
    position = 0
    for size in sizes:
        stream.append_samples(buffer, samples[position : position + size])
        position += size
        closed.extend(stream.advance_segmenter(segmenter, buffer))
    stream.append_samples(buffer, samples[position:])
    closed.extend(stream.advance_segmenter(segmenter, buffer, final=True))
    return closed


def test_read_spans_chunk_boundaries():
    """A read that starts in one chunk and ends in a third returns the samples in order."""
    buffer = build_buffer(np.arange(0, 10), np.arange(10, 15), np.arange(15, 30))
    assert buffer["total"] == 30
    assert stream.read_samples(buffer, 8, 17).tolist() == list(range(8, 17))
    assert stream.read_samples(buffer, 10, 15).tolist() == list(range(10, 15))
    assert stream.read_samples(buffer, 0, 30).tolist() == list(range(30))


def test_read_clips_to_what_has_arrived():
    """Past the end reads what exists; an empty or inverted range reads nothing, as int16."""
    buffer = build_buffer(np.arange(0, 10))
    assert stream.read_samples(buffer, 5, 100).tolist() == list(range(5, 10))
    for start, end in ((10, 20), (7, 7), (8, 3)):
        empty = stream.read_samples(buffer, start, end)
        assert empty.size == 0
        assert empty.dtype == np.int16


def test_empty_append_adds_no_chunk():
    """Appending nothing leaves the buffer as it was, so a zero-byte frame costs nothing."""
    buffer = build_buffer(np.arange(0, 4))
    stream.append_samples(buffer, np.zeros(0, dtype=np.int16))
    assert len(buffer["chunks"]) == 1
    assert buffer["total"] == 4


def test_trim_keeps_the_chunk_that_straddles_the_mark():
    """Only whole chunks before the mark go; the one holding it stays, partly before the mark."""
    buffer = build_buffer(np.arange(0, 10), np.arange(10, 15), np.arange(15, 30))
    stream.trim_samples(buffer, 12)
    assert buffer["base"] == 10
    assert len(buffer["chunks"]) == 2
    # The kept part of the straddling chunk still reads, even before the mark.
    assert stream.read_samples(buffer, 10, 13).tolist() == [10, 11, 12]


def test_trimmed_samples_read_as_absent():
    """A read that reaches before the first kept sample returns only what is kept."""
    buffer = build_buffer(np.arange(0, 10), np.arange(10, 15), np.arange(15, 30))
    stream.trim_samples(buffer, 15)
    assert buffer["base"] == 15
    assert stream.read_samples(buffer, 0, 20).tolist() == list(range(15, 20))
    assert stream.read_samples(buffer, 2, 9).size == 0
    assert buffer["total"] == 30


def test_trim_everything_then_keep_appending():
    """Trimming past the end empties the buffer without losing the absolute index of what comes next."""
    buffer = build_buffer(np.arange(0, 10), np.arange(10, 20))
    stream.trim_samples(buffer, 50)
    assert buffer["chunks"] == []
    assert buffer["base"] == 20
    stream.append_samples(buffer, np.arange(20, 25, dtype=np.int16))
    assert stream.read_samples(buffer, 0, 100).tolist() == list(range(20, 25))


def test_one_burst_is_one_utterance_with_its_rolls():
    """A tone between two silences comes out as one utterance, padded by at most the pre and post roll."""
    tone_start, tone_end = RATE, 2 * RATE
    samples = np.concatenate([make_silence(1.0), make_tone(1.0), make_silence(1.5)])
    utterances = segment_audio(samples, final=False)
    assert len(utterances) == 1
    utterance = utterances[0]
    # The detector triggers on the first frame that holds tone, so the start is at most one frame
    # plus the pre-roll ahead of the tone, and never after it.
    assert tone_start - PRE_ROLL - FRAME <= utterance["start"] <= tone_start
    assert tone_end <= utterance["end"] <= tone_end + POST_ROLL + FRAME


def test_two_bursts_split_by_a_long_pause_are_two_utterances():
    """A pause longer than PAUSE_SECONDS ends the first utterance before the second starts."""
    samples = np.concatenate(
        [make_silence(0.5), make_tone(0.6), make_silence(stream.PAUSE_SECONDS + 0.4), make_tone(0.6), make_silence(1.0)]
    )
    utterances = segment_audio(samples, final=False)
    assert len(utterances) == 2
    first, second = utterances
    assert first["end"] <= second["start"]
    assert first["start"] < int(0.5 * RATE) < first["end"]
    second_tone = int((0.5 + 0.6 + stream.PAUSE_SECONDS + 0.4) * RATE)
    assert second["start"] <= second_tone < second["end"]


def test_a_short_gap_does_not_split_an_utterance():
    """The gap between two words is shorter than the pause and stays inside one utterance."""
    samples = np.concatenate([make_silence(0.5), make_tone(0.6), make_silence(0.3), make_tone(0.6), make_silence(1.0)])
    utterances = segment_audio(samples, final=False)
    assert len(utterances) == 1
    assert utterances[0]["start"] < int(0.5 * RATE)
    assert utterances[0]["end"] > int(2.0 * RATE)


def test_a_click_is_not_an_utterance():
    """Less voiced audio than MIN_VOICED_SECONDS is dropped, even when the stream ends on it."""
    click = make_tone(stream.MIN_VOICED_SECONDS / 3)
    assert segment_audio(np.concatenate([make_silence(0.5), click, make_silence(1.0)])) == []
    assert segment_audio(np.concatenate([make_silence(0.5), click])) == []


def test_endless_sound_is_cut_at_the_quietest_frame_and_continues():
    """Speech that never pauses is cut after MAX_UTTERANCE_SECONDS in the middle of its quietest frame."""
    # One quieter frame, aligned to the detector's frame grid, 1.5 s before the limit: inside the
    # search window, and the only candidate quieter than the tone around it.
    dip_frame = int((stream.MAX_UTTERANCE_SECONDS - 1.5) * RATE) // FRAME
    dip_start = dip_frame * FRAME
    tone_seconds = 20.0
    samples = np.concatenate(
        [
            make_tone(dip_start / RATE),
            make_tone(FRAME / RATE, amplitude=0.02),
            make_tone(tone_seconds - (dip_start + FRAME) / RATE),
            make_silence(1.0),
        ]
    )
    utterances = segment_audio(samples, final=False)
    assert len(utterances) == 2
    first, second = utterances
    cut = dip_start + FRAME // 2
    assert first == {"start": 0, "end": cut}
    limit = int(stream.MAX_UTTERANCE_SECONDS * RATE)
    assert limit - stream.CUT_SEARCH_SECONDS * RATE <= cut <= limit
    # The speaker had not stopped: the next utterance starts right at the cut and runs to the pause.
    assert second["start"] == cut
    assert int(tone_seconds * RATE) <= second["end"] <= int(tone_seconds * RATE) + POST_ROLL + FRAME


def test_final_closes_the_open_utterance():
    """A stream that stops mid-speech still yields that speech, ending at the last sample."""
    samples = np.concatenate([make_silence(0.5), make_tone(1.0)])
    assert segment_audio(samples, final=False) == []
    utterances = segment_audio(samples, final=True)
    assert len(utterances) == 1
    assert utterances[0]["end"] == samples.size


def test_pieces_and_one_piece_give_identical_utterances():
    """How the audio is chunked on the wire changes nothing about where it is cut."""
    samples = np.concatenate(
        [
            make_silence(0.5),
            make_tone(1.0),
            make_silence(0.3),
            make_tone(0.8),
            make_silence(1.0),
            make_tone(0.05),
            make_silence(1.0),
            make_tone(16.0),
            make_silence(1.0),
            make_tone(0.7),
        ]
    )
    whole = segment_audio(samples)
    generator = random.Random(1234)
    sizes = []
    while sum(sizes) < samples.size - 3000:
        sizes.append(generator.randint(1, 3000))
    pieces = segment_in_pieces(samples, sizes)
    # A two-word phrase, a dropped click, a run of speech cut in two, and a phrase the end of the stream closes.
    assert len(whole) == 4
    assert pieces == whole


def test_encode_wav_round_trips_through_soundfile():
    """The WAV handed to a transcriber decodes back to the same samples, rate and channel count."""
    samples = np.concatenate([make_tone(0.1), np.array([-32768, 32767, 0, -1], dtype=np.int16)])
    data, sample_rate = sf.read(stream.encode_wav(samples), dtype="int16")
    assert sample_rate == RATE
    assert data.ndim == 1
    assert np.array_equal(data, samples)


def test_transcribe_utterance_offsets_clamps_and_drops_empty_text(model_queue, stt_module, monkeypatch):
    """Segment times move to stream time, an end past the audio is clamped, and empty text is dropped."""
    seen = {}

    def fake_segments(bio, model=None, device=None, language=None):
        """Record what the transcriber was handed and answer with three segments."""
        data, unused_rate = sf.read(bio, dtype="int16")
        seen.update(model=model, language=language, samples=data.size, pool_during_call=model_queue.qsize())
        return [
            {"start": 0.0, "end": 1.0, "text": " hello "},
            {"start": 1.0, "end": 1.2, "text": "   "},
            {"start": 1.5, "end": 29.9, "text": " tail"},
        ]

    monkeypatch.setattr(stt_module, "get_stt_segments", fake_segments)
    buffer = build_buffer(make_silence(4.0))
    utterance = {"start": 2 * RATE, "end": int(3.6 * RATE)}
    segments = stream.transcribe_utterance(buffer, utterance, "ru")
    assert segments == [
        {"start": 2.0, "end": 3.0, "text": "hello"},
        {"start": 3.5, "end": 3.6, "text": "tail"},
    ]
    assert seen == {"model": "model-sentinel", "language": "ru", "samples": int(1.6 * RATE), "pool_during_call": 0}
    # Borrowed for the utterance only.
    assert model_queue.qsize() == 1


def test_transcribe_utterance_returns_the_model_when_the_transcriber_fails(model_queue, stt_module, monkeypatch):
    """A transcriber that raises still gives the model back, or one bad phrase would shrink the pool."""

    def fail_segments(bio, model=None, device=None, language=None):
        """Stand in for a transcriber that crashes."""
        raise RuntimeError("decoder exploded")

    monkeypatch.setattr(stt_module, "get_stt_segments", fail_segments)
    buffer = build_buffer(make_tone(1.0))
    with pytest.raises(RuntimeError):
        stream.transcribe_utterance(buffer, {"start": 0, "end": RATE}, None)
    assert model_queue.qsize() == 1


def test_transcribe_utterance_never_ends_a_segment_before_it_starts(model_queue, stt_module, monkeypatch):
    """A segment placed wholly past the audio is dropped, so every segment keeps start <= end."""

    def fake_segments(bio, model=None, device=None, language=None):
        """A real phrase, then one placed in the padding after the audio."""
        return [{"start": 0.0, "end": 0.8, "text": " hello"}, {"start": 1.4, "end": 2.0, "text": " thank you"}]

    monkeypatch.setattr(stt_module, "get_stt_segments", fake_segments)
    buffer = build_buffer(make_tone(1.0))
    segments = stream.transcribe_utterance(buffer, {"start": 0, "end": RATE}, None)
    assert all(segment["start"] <= segment["end"] for segment in segments)
    assert [segment["text"] for segment in segments] == ["hello"]


def test_attribute_live_segments_names_speakers_without_merging():
    """Each segment gets the speaker holding most of it and an overlap flag; runs are not merged."""
    segments = [
        {"start": 0.0, "end": 1.0, "text": "a"},
        {"start": 1.0, "end": 2.0, "text": "b"},
        {"start": 3.0, "end": 3.5, "text": "c"},
        {"start": 3.5, "end": 4.0, "text": "d"},
        {"start": 9.0, "end": 9.5, "text": "e"},
    ]
    turns = [
        {"speaker": 0, "start": 0.0, "end": 1.2},
        {"speaker": 1, "start": 0.9, "end": 2.5},
        {"speaker": 0, "start": 2.9, "end": 4.2},
    ]
    original = [dict(segment) for segment in segments]
    attributed = stream.attribute_live_segments(segments, turns)
    assert [(item["text"], item["speaker"], item["overlap"]) for item in attributed] == [
        ("a", 0, True),
        ("b", 1, True),
        ("c", 0, False),
        ("d", 0, False),
        ("e", None, False),
    ]
    assert attributed[0]["start"] == 0.0 and attributed[0]["end"] == 1.0
    assert segments == original


def test_advance_diarization_borrows_and_returns_a_diarizer(monkeypatch):
    """The diarizer is borrowed for one call, handed a reader over the buffer, and always given back."""
    pool: queue.Queue = queue.Queue()
    pool.put("diarizer-sentinel")
    monkeypatch.setattr(model_pool, "DIARIZER_POOL", pool)
    calls = []

    def record_advance(state, read_samples, total_samples, diarizer, until, final):
        """Record the call and read through the callback it was given."""
        calls.append((state, read_samples(2, 5).tolist(), total_samples, diarizer, until, final, pool.qsize()))

    monkeypatch.setattr(stream, "diarize", types.SimpleNamespace(advance_stream=record_advance))
    buffer = build_buffer(np.arange(0, 4), np.arange(4, 10))
    state: dict = {}
    stream.advance_diarization(state, buffer, until=8, final=True)
    assert calls == [(state, [2, 3, 4], 10, "diarizer-sentinel", 8, True, 0)]
    assert pool.qsize() == 1

    def fail_advance(*args):
        """Stand in for a diarizer that crashes."""
        raise RuntimeError("diarizer exploded")

    monkeypatch.setattr(stream, "diarize", types.SimpleNamespace(advance_stream=fail_advance))
    with pytest.raises(RuntimeError):
        stream.advance_diarization(state, buffer, until=8, final=False)
    assert pool.qsize() == 1


def test_cut_utterance_closes_the_open_phrase_and_goes_on():
    """A cut inside an open utterance closes it there, and the next one starts at the same sample."""
    buffer = build_buffer(make_tone(3.0))
    segmenter = stream.new_segmenter()
    assert stream.advance_segmenter(segmenter, buffer) == []
    closed = stream.cut_utterance(segmenter, int(1.5 * RATE))
    assert closed == {"start": 0, "end": int(1.5 * RATE)}
    assert segmenter["in_speech"] and segmenter["speech_start"] == int(1.5 * RATE)
    stream.append_samples(buffer, make_silence(1.0))
    tail = stream.advance_segmenter(segmenter, buffer, final=True)
    assert tail[0]["start"] == int(1.5 * RATE)


def test_cut_utterance_does_nothing_outside_an_open_phrase():
    """No open utterance, or a cut point outside it, changes nothing."""
    segmenter = stream.new_segmenter()
    assert stream.cut_utterance(segmenter, RATE) is None
    buffer = build_buffer(make_tone(2.0))
    stream.advance_segmenter(segmenter, buffer)
    assert stream.cut_utterance(segmenter, 0) is None
    assert stream.cut_utterance(segmenter, 5 * RATE) is None
    assert segmenter["speech_start"] == 0

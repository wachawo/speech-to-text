#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Join transcription segments to speaker turns by time. Pure functions: no models, no torch."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# A segment nobody claims keeps this speaker rather than being handed to the nearest turn.
# Saying "not attributed" is honest; guessing is not.
UNATTRIBUTED: None = None


def overlap_seconds(first_start: float, first_end: float, second_start: float, second_end: float) -> float:
    """Seconds the two ranges share, or zero when they do not touch."""
    return max(0.0, min(first_end, second_end) - max(first_start, second_start))


def turn_contains(turn: dict[str, Any], moment: float) -> bool:
    """Whether a turn covers this instant. Half-open, so a handover instant belongs to the new turn only."""
    return turn["start"] <= moment < turn["end"]


def is_point(segment: dict[str, Any]) -> bool:
    """Whether a segment has no length. Parakeet emits such tokens; they are instants, not ranges."""
    return float(segment["start"]) == float(segment["end"])


def assign_speaker(segment: dict[str, Any], turns: list[dict[str, Any]]) -> int | None:
    """The speaker whose turn overlaps this segment most, or None when no turn overlaps it.

    Greatest overlap rather than the containing turn: a phrase that straddles a handover
    belongs to whoever held most of it, and a phrase inside an overlap belongs to whoever was
    speaking for longer while it happened. A zero-length segment overlaps nothing, so it goes
    to the first turn that contains its instant.
    """
    if is_point(segment):
        moment = float(segment["start"])
        return next((turn["speaker"] for turn in turns if turn_contains(turn, moment)), UNATTRIBUTED)
    best: int | None = UNATTRIBUTED
    best_overlap = 0.0
    for turn in turns:
        shared = overlap_seconds(segment["start"], segment["end"], turn["start"], turn["end"])
        if shared > best_overlap:
            best, best_overlap = turn["speaker"], shared
    return best


def is_overlapped(segment: dict[str, Any], turns: list[dict[str, Any]]) -> bool:
    """Whether two different speakers were talking at the same moment inside this segment.

    Reported rather than hidden: the diarizer scores each speaker channel independently, so
    genuinely simultaneous speech is a fact about the recording, and a transcript that quietly
    attributes it to one person is claiming more than anybody knows. Turns that merely follow
    one another inside the segment are a handover, not overlap: a transcriber's phrase spans
    handovers all the time, and flagging those would set the flag on nearly everything.
    """
    start, end = float(segment["start"]), float(segment["end"])
    if is_point(segment):
        return len({turn["speaker"] for turn in turns if turn_contains(turn, start)}) > 1
    inside = [
        (turn["speaker"], max(start, turn["start"]), min(end, turn["end"]))
        for turn in turns
        if overlap_seconds(start, end, turn["start"], turn["end"]) > 0
    ]
    for index, (speaker, first_start, first_end) in enumerate(inside):
        for other, second_start, second_end in inside[index + 1 :]:
            if other != speaker and overlap_seconds(first_start, first_end, second_start, second_end) > 0:
                return True
    return False


def continues_run(previous: dict[str, Any], segment: dict[str, Any], speaker: int | None, turns: list[dict[str, Any]]) -> bool:
    """Whether a segment extends the previous run rather than starting a new one.

    The same speaker is not enough. If somebody else held a turn in the gap between the two -
    even a turn the transcriber produced no words for - merging them would claim the first
    speaker talked straight through the second one, which the diarizer says did not happen.
    """
    if previous["speaker"] != speaker:
        return False
    for turn in turns:
        if turn["speaker"] == speaker:
            continue
        if overlap_seconds(previous["end"], segment["start"], turn["start"], turn["end"]) > 0:
            return False
    return True


def attribute_segments(segments: list[dict[str, Any]], turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attribute each transcription segment to a speaker, merging consecutive runs of one.

    Runs merge only when nobody else spoke in between; see continues_run.

    `segments` are the transcriber's own phrases with their times; `turns` are the diarizer's
    output. Neither is modified. The result carries the joined text, the range it covers and
    whether two different speakers were talking at the same moment inside it.
    """
    attributed: list[dict[str, Any]] = []
    for segment in segments:
        text = segment["text"].strip()
        # Found live: a whitespace-only token became a segment of its own, `{"speaker": null,
        # "text": ""}`. Nothing was said there, so there is nothing to attribute.
        if not text:
            continue
        speaker = assign_speaker(segment, turns)
        overlapped = is_overlapped(segment, turns)
        if attributed and continues_run(attributed[-1], segment, speaker, turns):
            previous = attributed[-1]
            previous["end"] = round(float(segment["end"]), 2)
            previous["text"] = f"{previous['text']} {text}".strip()
            previous["overlap"] = previous["overlap"] or overlapped
            continue
        attributed.append(
            {
                "speaker": speaker,
                "start": round(float(segment["start"]), 2),
                "end": round(float(segment["end"]), 2),
                "text": text,
                "overlap": overlapped,
            }
        )
    return attributed


def count_speakers(attributed: list[dict[str, Any]]) -> int:
    """How many distinct speakers were actually attributed, not counting the unattributed."""
    return len({segment["speaker"] for segment in attributed if segment["speaker"] is not UNATTRIBUTED})


def main():
    """No-op entry point: this module is imported for its join helpers."""
    pass


if __name__ == "__main__":
    main()

"""Typing test: a short passage, two minutes from the first character, then words per minute.

There are six passages of the same length. Each run shows a passage the participant has not seen,
so three runs per keyboard use all six and practice never helps a later run.

Speed uses the usual text entry measure (MacKenzie): words per minute, with a "word" being
5 characters. The clock starts on the first character, so that character carries no time:

    WPM = (characters typed - 1) / seconds * 60 / 5

Accuracy compares what was typed with the same stretch of the passage: the smallest number of
single letter changes between them (the edit distance), as a share of what was typed. Picks per
character (KSPC) counts every selection made while typing (letters, letter groups, Back, Space,
Backspace) divided by the characters typed, so it shows the effort behind each character.
"""

from __future__ import annotations

import json
from pathlib import Path

from .common import ROOT

SECONDS = 120     # the test runs for two minutes from the first character


def passages() -> list[str]:
    path = ROOT / "communicaid" / "prose.txt"
    return [l.strip() for l in path.read_text().splitlines() if l.strip() and not l.startswith("#")]


def load_passage(number: int) -> str:
    """Passage 1 to 6, in the order of prose.txt."""
    return passages()[number - 1]


def participant(person: str) -> str:
    """P01-gaze, P01-head and P01 all belong to participant P01."""
    return person.split("-")[0]


def used_passages(root: Path, person: str) -> set[int]:
    """Passages this participant has already typed, in any of their data folders."""
    who, used = participant(person), set()
    data = root / "data"
    for folder in data.iterdir() if data.exists() else []:
        if folder.name != who and not folder.name.startswith(who + "-"):
            continue
        log = folder / "events.jsonl"
        if log.exists():
            for line in log.open():
                if '"typing_result"' in line:
                    used.add(json.loads(line).get("passage"))
    return used - {None}


def next_passage(root: Path, person: str) -> int | None:
    """The lowest numbered passage this participant has not typed yet, or None when all are used."""
    used = used_passages(root, person)
    return next((n for n in range(1, len(passages()) + 1) if n not in used), None)


def edit_distance(a: str, b: str) -> int:
    """Fewest single character insertions, deletions or swaps that turn a into b."""
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def score(passage: str, typed: str, seconds: float, selections: int, backspaces: int) -> dict:
    """Everything worth keeping about one timed test."""
    chars = len(typed)
    wpm = (chars - 1) / seconds * 60 / 5 if chars > 1 and seconds > 0 else 0.0
    errors = edit_distance(typed, passage[:chars])
    return {
        "typed": typed, "chars": chars, "seconds": seconds, "wpm": round(wpm, 2),
        "errors": errors, "accuracy": round(1 - errors / chars, 3) if chars else 0.0,
        "kspc": round(selections / chars, 2) if chars else None,
        "selections": selections, "backspaces": backspaces,
    }

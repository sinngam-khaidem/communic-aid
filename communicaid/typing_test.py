"""Typing test: phrases to copy and how each attempt is scored.

Speed uses the usual text entry measure (MacKenzie): words per minute, with a "word" being
5 characters, timed from the first character entered to the last:

    WPM = (characters typed - 1) / seconds * 60 / 5

Errors left in are the smallest number of single letter changes that turn the typed text into
the phrase (the edit distance), divided by the longer of the two. Selections per character
(KSPC) counts every pick made while typing (letters, letter groups, Back, Space, Backspace)
divided by the characters typed, so it shows the effort behind each character.
"""

from __future__ import annotations

from .common import ROOT


def load_phrases(keyboard: str) -> list[str]:
    """The grouped keyboard gets the first half of the list, QWERTY the second half."""
    path = ROOT / "communicaid" / "phrases.txt"
    lines = [l.strip() for l in path.read_text().splitlines() if l.strip() and not l.startswith("#")]
    half = len(lines) // 2
    return lines[:half] if keyboard == "grouped" else lines[half:]


def edit_distance(a: str, b: str) -> int:
    """Fewest single character insertions, deletions or swaps that turn a into b."""
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def score(target: str, typed: str, first: float | None, last: float | None, selections: int,
          backspaces: int) -> dict:
    """Everything worth keeping about one attempt at one phrase."""
    seconds = (last - first) if first is not None and last is not None else 0.0
    chars = len(typed)
    wpm = (chars - 1) / seconds * 60 / 5 if chars > 1 and seconds > 0 else 0.0
    longest = max(len(target), chars) or 1
    return {
        "target": target, "typed": typed, "chars": chars, "seconds": round(seconds, 2),
        "wpm": round(wpm, 2),
        "error_rate": round(edit_distance(typed, target) / longest, 3),
        "kspc": round(selections / chars, 2) if chars else None,
        "selections": selections, "backspaces": backspaces, "exact": typed == target,
    }

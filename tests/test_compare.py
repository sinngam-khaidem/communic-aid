"""The Adaptive vs Fixed study: session order, setup copy, scoring and the paired test."""

import csv
import json
import math

import pytest

import compare
import study


def test_odd_participants_start_adaptive_and_even_start_fixed():
    assert study.order("P03") == ("adaptive", "fixed")
    assert study.order("P04") == ("fixed", "adaptive")
    with pytest.raises(SystemExit):
        study.order("P03-gaze")


def test_second_session_reuses_answers_but_not_calibration(tmp_path, monkeypatch):
    first = tmp_path / "data" / "P03-adaptive"
    first.mkdir(parents=True)
    for name in ("settings.json", "signals.json", "calibration.json"):
        (first / name).write_text("{}")
    monkeypatch.setattr(study, "ROOT", tmp_path)

    command = study.prepare("P03", 2)

    second = tmp_path / "data" / "P03-fixed"
    assert (second / "settings.json").exists() and (second / "signals.json").exists()
    assert not (second / "calibration.json").exists()
    assert command[-6:] == ["--person", "P03-fixed", "--condition", "fixed", "--pointing", "gaze"]


def test_sus_scoring():
    assert compare.sus({f"sus{i}": 3 for i in range(1, 11)}) == 50
    assert compare.sus({f"sus{i}": 5 if i % 2 else 1 for i in range(1, 11)}) == 100
    assert compare.sus({f"sus{i}": 1 if i % 2 else 5 for i in range(1, 11)}) == 0


def test_wilcoxon_matches_known_values():
    assert compare.wilcoxon([1, 2, 3, 4, 5, 6]) == (6, 21, 2 / 64)       # all one way: smallest p for 6 pairs
    n, w, p = compare.wilcoxon([1, -2, 3, -4, 5, -6])
    assert n == 6 and w == 9 and p > 0.5
    assert compare.wilcoxon([0, 0, 1])[0] == 1                           # no difference: left out
    assert compare.ranks([10, 20, 20, 30]) == [1, 2.5, 2.5, 4]


def session(folder, condition, accidents, dwell):
    """A tiny log: 10 selections, some of them accidents, every look at one dwell."""
    rows = []
    for i in range(10):
        base = {"t": float(i), "session": "s1", "condition": condition}
        rows.append({**base, "event": "look", "action": "key:a", "tier": 1, "dwell": dwell})
        rows.append({**base, "event": "fire", "action": "key:a"})
        kind = "accident" if i < accidents else "worked"
        rows.append({**base, "event": "outcome", "outcome": {"learner": "dwell", "kind": kind}})
    folder.mkdir(parents=True)
    (folder / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_compare_pairs_each_participant_and_adds_sus(tmp_path, monkeypatch):
    for p, (fa, aa) in {"P01": (3, 1), "P02": (2, 1), "P03": (4, 2)}.items():
        session(tmp_path / "data" / f"{p}-fixed", "fixed", fa, 1000)
        session(tmp_path / "data" / f"{p}-adaptive", "adaptive", aa, 1200)
    session(tmp_path / "data" / "P09-fixed", "fixed", 1, 1000)          # only one condition: left out
    with (tmp_path / "data" / "study_forms.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["participant", "condition", *(f"sus{i}" for i in range(1, 11))])
        w.writerow(["P01", "adaptive", *[5, 1] * 5])
        w.writerow(["P01", "fixed", *[3] * 10])
    monkeypatch.setattr(compare, "ROOT", tmp_path)

    out = compare.compare(tmp_path / "out")

    assert compare.participants() == ["P01", "P02", "P03"]
    rows = list(csv.DictReader((out / "measures.csv").open()))
    p1 = {r["condition"]: r for r in rows if r["participant"] == "P01"}
    assert float(p1["fixed"]["Accidents per 100 selections"]) == 30
    assert float(p1["adaptive"]["SUS"]) == 100 and float(p1["fixed"]["SUS"]) == 50
    assert math.isclose(float(p1["adaptive"]["Mean dwell, tier 1 (ms)"]), 1200)
    assert (out / "compare.png").exists()
    assert "| Accidents per 100 selections | 30.0 | 10.0 | 3 |" in (out / "compare.md").read_text()

"""Make everything for one participant: heatmaps, dwell plots and a summary table per mode.

    python tests/report.py --person P01

Finds data/P01 and every data/P01-<mode> folder (for example P01-gaze, P01-head, P01-free).
For each folder it uses the session with the most looks, and saves into result/P01/:

    <mode>/heatmap_<screen>.png   where the person looked on each screen
    <mode>/dwell.png              how the dwell changed over the session
    summary.csv, summary.md       one column per mode, one row per measure

Task times, SUS, NASA-TLX and ratings are on paper and are not part of this.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np

import plot_dwell
import plot_heatmap
from communicaid.common import ROOT

FIXED = ("undo", "redo")
SIGNALS = {"blink": "Blink and hold", "brows": "Raise eyebrows", "yes": 'Say "proceed"', "switch": "Switch"}


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def folders(person: str) -> dict[str, Path]:
    """Mode name to data folder: data/P01 is "default", data/P01-gaze is "gaze"."""
    found = {}
    for d in sorted((ROOT / "data").iterdir()):
        if d.is_dir() and (d.name == person or d.name.startswith(person + "-")):
            found[d.name[len(person) + 1:] or "default"] = d
    if not found:
        raise SystemExit(f"No data folders for {person} in data/.")
    return found


def main_session(events: list[dict]) -> str | None:
    """The session with the most looks, so a short false start is never picked."""
    looks = Counter(e["session"] for e in events if e["event"] == "look")
    return looks.most_common(1)[0][0] if looks else None


def head_movement(gaze: list[dict]) -> tuple[str, str]:
    """How far the eyes moved from their usual place, in mm: typical, and the largest 5%."""
    eye = np.array([g["eye_mm"] for g in gaze if g.get("eye_mm")])
    if len(eye) < 10:
        return "n/a", "n/a"
    dist = np.linalg.norm(eye - np.median(eye, axis=0), axis=1)
    return f"{np.median(dist):.0f}", f"{np.percentile(dist, 95):.0f}"


def summarise(events: list[dict], gaze: list[dict]) -> dict[str, str]:
    kinds = Counter(e["outcome"]["kind"] for e in events if e["event"] == "outcome")
    fires = [e for e in events if e["event"] == "fire"]
    picks = [f for f in fires if f["action"] not in FIXED]
    asked = Counter(e["check"] for e in events if e["event"] == "choice" and e["check"] != "dwell")
    confirmed = Counter(e["check"] for e in events if e["event"] == "accept")
    calib = [e for e in events if e["event"] == "calib_done" and e.get("error_px") is not None]
    last_dwell = {}
    for e in events:
        if e["event"] == "look" and e["action"] not in FIXED and e["tier"] in (0, 1):
            last_dwell[e["tier"]] = e["dwell"]
    minutes = (events[-1]["t"] - events[0]["t"]) / 60 if events else 0
    typical, largest = head_movement(gaze)
    row = {
        "Pointing": events[0].get("pointing", "gaze") if events else "",
        "Condition": events[0].get("condition", "") if events else "",
        "Session length (min)": f"{minutes:.0f}",
        "Calibration error (px)": f"{calib[-1]['error_px']:.0f}" if calib else "n/a",
        "Selections": str(len(picks)),
        "Accidents": str(kinds["accident"]),
        "Accidents per 100 selections": f"{100 * kinds['accident'] / len(picks):.1f}" if picks else "n/a",
        "Undos": str(sum(f["action"] == "undo" for f in fires)),
        "Give-ups": str(kinds["gave_up"]),
        "Stray glances (passed by)": str(kinds["passed_by"]),
        "Wrong signals": str(sum(e["event"] == "wrong" for e in events)),
        "Signal timeouts": str(sum(e["event"] == "timeout" and e.get("reason") != "lost" for e in events)),
        "Dwell at end, tier 0 (ms)": str(last_dwell.get(0, "n/a")),
        "Dwell at end, tier 1 (ms)": str(last_dwell.get(1, "n/a")),
        "Head movement, typical (mm)": typical,
        "Head movement, largest 5% (mm)": largest,
    }
    for key, name in SIGNALS.items():
        row[f"{name}: asked / confirmed"] = f"{asked[key]} / {confirmed[key]}"
    return row


def report(person: str) -> None:
    out = ROOT / "result" / person
    out.mkdir(parents=True, exist_ok=True)
    table: dict[str, dict[str, str]] = {}
    for mode, folder in folders(person).items():
        everything = read(folder / "events.jsonl")
        session = main_session(everything)
        if session is None:
            print(f"{folder.name}: no looks logged, skipped")
            continue
        events = [e for e in everything if e.get("session") == session]
        gaze = [g for g in read(folder / "gaze.jsonl") if g.get("session") == session]
        print(f"{folder.name}: session {session}")
        table[mode] = summarise(events, gaze)
        if gaze:
            plot_heatmap.plot(folder.name, session, out / mode)
        else:
            print("  no gaze log in this session (recorded before gaze logging was added)")
        try:
            plot_dwell.plot(folder.name, session, out / mode / "dwell.png")
        except SystemExit as why:
            print(f"  no dwell plot: {why}")
    if not table:
        raise SystemExit("Nothing to report.")

    modes = list(table)
    rows = list(next(iter(table.values())))
    with (out / "summary.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Measure", *modes])
        for r in rows:
            w.writerow([r, *(table[m][r] for m in modes)])
    lines = [f"# {person}", "", "| Measure | " + " | ".join(modes) + " |", "|---|" + "---|" * len(modes)]
    lines += [f"| {r} | " + " | ".join(table[m][r] for m in modes) + " |" for r in rows]
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nsaved {out.relative_to(ROOT)}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--person", required=True, help="participant ID without the mode, for example P01")
    report(ap.parse_args().person)

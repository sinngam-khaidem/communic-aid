"""Plot how the learned dwell changed over a logged session.

    python tests/plot_dwell.py                                        # the session with the most looks
    python tests/plot_dwell.py --person sinngam01 --session 20261109-203807

Saves result/dwell_over_time.png: the dwell in use at each look, for tier 0 and tier 1.
Undo and redo are left out, since the undo strip keeps a fixed dwell.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from communicaid.common import ROOT, load_config

OUT = ROOT / "result"
FIXED = ("undo", "redo")
TIERS = {0: ("Tier 0: letters and navigation", "#4C7DAF"), 1: ("Tier 1: words and edits", "#D08A55")}


def load_looks(person: str | None, session: str | None):
    """Looks of one adaptive session. Without a choice, the session with the most looks."""
    files = [ROOT / "data" / person / "events.jsonl"] if person else sorted((ROOT / "data").glob("*/events.jsonl"))
    sessions: dict[tuple[str, str], list] = defaultdict(list)
    for f in files:
        for line in f.open():
            r = json.loads(line)
            if r.get("event") == "look" and r.get("condition") == "adaptive" and r["action"] not in FIXED:
                sessions[(f.parent.name, r["session"])].append(r)
    if session:
        sessions = {k: v for k, v in sessions.items() if k[1] == session}
    if not sessions:
        raise SystemExit("No logged session found with looks in it.")
    key = max(sessions, key=lambda k: len(sessions[k]))
    return key, sessions[key]


def plot(person: str | None, session: str | None) -> None:
    (who, sid), looks = load_looks(person, session)
    d = load_config()["dwell"]
    end = max(r["t"] for r in looks) / 60

    fig, ax = plt.subplots(figsize=(8, 3.8), constrained_layout=True)
    for y in (d["start"], d["min"]):
        ax.axhline(y, color="#D5D5D5", lw=0.8, zorder=0)
    for tier, (label, colour) in TIERS.items():
        pts = [(r["t"] / 60, r["dwell"]) for r in looks if r["tier"] == tier]
        x, y = zip(*pts)
        ax.step((0, *x, end), (d["start"], *y, y[-1]), where="post", color=colour, lw=2, label=label)

    ax.set_xlim(0, end)
    ax.set_ylim(d["min"] - 100, d["start"] + 100)
    ax.set_yticks(range(d["min"], d["start"] + 1, 100))
    ax.set_xlabel("Minutes")
    ax.set_ylabel("Dwell time (ms)")
    ax.set_title("Dwell time over one session", loc="left", fontsize=12, pad=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper right")

    OUT.mkdir(exist_ok=True)
    path = OUT / "dwell_over_time.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    print(f"saved {path.relative_to(ROOT)} ({who}, session {sid}, {len(looks)} looks, {end:.0f} minutes)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--person", help="folder in data/ (default: any)")
    ap.add_argument("--session", help="session id (default: the one with the most looks)")
    args = ap.parse_args()
    plot(args.person, args.session)

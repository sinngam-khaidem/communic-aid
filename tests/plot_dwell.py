"""Plot how the learned dwell changed over a logged session.

    python tests/plot_dwell.py                                        # the session with the most looks
    python tests/plot_dwell.py --person sinngam01 --session 20261109-203807

Saves result/dwell_over_time.png: the dwell in use at each look, for tier 0 and tier 1,
with the session length, looks and give-ups per tier in a corner box.
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


def load_session(person: str | None, session: str | None):
    """Looks and give-ups of one adaptive session. Without a choice, the session with the most looks."""
    files = [ROOT / "data" / person / "events.jsonl"] if person else sorted((ROOT / "data").glob("*/events.jsonl"))
    looks: dict[tuple[str, str], list] = defaultdict(list)
    gave_ups: dict[tuple[str, str], list] = defaultdict(list)
    for f in files:
        for line in f.open():
            r = json.loads(line)
            if r.get("condition") != "adaptive":
                continue
            key = (f.parent.name, r["session"])
            if r["event"] == "look" and r["action"] not in FIXED:
                looks[key].append(r)
            elif r["event"] == "outcome" and r["outcome"]["learner"] == "dwell" and r["outcome"]["kind"] == "gave_up":
                gave_ups[key].append(r["outcome"])
    if session:
        looks = {k: v for k, v in looks.items() if k[1] == session}
    if not looks:
        raise SystemExit("No logged session found with looks in it.")
    key = max(looks, key=lambda k: len(looks[k]))
    return key, looks[key], gave_ups[key]


def plot(person: str | None, session: str | None) -> None:
    (who, sid), looks, gave_ups = load_session(person, session)
    d = load_config()["dwell"]
    end = max(r["t"] for r in looks) / 60
    count = lambda rows, tier: sum(1 for r in rows if r["tier"] == tier)
    info = "\n".join([
        f"Session duration   {end:.0f} min",
        f"Tier 0 looks       {count(looks, 0)}",
        f"Tier 1 looks       {count(looks, 1)}",
        f"Tier 0 gave ups    {count(gave_ups, 0)}",
        f"Tier 1 gave ups    {count(gave_ups, 1)}",
    ])

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
    ax.text(0.02, 0.04, info, transform=ax.transAxes, ha="left", va="bottom", fontsize=9,
            family="monospace", color="#444444", linespacing=1.5,
            bbox={"boxstyle": "round,pad=0.6", "facecolor": "#F7F7F7", "edgecolor": "#E2E2E2"})

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

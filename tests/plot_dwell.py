"""
Plot how the dwell learner changed the dwell, over every session in one data folder.

    python tests/plot_dwell.py --person P01-gaze

Saves result/dwell_<person>.png. It reads the learner's own record: the "learned" lines in
events.jsonl, which give the dwell before and after each selection. So:

- The x axis counts selections, because the learner moves only when something is selected.
  Sessions follow in order, since the learning carries over from one session to the next.
- The learner keeps a separate dwell for each group (for example tired+steady and tired+shaky),
  so each group gets its own panel, with one line per tier.
- Each line starts where the learner really was when the first session in the folder began.
- The shaded part is the warmup: the group's first selections, when its dwell stays at the start.
  Light marks along the bottom are this group's selections, so a flat line with no marks means the
  group was not in use. Dark marks are accidents, which make the dwell go back up.

Only the adaptive condition is plotted. In the Fixed condition the dwell never changes.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from communicaid.common import ROOT, load_config

OUT = ROOT / "result"
TIERS = {0: ("Tier 0: navigation", "#4C7DAF"), 1: ("Tier 1: typing and settings", "#D08A55")}
INK, MUTED, RULE = "#333333", "#777777", "#D5D5D5"


def load(person: str) -> dict:
    """Every dwell learning step in one data folder, numbered by selection."""
    path = ROOT / "data" / person / "events.jsonl"
    if not path.exists():
        raise SystemExit(f"No events.jsonl in data/{person}.")
    events = [json.loads(line) for line in path.open() if line.strip()]
    keyboard = {e["session"]: e["keyboard"] for e in events if e["event"] == "typing_start"}

    n = 0                                            # selections so far
    lines: dict[tuple[int, str], list] = defaultdict(list)   # (tier, group) -> [(selection, dwell)]
    selections, accidents = defaultdict(list), defaultdict(list)   # group -> selection numbers
    warmup, warm_from = set(), {}                    # groups seen in warmup, and where it ended
    sessions: list[tuple[float, str, str]] = []      # (where it starts, label, session id)
    for e in events:
        if e["event"] != "learned" or e.get("condition") != "adaptive" or e["outcome"]["learner"] != "dwell":
            continue
        changes = e.get("changes") or []
        if not changes:                              # a stray glance or a give-up: counted, dwell unchanged
            continue
        if not sessions or sessions[-1][2] != e["session"]:
            sessions.append((n + 0.5, keyboard.get(e["session"], "chat"), e["session"]))
        n += 1
        group = e["outcome"]["group"]
        selections[group].append(n)
        if e["outcome"]["kind"] == "accident":
            accidents[group].append(n)
        for c in changes:
            key = (c["tier"], c["group"])
            if "warmup" in c:
                before = after = c["dwell"]
                warmup.add(c["group"])
            else:
                before, after = c["before"], c["after"]
                if c["group"] in warmup:
                    warm_from.setdefault(c["group"], n - 0.5)
            if not lines[key]:
                lines[key].append((0, before))       # where the learner was at the start
            elif lines[key][-1][1] != before:        # changed outside a selection, for example a reset
                lines[key].append((n - 0.5, before))
            lines[key].append((n, after))
    if not n:
        raise SystemExit(f"No dwell learning in data/{person} (Fixed condition, or no selections yet).")
    return {"n": n, "lines": lines, "selections": selections, "accidents": accidents,
            "warmup": warmup, "warm_from": warm_from, "sessions": sessions}


def plot(person: str, out: Path | None = None) -> Path:
    data, d = load(person), load_config()["dwell"]
    n = data["n"]
    groups = sorted(data["selections"], key=lambda g: -len(data["selections"][g]))
    fig, axes = plt.subplots(len(groups), 1, figsize=(9, 1.2 + 2.4 * len(groups)), sharex=True, sharey=True,
                             squeeze=False, constrained_layout=True)
    for ax, group in zip(axes[:, 0], groups):
        for y in (d["start"], d["min"]):
            ax.axhline(y, color=RULE, lw=0.8, zorder=0)
        for x, _, _ in data["sessions"][1:]:
            ax.axvline(x, color=MUTED, lw=0.8, ls=(0, (2, 3)), zorder=0)
        if group in data["warmup"]:
            ax.axvspan(data["selections"][group][0] - 0.5, data["warm_from"].get(group, n), color="#EEEEEE", lw=0, zorder=0)
        for tier, (label, colour) in TIERS.items():
            pts = data["lines"].get((tier, group))
            if pts:
                x, y = zip(*pts)
                ax.step((*x, n), (*y, y[-1]), where="post", color=colour, lw=2, label=label)
        mine, hits = data["selections"][group], data["accidents"][group]
        ax.plot(mine, [d["min"] - 30] * len(mine), "|", color=RULE, ms=5, mew=1, label="Selection in this group")
        ax.plot(hits, [d["min"] - 30] * len(hits), "|", color=INK, ms=9, mew=1.4, label="Accident")
        ax.set_title(f"{group}: {len(mine)} selections, {len(hits)} accidents",
                     loc="left", fontsize=10, color=INK)
        ax.set_ylabel("Dwell (ms)", color=INK)
        ax.spines[["top", "right"]].set_visible(False)

    top = axes[0, 0]
    for i, (x, label, _) in enumerate(data["sessions"]):
        end = data["sessions"][i + 1][0] if i + 1 < len(data["sessions"]) else n
        if end - x < 0.04 * n:                       # too short to label without overlapping
            continue
        top.text((x + end) / 2, d["max"] + 40, label, ha="center", va="bottom", fontsize=8, color=MUTED)
    top.set_ylim(d["min"] - 60, d["max"] + 140)
    top.set_yticks(range(d["min"], d["max"] + 1, 200))
    top.set_xlim(0, n)
    top.legend(frameon=False, loc="upper right", fontsize=8, ncol=3, bbox_to_anchor=(1, 0.92))
    axes[-1, 0].set_xlabel("Selections, all sessions in order (dotted lines start a new session)")
    fig.suptitle(f"How the dwell learner changed the dwell: {person}", x=0.01, ha="left", fontsize=12)

    path = Path(out) if out else OUT / f"dwell_{person}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f"saved {shown} ({person}, {n} selections in {len(data['sessions'])} sessions)")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--person", required=True, help="folder in data/, for example P01-gaze")
    plot(ap.parse_args().person)

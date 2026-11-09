"""Plot how the learned dwell changes over a few minutes of use.

    python tests/plot_dwell.py                 # both figures, first 5 minutes
    python tests/plot_dwell.py --minutes 10
    python tests/plot_dwell.py --person sinngam01 --session 20261109-203807

Two figures go to result/:
  dwell_simulated.png  the real learner, driven by simulated people (tests/simulate.py habits),
                       20 runs each: the line is the middle run, the band holds the middle half.
  dwell_logged.png     a logged session from data/<person>/events.jsonl: the dwell in use at
                       every look, with accidents and give-ups marked. Undo and redo are left
                       out, since the undo strip keeps a fixed dwell.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from communicaid.common import ROOT, Outcome, load_config
from communicaid.policy import AdaptivePolicy
from simulate import DWELL_PEOPLE

OUT = ROOT / "result"
GROUP = "rested+steady"
TIERS = {0: ("Tier 0, letters and navigation", "#4C7DAF", "-"), 1: ("Tier 1, words and edits", "#C77C48", (0, (4, 2)))}
FIXED = ("undo", "redo")    # the undo strip has its own fixed dwell, never learned
MARKS = {"accident": ("x", "#B23A48", "accident"), "gave_up": ("o", "#7A7A7A", "gave up")}


def style(ax, config: dict, minutes: float) -> None:
    d = config["dwell"]
    for y, label in ((d["start"], "start"), (d["min"], "floor")):
        ax.axhline(y, color="#B8B8B8", lw=0.8, ls=(0, (3, 3)), zorder=0)
        ax.text(minutes, y, f" {label} {y} ms", va="center", ha="left", fontsize=8, color="#8A8A8A")
    ax.set_xlim(0, minutes)
    ax.set_ylim(d["min"] - 150, d["max"] + 50)
    ax.set_xlabel("minutes of use")
    ax.set_ylabel("dwell (ms)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#EEEEEE", lw=0.8)


# ---------- simulated people ----------

def simulate_run(person: dict, minutes: float, seed: int, config: dict, letter_share: float = 0.6):
    """One person using the app for `minutes`, looks on tier 0 and tier 1 buttons mixed.

    Rough timing: a meant look lasts until it fires (or until patience runs out), a stray glance
    until it ends (or fires), then the eyes move on after a short pause. An accident costs an undo.
    """
    rng = np.random.default_rng(seed)
    policy = AdaptivePolicy(config, rng)
    t, times, dwell = 0.0, [0.0], {0: [config["dwell"]["start"]], 1: [config["dwell"]["start"]]}
    while t < minutes * 60:
        tier = 0 if rng.random() < letter_share else 1
        d = policy.dwell_for(tier, GROUP)
        if rng.random() < person["intended"]:
            patience = rng.lognormal(np.log(person["patience"]), 0.35)
            if patience < d:
                o, spent = Outcome("dwell", "gave_up", "key:a", tier, GROUP, dwell=d, duration=patience), patience
            else:
                o, spent = Outcome("dwell", "worked", "key:a", tier, GROUP, dwell=d), d + 300
        else:
            glance = rng.exponential(person["stray"])
            if glance >= d:
                o, spent = Outcome("dwell", "accident", "key:a", tier, GROUP, dwell=d), d + 2500
            else:
                o, spent = Outcome("dwell", "passed_by", "key:a", tier, GROUP, dwell=d, duration=glance), glance
        policy.learn(o)
        t += spent / 1000 + 0.3 + rng.exponential(0.4)
        times.append(t / 60)
        for k in (0, 1):
            dwell[k].append(policy.dwell.dwell_for(k, GROUP))
    return np.array(times), {k: np.array(v) for k, v in dwell.items()}


def plot_simulated(minutes: float, runs: int, config: dict) -> Path:
    grid = np.linspace(0, minutes, 600)
    fig, axes = plt.subplots(1, len(DWELL_PEOPLE), figsize=(11, 4), sharey=True, constrained_layout=True)
    for ax, (name, person) in zip(np.atleast_1d(axes), DWELL_PEOPLE.items()):
        curves = {0: [], 1: []}
        for seed in range(runs):
            times, dwell = simulate_run(person, minutes, seed, config)
            for k in (0, 1):
                idx = np.searchsorted(times, grid, side="right") - 1      # the dwell in use at each moment
                curves[k].append(dwell[k][idx])
        for k, (label, colour, ls) in TIERS.items():
            c = np.array(curves[k])
            lo, mid, hi = np.percentile(c, [25, 50, 75], axis=0)
            ax.fill_between(grid, lo, hi, color=colour, alpha=0.18, lw=0, step="post")
            ax.step(grid, mid, where="post", color=colour, lw=1.8, ls=ls, label=label)
        habits = f"stray glance about {person['stray']} ms, gives up after about {person['patience']} ms"
        ax.set_title(f"Simulated: {name}\n{habits}", fontsize=10, loc="left")
        style(ax, config, minutes)
    np.atleast_1d(axes)[0].legend(frameon=False, fontsize=8, loc="upper right")
    fig.suptitle(f"How the dwell learner moves the dwell ({runs} runs per person, middle run and middle half)",
                 fontsize=11, x=0.01, ha="left")
    path = OUT / "dwell_simulated.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


# ---------- a logged session ----------

def load_session(person: str | None, session: str | None):
    """Looks and outcomes of one session. Without a choice, the session with the most looks."""
    files = [ROOT / "data" / person / "events.jsonl"] if person else sorted((ROOT / "data").glob("*/events.jsonl"))
    sessions: dict[tuple[str, str], dict[str, list]] = defaultdict(lambda: {"look": [], "outcome": []})
    for f in files:
        for line in f.open():
            r = json.loads(line)
            if r.get("event") in ("look", "outcome") and r.get("condition") == "adaptive":
                sessions[(f.parent.name, r["session"])][r["event"]].append(r)
    if session:
        sessions = {k: v for k, v in sessions.items() if k[1] == session}
    if not sessions:
        raise SystemExit("No logged session found with looks in it.")
    key = max(sessions, key=lambda k: len(sessions[k]["look"]))
    return key, sessions[key]


def plot_logged(minutes: float, person: str | None, session: str | None, config: dict) -> Path:
    (who, sid), s = load_session(person, session)
    total = max(r["t"] for r in s["look"]) / 60
    spans = [(minutes, f"first {minutes:g} minutes")] + ([(total, f"whole session, {total:.0f} minutes")]
                                                         if total > minutes * 1.5 else [])
    fig, axes = plt.subplots(1, len(spans), figsize=(5.5 * len(spans), 4), constrained_layout=True, squeeze=False)
    for ax, (span, title) in zip(axes[0], spans):
        for k, (label, colour, ls) in TIERS.items():
            looks = [(r["t"] / 60, r["dwell"]) for r in s["look"]
                     if r["tier"] == k and r["action"] not in FIXED and r["t"] / 60 <= span]
            if not looks:
                continue
            x, y = zip(*looks)
            ax.step(x, y, where="post", color=colour, lw=1.6, ls=ls, label=f"{label} ({len(x)} looks)")
            for kind, (marker, mcolour, mlabel) in MARKS.items():
                hits = [(o["t"] / 60, o["outcome"]["dwell"]) for o in s["outcome"]
                        if o["outcome"]["kind"] == kind and o["outcome"]["tier"] == k
                        and o["outcome"]["learner"] == "dwell" and o["outcome"]["action"] not in FIXED
                        and o["t"] / 60 <= span]
                if hits:
                    hx, hy = zip(*hits)
                    ax.scatter(hx, hy, marker=marker, s=22, color=mcolour, lw=1.2, zorder=3,
                               facecolors="none" if marker == "o" else mcolour,
                               label=f"{mlabel}, tier {k} ({len(hx)})")
        ax.set_title(title, fontsize=10, loc="left")
        style(ax, config, span)
        ax.legend(frameon=False, fontsize=7.5, loc="upper right")
    fig.suptitle(f"Logged session {sid} ({who}): the dwell in use at each look", fontsize=11, x=0.01, ha="left")
    path = OUT / "dwell_logged.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--person", help="folder in data/ (default: any)")
    ap.add_argument("--session", help="session id, e.g. 20261109-203807 (default: the one with most looks)")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    cfg = load_config()
    print("saved", plot_simulated(args.minutes, args.runs, cfg).relative_to(ROOT))
    print("saved", plot_logged(args.minutes, args.person, args.session, cfg).relative_to(ROOT))

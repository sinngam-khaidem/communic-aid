"""
Compare Adaptive and Fixed across participants.

    python tests/compare.py

Uses every participant who has both data/<P>-adaptive and data/<P>-fixed (made by tests/study.py).
From each session's log it takes selections, accidents, undos, give-ups, wrong signals and the dwell
in use. From data/study_forms.csv, if it exists, it adds the SUS score and any task times typed in
from the paper forms. The columns of that file:

    participant, condition, sus1 ... sus10, task1_s, task2_s, task3_s, task4_s

condition is adaptive or fixed. SUS answers are 1 to 5. Task times are optional; leave them empty
if not timed.

Saves into result/study/:
    measures.csv   one row per participant and condition
    compare.md     the median of each condition, and a paired Wilcoxon signed-rank test
    compare.png    each participant's two values joined by a line
"""

from __future__ import annotations

import csv
import itertools
import math
import re
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from communicaid.common import ROOT
from report import FIXED, main_session, read

CONDITIONS = {"fixed": ("Fixed", "#4C7DAF"), "adaptive": ("Adaptive", "#D08A55")}
INK, MUTED = "#333333", "#999999"
FIGURE = ["Accidents per 100 selections", "Give-ups per 100 selections", "Mean dwell, tier 0 (ms)",
          "Mean dwell, tier 1 (ms)", "Total task time (s)", "SUS"]


def participants() -> list[str]:
    """Participants with a folder for both conditions, in number order."""
    names = {d.name for d in (ROOT / "data").iterdir() if d.is_dir()} if (ROOT / "data").exists() else set()
    found = {n.rsplit("-", 1)[0] for n in names if n.endswith(("-adaptive", "-fixed"))}
    both = [p for p in found if f"{p}-adaptive" in names and f"{p}-fixed" in names]
    return sorted(both, key=lambda p: (int(re.search(r"\d+", p).group()) if re.search(r"\d+", p) else 0, p))


def from_log(folder: Path) -> dict[str, float]:
    """The measures that come from one session's log."""
    events = read(folder / "events.jsonl")
    session = main_session(events)
    if session is None:
        return {}
    events = [e for e in events if e.get("session") == session]
    kinds = Counter(e["outcome"]["kind"] for e in events if e["event"] == "outcome" and e["outcome"]["learner"] == "dwell")
    fires = [e for e in events if e["event"] == "fire"]
    picks = sum(f["action"] not in FIXED for f in fires)
    per100 = lambda k: 100 * k / picks if picks else math.nan
    looks = [e for e in events if e["event"] == "look" and e["action"] not in FIXED]
    dwell = lambda tier: (sum(e["dwell"] for e in looks if e["tier"] == tier) / n
                          if (n := sum(e["tier"] == tier for e in looks)) else math.nan)
    return {
        "Session length (min)": (events[-1]["t"] - events[0]["t"]) / 60,
        "Selections": picks,
        "Accidents per 100 selections": per100(kinds["accident"]),
        "Give-ups per 100 selections": per100(kinds["gave_up"]),
        "Undos": sum(f["action"] == "undo" for f in fires),
        "Wrong signals": sum(e["event"] == "wrong" for e in events),
        "Mean dwell, tier 0 (ms)": dwell(0),
        "Mean dwell, tier 1 (ms)": dwell(1),
    }


def sus(row: dict) -> float:
    """Odd items: answer minus 1. Even items: 5 minus answer. Sum times 2.5, from 0 to 100."""
    answers = [float(row[f"sus{i}"]) for i in range(1, 11)]
    return 2.5 * sum(a - 1 if i % 2 == 0 else 5 - a for i, a in enumerate(answers))


def from_forms() -> dict[tuple[str, str], dict[str, float]]:
    """SUS and task times typed in from the paper forms, by (participant, condition)."""
    path = ROOT / "data" / "study_forms.csv"
    if not path.exists():
        return {}
    found = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            got = {}
            if all(row.get(f"sus{i}") for i in range(1, 11)):
                got["SUS"] = sus(row)
            times = [float(row[f"task{i}_s"]) for i in range(1, 5) if row.get(f"task{i}_s")]
            for i in range(1, 5):
                if row.get(f"task{i}_s"):
                    got[f"Task {i} time (s)"] = float(row[f"task{i}_s"])
            if len(times) == 4:
                got["Total task time (s)"] = sum(times)
            found[(row["participant"], row["condition"].lower())] = got
    return found


def ranks(values: list[float]) -> list[float]:
    """Ranks from 1, with tied values sharing their average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def wilcoxon(diffs: list[float]) -> tuple[int, float, float]:
    """Paired Wilcoxon signed-rank test, two sided. Returns (pairs used, W+, p).

    Pairs with no difference are left out. Up to 20 pairs the p value is exact: every way of giving
    the ranks a sign is counted. Above that it uses the normal approximation.
    """
    d = [x for x in diffs if x != 0 and not math.isnan(x)]
    n = len(d)
    if n == 0:
        return 0, 0.0, 1.0
    r = ranks([abs(x) for x in d])
    w = sum(rk for rk, x in zip(r, d) if x > 0)
    if n <= 20:
        sums = [sum(rk for rk, s in zip(r, signs) if s) for signs in itertools.product((0, 1), repeat=n)]
        low = sum(s <= w + 1e-9 for s in sums) / len(sums)
        high = sum(s >= w - 1e-9 for s in sums) / len(sums)
        return n, w, min(1.0, 2 * min(low, high))
    mean, sd = n * (n + 1) / 4, math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    z = (w - mean) / sd
    return n, w, min(1.0, math.erfc(abs(z) / math.sqrt(2)))


def median(values: list[float]) -> float:
    v = sorted(x for x in values if not math.isnan(x))
    if not v:
        return math.nan
    return (v[len(v) // 2] + v[(len(v) - 1) // 2]) / 2


def fmt(x: float) -> str:
    return "n/a" if math.isnan(x) else f"{x:.1f}"


def plot(table: dict, people: list[str], measures: list[str], path: Path) -> None:
    def pairs_of(m: str) -> list[tuple[float, float]]:
        pairs = [(table[(p, "fixed")].get(m, math.nan), table[(p, "adaptive")].get(m, math.nan)) for p in people]
        return [pr for pr in pairs if not any(math.isnan(x) for x in pr)]

    shown = [m for m in FIGURE if m in measures and pairs_of(m)]     # a measure with no data gets no panel
    cols = 3
    rows = math.ceil(len(shown) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(9, 2.9 * rows), squeeze=False, constrained_layout=True)
    for ax, m in zip(axes.flat, shown):
        pairs = pairs_of(m)
        for a, b in pairs:
            ax.plot((0, 1), (a, b), color=MUTED, lw=1, marker="o", ms=3.5, zorder=1)
        for x, (cond, (name, colour)) in enumerate(CONDITIONS.items()):
            mid = median([pr[x] for pr in pairs])
            ax.plot((x - 0.15, x + 0.15), (mid, mid), color=colour, lw=3, zorder=2, solid_capstyle="round")
        ax.set_xticks((0, 1), [name for name, _ in CONDITIONS.values()])
        ax.set_xlim(-0.4, 1.4)
        ax.set_title(m, loc="left", fontsize=10, color=INK)
        ax.spines[["top", "right"]].set_visible(False)
    for ax in list(axes.flat)[len(shown):]:
        ax.set_visible(False)
    fig.suptitle(f"Fixed vs Adaptive, {len(people)} participants (thick bar: median)", x=0.01, ha="left", fontsize=12)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def compare(out: Path | None = None) -> Path:
    out = out or ROOT / "result" / "study"
    people = participants()
    if not people:
        raise SystemExit("No participant has both a -adaptive and a -fixed folder in data/.")
    forms = from_forms()
    table = {}
    for p in people:
        for cond in CONDITIONS:
            table[(p, cond)] = {**from_log(ROOT / "data" / f"{p}-{cond}"), **forms.get((p, cond), {})}
    measures = list(dict.fromkeys(m for row in table.values() for m in row))

    out.mkdir(parents=True, exist_ok=True)
    with (out / "measures.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["participant", "condition", *measures])
        for (p, cond), row in table.items():
            w.writerow([p, cond, *("" if math.isnan(row.get(m, math.nan)) else round(row[m], 2) for m in measures)])

    lines = [f"# Fixed vs Adaptive ({len(people)} participants: {', '.join(people)})", "",
             "Median of each condition. The test is a paired Wilcoxon signed-rank test, two sided; "
             "pairs with no difference are left out, so n can be smaller than the number of participants.", "",
             "| Measure | Fixed | Adaptive | n | W+ | p |", "|---|---|---|---|---|---|"]
    for m in measures:
        fixed = [table[(p, "fixed")].get(m, math.nan) for p in people]
        adapt = [table[(p, "adaptive")].get(m, math.nan) for p in people]
        n, w, pv = wilcoxon([a - b for a, b in zip(adapt, fixed)])
        test = f"{n} | {w:g} | {pv:.3f}" if n else "0 | n/a | n/a"     # no pair differs: nothing to test
        lines.append(f"| {m} | {fmt(median(fixed))} | {fmt(median(adapt))} | {test} |")
    if not forms:
        lines += ["", "No data/study_forms.csv yet, so there is no SUS or task time."]
    (out / "compare.md").write_text("\n".join(lines) + "\n")
    plot(table, people, measures, out / "compare.png")
    print("\n".join(lines))
    print(f"\nsaved {out}")
    return out


if __name__ == "__main__":
    compare()

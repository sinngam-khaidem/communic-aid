"""Draw a gaze heatmap for each app screen from a logged session.

    python tests/plot_heatmap.py --person P01-gaze                       # that person's latest session
    python tests/plot_heatmap.py --person P01-gaze --session 20261111-140000

Reads data/<person>/gaze.jsonl (gaze points) and events.jsonl (page size and button layout).
Saves result/heatmap_<person>_<screen>.png, one per screen with enough gaze on it.
Frozen points (eyes closed) are left out.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

from communicaid.common import ROOT
from communicaid.persist import GAZE_HZ

OUT = ROOT / "result"
BIN_PX = 4            # heatmap cell size
BLUR_PX = 24          # how far one gaze point spreads
MIN_SECONDS = 3       # skip screens looked at for less than this


def read(path):
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def load(person: str, session: str | None):
    folder = ROOT / "data" / person
    gaze = read(folder / "gaze.jsonl")
    if not gaze:
        raise SystemExit(f"No gaze logged for {person}.")
    session = session or gaze[-1]["session"]
    points = defaultdict(list)
    pointing = "gaze"
    for g in gaze:
        if g["session"] == session and g.get("valid") and not g.get("frozen") and g.get("screen"):
            points[g["screen"]].append((g["x"], g["y"]))
            pointing = g.get("pointing", pointing)
    # A screen can change its buttons (the keyboard opens a letter group), so draw the layout it showed longest.
    size, shown, current, since, t = (1440, 900), defaultdict(float), None, 0.0, 0.0
    for e in read(folder / "events.jsonl"):
        if e.get("session") != session:
            continue
        t = e["t"]
        if e["event"] == "screen":
            size = (int(e["w"]), int(e["h"]))
        elif e["event"] == "layout" and e.get("screen"):
            if current is not None:
                shown[current] += t - since
            current, since = (e["screen"], json.dumps(e["buttons"])), t
    if current is not None:
        shown[current] += t - since
    layouts = {}
    for (screen, buttons), seconds in sorted(shown.items(), key=lambda kv: kv[1]):
        layouts[screen] = json.loads(buttons)
    return session, pointing, size, points, layouts


def blur(grid: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur along both axes, with numpy only."""
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    grid = np.apply_along_axis(lambda row: np.convolve(row, k, mode="same"), 1, grid)
    return np.apply_along_axis(lambda col: np.convolve(col, k, mode="same"), 0, grid)


def plot(person: str, session: str | None) -> None:
    session, pointing, (w, h), points, layouts = load(person, session)
    OUT.mkdir(exist_ok=True)
    saved = 0
    for screen, pts in sorted(points.items()):
        seconds = len(pts) / GAZE_HZ
        if seconds < MIN_SECONDS:
            continue
        xy = np.asarray(pts)
        grid, _, _ = np.histogram2d(xy[:, 1], xy[:, 0], bins=(h // BIN_PX, w // BIN_PX), range=((0, h), (0, w)))
        heat = blur(grid, BLUR_PX / BIN_PX)
        heat = np.where(heat > heat.max() * 0.03, heat, np.nan)   # leave unlooked areas blank

        fig, ax = plt.subplots(figsize=(9, 9 * h / w), constrained_layout=True)
        ax.imshow(heat, extent=(0, w, h, 0), cmap="Blues", interpolation="bilinear", alpha=0.85, zorder=1)
        for b in layouts.get(screen, []):
            ax.add_patch(Rectangle((b["x"], b["y"]), b["w"], b["h"], fill=False, lw=0.8, ec="#9AA0A8", zorder=2))
            ax.text(b["x"] + 4, b["y"] + 4, b["action"], fontsize=6, color="#5E636B", va="top", zorder=3)
        ax.set_xlim(0, w)
        ax.set_ylim(h, 0)
        ax.set_xticks([])
        ax.set_yticks([])
        for side in ax.spines.values():
            side.set_color("#D5D5D5")
        ax.set_title(f"Where {person} looked: {screen} screen  ({seconds:.0f} s of gaze, {pointing} pointing)",
                     loc="left", fontsize=11)
        path = OUT / f"heatmap_{person}_{screen}.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        saved += 1
        print(f"saved {path.relative_to(ROOT)}")
    if not saved:
        print(f"No screen had {MIN_SECONDS} s or more of gaze in session {session}.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--person", required=True, help="folder in data/, for example P01-gaze")
    ap.add_argument("--session", help="session id (default: the latest)")
    args = ap.parse_args()
    plot(args.person, args.session)

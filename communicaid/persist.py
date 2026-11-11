"""Persist: write logs and save state per person (DESIGN_PLAN 6.7 and 10).

Listens to every event. Nothing listens to Persist. Message text is never logged.

Three files per person in data/<person>/:
  events.jsonl  one line per event, plus a "layout" line whenever the buttons on screen change
  gaze.jsonl    the gaze point GAZE_HZ times a second, with the screen name and eye position (heatmaps)
  frames.jsonl  every raw phone frame, only with --raw
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .common import Bus, Clock, Frame, Outcome

# High-rate or bulky events that are not worth a line each.
SKIP = {"frame", "gaze", "tick", "button", "dim", "targets", "state", "dwell_now", "calib_dot", "check_prompt",
        "preview"}   # face pictures are shown live only, never stored

GAZE_HZ = 30         # gaze points saved per second, enough for heatmaps


def _clean(value):
    if isinstance(value, Outcome):
        return value.to_dict()
    if isinstance(value, Frame):
        return value.__dict__
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


class Persist:
    def __init__(self, bus: Bus, clock: Clock, root: Path, person: str, meta: dict, raw: bool = False) -> None:
        self.clock, self.meta = clock, meta
        self.dir = root / "data" / person
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events = open(self.dir / "events.jsonl", "a", buffering=1)
        self.frames = open(self.dir / "frames.jsonl", "a", buffering=1) if raw else None
        self.gaze = open(self.dir / "gaze.jsonl", "a", buffering=1)
        self.screen: str | None = None           # the app screen being shown, from the chat state
        self.eye: tuple | None = None            # last eye position from the phone
        self.last_gaze = -1e9
        self.last_layout: list | None = None
        bus.on_all(self._log)

    def _log(self, event: str, payload: dict) -> None:
        if event == "frame":
            self.eye = payload["frame"].eye
            if self.frames:
                self.frames.write(json.dumps({"t": self.clock.now(), **payload["frame"].__dict__}) + "\n")
        elif event == "state":
            self.screen = payload["state"].get("screen")
        elif event == "gaze":
            self._gaze(payload)
        elif event == "targets":
            self._layout(payload["targets"])
        if event in SKIP:
            return
        self._write(event, _clean(payload))

    def _write(self, event: str, payload: dict) -> None:
        line = {"t": round(self.clock.now(), 3), "wall": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "session": self.meta["session"], "condition": self.meta["condition"],
                "pointing": self.meta.get("pointing", "gaze"),
                "costs": self.meta["config"]["costs"]["version"], "event": event, **payload}
        self.events.write(json.dumps(line, default=str) + "\n")

    def _gaze(self, p: dict) -> None:
        """One gaze point every 1/GAZE_HZ s, in the page's own pixels."""
        now = self.clock.now()
        if now - self.last_gaze < 0.8 / GAZE_HZ:      # a little slack, so 60 fps input gives a steady 30
            return
        self.last_gaze = now
        line = {"t": round(now, 3), "session": self.meta["session"], "pointing": self.meta.get("pointing", "gaze"),
                "screen": self.screen, "valid": bool(p.get("valid"))}
        if p.get("valid"):
            line.update(x=round(p["x"], 1), y=round(p["y"], 1), frozen=bool(p.get("frozen")))
        if self.eye is not None:
            line["eye_mm"] = [round(v * 1000, 1) for v in self.eye]     # to check the head stayed still
        self.gaze.write(json.dumps(line) + "\n")

    def _layout(self, targets) -> None:
        """The buttons on screen, logged only when they change, so heatmaps can show the real layout."""
        buttons = [{"action": t.action, "x": round(t.x), "y": round(t.y), "w": round(t.w), "h": round(t.h)}
                   for t in targets]
        if buttons != self.last_layout:
            self.last_layout = buttons
            self._write("layout", {"screen": self.screen, "buttons": buttons})

    def save(self, name: str, data) -> None:
        if data is None:
            return
        tmp = self.dir / f"{name}.json.tmp"
        tmp.write_text(json.dumps(_clean(data), indent=1))
        tmp.replace(self.dir / f"{name}.json")

    def load(self, name: str):
        path = self.dir / f"{name}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def close(self) -> None:
        self.events.close()
        self.gaze.close()
        if self.frames:
            self.frames.close()

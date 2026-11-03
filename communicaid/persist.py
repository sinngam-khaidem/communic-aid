"""Persist: write logs and save state per person (DESIGN_PLAN 6.7 and 10).

Listens to every event. Nothing listens to Persist. Message text is never logged.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .common import Bus, Clock, Frame, Outcome

# High-rate or bulky events that are not worth a line each.
SKIP = {"frame", "gaze", "tick", "button", "dim", "targets", "state", "dwell_now", "calib_dot", "check_prompt",
        "preview"}   # face pictures are shown live only, never stored


def _clean(value):
    if isinstance(value, Outcome):
        return value.to_dict()
    if isinstance(value, Frame):
        return value.__dict__
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
        bus.on_all(self._log)

    def _log(self, event: str, payload: dict) -> None:
        if event == "frame" and self.frames:
            self.frames.write(json.dumps({"t": self.clock.now(), **payload["frame"].__dict__}) + "\n")
        if event in SKIP:
            return
        line = {"t": round(self.clock.now(), 3), "wall": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "session": self.meta["session"], "condition": self.meta["condition"],
                "costs": self.meta["config"]["costs"]["version"], "event": event, **_clean(payload)}
        self.events.write(json.dumps(line, default=str) + "\n")

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
        if self.frames:
            self.frames.close()

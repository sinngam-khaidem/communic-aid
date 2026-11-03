"""Context: which group the person is in right now (DESIGN_PLAN 6.3), and tracking quality (3.8)."""

from __future__ import annotations

import statistics
from collections import deque

from .common import Bus, Clock


class Context:
    def __init__(self, bus: Bus, clock: Clock, config: dict) -> None:
        self.bus, self.clock = bus, clock
        c = config["context"]
        self.cfg = c
        self.lost_s = config["interaction"]["lost_ms"] / 1000
        self.start = clock.now()
        self.slips: deque[bool] = deque(maxlen=c["slip_window"])
        self.spreads: deque[float] = deque(maxlen=c["shaky_looks"])
        self.baseline = float(c["baseline_spread_px"])
        self.points: deque[tuple[float, float, float]] = deque(maxlen=600)
        self.frames: deque[tuple[float, bool]] = deque()
        self.dist: float | None = None
        self.invalid_since: float | None = None
        self.state: dict = {}
        self.banner: str | None = None
        self.next_eval = 0.0

        bus.on("frame", self._frame)
        bus.on("gaze", self._gaze)
        bus.on("look", self._look)
        bus.on("outcome", self._outcome)
        bus.on("calib_done", self._calib)
        bus.on("tick", lambda p: self.evaluate(self.clock.now()))

    # ---------- inputs ----------

    def _frame(self, p: dict) -> None:
        f = p["frame"]
        now = self.clock.now()
        self.frames.append((now, f.tracked))
        while self.frames and now - self.frames[0][0] > self.cfg["tracking_window_s"]:
            self.frames.popleft()
        self.dist = f.dist if f.tracked else None

    def _gaze(self, p: dict) -> None:
        now = self.clock.now()
        if p.get("valid"):
            self.invalid_since = None
            if not p.get("frozen"):
                self.points.append((now, p["x"], p["y"]))
        elif self.invalid_since is None:
            self.invalid_since = now

    def _look(self, p: dict) -> None:
        pts = [(x, y) for t, x, y in self.points if p["start"] <= t <= p["end"]]
        if len(pts) >= 5:
            cx = sum(x for x, _ in pts) / len(pts)
            cy = sum(y for _, y in pts) / len(pts)
            self.spreads.append(sum(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for x, y in pts) / len(pts))

    def _outcome(self, p: dict) -> None:
        kind = p["outcome"].kind
        if kind != "passed_by":
            self.slips.append(kind in ("accident", "gave_up"))

    def _calib(self, p: dict) -> None:
        if p.get("spread_px"):
            self.baseline = max(1.0, float(p["spread_px"]))

    # ---------- decisions ----------

    def tired(self, now: float) -> bool:
        return ((now - self.start) / 60 >= self.cfg["tired_minutes"]
                or self.clock.hour() >= self.cfg["tired_hour"]
                or sum(self.slips) >= self.cfg["slip_count"])

    def shaky(self) -> bool:
        if len(self.spreads) < 5:
            return False
        return statistics.median(self.spreads) > self.cfg["shaky_ratio"] * self.baseline

    def poor_tracking(self) -> bool:
        if not self.frames:
            return False
        lost = sum(1 for _, ok in self.frames if not ok)
        return lost / len(self.frames) > self.cfg["poor_fraction"]

    def evaluate(self, now: float) -> None:
        if now < self.next_eval:
            return
        self.next_eval = now + 0.25
        tired, shaky = self.tired(now), self.shaky()
        state = {"group": f"{'tired' if tired else 'rested'}+{'shaky' if shaky else 'steady'}",
                 "tired": tired, "shaky": shaky, "poor_tracking": self.poor_tracking()}
        if state != self.state:
            self.state = state
            self.bus.emit("context", state)
        banner = None
        face_lost = bool(self.frames) and not self.frames[-1][1]
        if face_lost and self.invalid_since is not None and now - self.invalid_since >= self.lost_s:
            banner = "I can't see your eyes. Look at the screen."
        elif self.dist is not None and self.dist < self.cfg["min_dist"]:
            banner = "Move a little further from the screen."
        elif self.dist is not None and self.dist > self.cfg["max_dist"]:
            banner = "Move a little closer to the screen."
        if banner != self.banner:
            self.banner = banner
            self.bus.emit("banner", {"text": banner})

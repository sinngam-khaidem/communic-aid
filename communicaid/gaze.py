"""Input: turn frames into a gaze point (DESIGN_PLAN 3.2).

Calibration (9 dots, quadratic fit, reused from ARKitGaze/mac/gaze_receiver.py), smoothing,
freezing while the eyes are closed, and slow drift correction from successful selections.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np

from .common import Bus, Clock, Frame

DOTS = [(fx, fy) for fy in (0.1, 0.5, 0.9) for fx in (0.1, 0.5, 0.9)]


def features(yaw, pitch):
    """Quadratic basis. Absorbs axis flips and mild lens or geometry distortion."""
    yaw = np.asarray(yaw, dtype=float)
    pitch = np.asarray(pitch, dtype=float)
    return np.stack([np.ones_like(yaw), yaw, pitch, yaw * pitch, yaw**2, pitch**2], axis=-1)


def angles(d: tuple[float, float, float]) -> tuple[float, float]:
    dx, dy, dz = d
    return math.degrees(math.atan2(dx, dz)), math.degrees(math.atan2(dy, dz))


class Mapping:
    """Yaw and pitch in degrees to screen pixels."""

    def __init__(self, coef_x, coef_y, mu, sigma) -> None:
        self.coef_x, self.coef_y = np.asarray(coef_x), np.asarray(coef_y)
        self.mu, self.sigma = np.asarray(mu), np.asarray(sigma)

    @classmethod
    def fit(cls, observations, targets) -> tuple["Mapping", float]:
        """Least squares on standardised angles with a small ridge term (same as gaze_receiver.py)."""
        obs, tgt = np.asarray(observations, float), np.asarray(targets, float)
        mu, sigma = obs.mean(axis=0), obs.std(axis=0)
        sigma[sigma < 1e-6] = 1.0
        z = (obs - mu) / sigma
        A = features(z[:, 0], z[:, 1])
        gram = A.T @ A + 1e-2 * np.eye(A.shape[1])
        m = cls(np.linalg.solve(gram, A.T @ tgt[:, 0]), np.linalg.solve(gram, A.T @ tgt[:, 1]), mu, sigma)
        pred = np.array([m.predict(*o) for o in obs])
        return m, float(np.sqrt(((pred - tgt) ** 2).sum(axis=1).mean()))

    def predict(self, yaw: float, pitch: float) -> tuple[float, float]:
        z = (np.array([yaw, pitch]) - self.mu) / self.sigma
        f = features(z[0], z[1])
        return float(f @ self.coef_x), float(f @ self.coef_y)

    def to_dict(self) -> dict:
        return {"coef_x": self.coef_x.tolist(), "coef_y": self.coef_y.tolist(),
                "mu": self.mu.tolist(), "sigma": self.sigma.tolist()}


class Gaze:
    def __init__(self, bus: Bus, clock: Clock, config: dict) -> None:
        self.bus, self.clock = bus, clock
        g = config["gaze"]
        self.alpha = g["smoothing_alpha"]
        self.drift_rate, self.drift_cap = g["drift_rate"], g["drift_cap_px"]
        self.drift_window = g["drift_window_ms"] / 1000
        self.settle, self.collect = g["calib_settle_s"], g["calib_collect_s"]
        self.redo_px = g["calib_redo_px"]
        self.closed_level = config["signals"]["closed_level"]

        self.mapping: Mapping | None = None
        self.spread_px: float | None = None
        self.smoothed: tuple[float, float] | None = None
        self.offset = np.zeros(2)
        self.history: deque[tuple[float, float, float]] = deque(maxlen=120)
        self.screen = (1440.0, 900.0)
        self.calib: dict | None = None

        bus.on("frame", lambda p: self.on_frame(p["frame"]))
        bus.on("screen", lambda p: setattr(self, "screen", (float(p["w"]), float(p["h"]))))
        bus.on("levels", lambda p: setattr(self, "closed_level", p["closed_level"]))
        bus.on("start_calibration", lambda p: self.start_calibration())
        bus.on("outcome", self._drift)

    # ---------- every frame ----------

    def on_frame(self, f: Frame) -> None:
        now = self.clock.now()
        if self.calib is not None:
            self._calibrate_step(f, now)
            return
        if not f.tracked:
            self.bus.emit("gaze", {"t": now, "valid": False})
            return
        if f.blink_l > self.closed_level and f.blink_r > self.closed_level and self.smoothed is not None:
            # ARKit's gaze swings as the lids come down: hold the last good point.
            x, y = self._shown()
            self.bus.emit("gaze", {"t": now, "valid": True, "frozen": True, "x": x, "y": y})
            return
        raw = self._raw_point(f)
        if raw is None:
            self.bus.emit("gaze", {"t": now, "valid": False})
            return
        if self.smoothed is None:
            self.smoothed = raw
        else:
            a = self.alpha
            self.smoothed = (a * raw[0] + (1 - a) * self.smoothed[0], a * raw[1] + (1 - a) * self.smoothed[1])
        self.history.append((now, *self.smoothed))
        x, y = self._shown()
        self.bus.emit("gaze", {"t": now, "valid": True, "frozen": False, "x": x, "y": y})

    def _raw_point(self, f: Frame) -> tuple[float, float] | None:
        if f.point is not None:
            return f.point
        if f.dir is not None and self.mapping is not None:
            return self.mapping.predict(*angles(f.dir))
        return None

    def _shown(self) -> tuple[float, float]:
        return self.smoothed[0] + self.offset[0], self.smoothed[1] + self.offset[1]

    # ---------- drift correction ----------

    def _drift(self, p: dict) -> None:
        o = p["outcome"]
        if o.kind != "worked" or o.center is None or self.mapping is None:
            return
        pts = [(x, y) for t, x, y in self.history if o.fired_at - self.drift_window <= t <= o.fired_at]
        if not pts:
            return
        mean = np.mean(pts, axis=0) + self.offset
        self.offset += self.drift_rate * (np.asarray(o.center) - mean)
        size = float(np.linalg.norm(self.offset))
        if size > self.drift_cap:
            self.offset *= self.drift_cap / size
            self.bus.emit("drift_capped", {"offset": self.offset.tolist()})

    # ---------- calibration ----------

    def start_calibration(self) -> None:
        self.calib = {"i": -1, "started": 0.0, "samples": [], "obs": [], "targets": [], "spreads": []}
        self.offset[:] = 0
        self._next_dot(self.clock.now())

    def _next_dot(self, now: float) -> None:
        c = self.calib
        c["i"] += 1
        c["started"], c["samples"] = now, []
        if c["i"] >= len(DOTS):
            self._finish_calibration()
            return
        fx, fy = DOTS[c["i"]]
        x, y = fx * self.screen[0], fy * self.screen[1]
        c["targets"].append((x, y))
        self.bus.emit("calib_dot", {"x": x, "y": y, "i": c["i"], "n": len(DOTS)})

    def _calibrate_step(self, f: Frame, now: float) -> None:
        c = self.calib
        if f.point is not None:
            # Mouse test mode has nothing to calibrate.
            self.calib = None
            self.bus.emit("calib_done", {"error_px": 0.0, "spread_px": None, "ok": True})
            return
        elapsed = now - c["started"]
        if elapsed >= self.settle and f.tracked and f.dir is not None:
            c["samples"].append(angles(f.dir))
        if elapsed >= self.settle + self.collect:
            if c["samples"]:
                s = np.asarray(c["samples"])
                c["obs"].append(s.mean(axis=0))
                c["spreads"].append(s)
            else:
                c["targets"].pop()
            self._next_dot(now)

    def _finish_calibration(self) -> None:
        c, self.calib = self.calib, None
        if len(c["obs"]) < 6:
            self.bus.emit("calib_done", {"error_px": None, "spread_px": None, "ok": False})
            return
        self.mapping, error = Mapping.fit(c["obs"], c["targets"])
        # Spread of gaze while holding still on a dot: the steady baseline for "shaky gaze?".
        spreads = []
        for s in c["spreads"]:
            pts = np.array([self.mapping.predict(*a) for a in s])
            spreads.append(float(np.linalg.norm(pts - pts.mean(axis=0), axis=1).mean()))
        self.spread_px = float(np.median(spreads))
        self.smoothed = None
        self.bus.emit("calib_done", {"error_px": error, "spread_px": self.spread_px,
                                     "ok": error <= self.redo_px})

    # ---------- saving ----------

    def save(self) -> dict | None:
        if self.mapping is None:
            return None
        return {**self.mapping.to_dict(), "spread_px": self.spread_px}

    def load(self, saved: dict | None) -> None:
        if saved:
            self.mapping = Mapping(saved["coef_x"], saved["coef_y"], saved["mu"], saved["sigma"])
            self.spread_px = saved.get("spread_px")

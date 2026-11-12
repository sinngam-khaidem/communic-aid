"""Input: turn frames into a gaze point.

Calibration (9 dots, quadratic fit), smoothing,
freezing while the eyes are closed, and slow drift correction from successful selections.

Two things keep it accurate in real use:
  * Head compensation. When the phone sends the eye position, the gaze ray is intersected with
    the phone's plane (the screen plane) and that point is mapped, so moving the head does not
    move the gaze. Older phone builds without the eye position fall back to the ray's angles.
  * Screen anchoring. The mapping is learned in screen pixels. The view reports where its page
    sits on the screen, so leaving full screen or moving the window does not shift the gaze.

Pointing "head" (the head only study mode) uses where the nose points instead of the gaze,
with the same plane, calibration, smoothing and drift correction.
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


def on_plane(eye: tuple[float, float, float], d: tuple[float, float, float]) -> tuple[float, float] | None:
    """Where the gaze ray meets the phone's plane (z = 0 in camera space), in millimetres."""
    ex, ey, ez = eye
    dx, dy, dz = d
    if abs(dz) < 1e-6:
        return None
    t = -ez / dz
    if t <= 0:
        return None
    return (ex + t * dx) * 1000, (ey + t * dy) * 1000


def ray(f: Frame, pointing: str) -> tuple[float, float, float] | None:
    """The direction that moves the cursor: the eyes' gaze, or where the nose points."""
    return f.head if pointing == "head" else f.dir


def reading(f: Frame, basis: str, pointing: str = "gaze") -> tuple[float, float] | None:
    """The two numbers the mapping uses for this frame."""
    d = ray(f, pointing)
    if d is None:
        return None
    if basis == "plane":
        return on_plane(f.eye, d) if f.eye is not None else None
    return angles(d)


class Mapping:
    """Gaze readings (plane point in mm, or yaw and pitch in degrees) to screen pixels."""

    def __init__(self, coef_x, coef_y, mu, sigma, basis: str = "angles", pointing: str = "gaze") -> None:
        self.coef_x, self.coef_y = np.asarray(coef_x), np.asarray(coef_y)
        self.mu, self.sigma = np.asarray(mu), np.asarray(sigma)
        self.basis, self.pointing = basis, pointing

    @classmethod
    def fit(cls, observations, targets, basis: str = "angles", pointing: str = "gaze") -> tuple["Mapping", float]:
        """Least squares on standardised readings with a small ridge term."""
        obs, tgt = np.asarray(observations, float), np.asarray(targets, float)
        mu, sigma = obs.mean(axis=0), obs.std(axis=0)
        sigma[sigma < 1e-6] = 1.0
        z = (obs - mu) / sigma
        A = features(z[:, 0], z[:, 1])
        gram = A.T @ A + 1e-2 * np.eye(A.shape[1])
        m = cls(np.linalg.solve(gram, A.T @ tgt[:, 0]), np.linalg.solve(gram, A.T @ tgt[:, 1]), mu, sigma, basis, pointing)
        pred = np.array([m.predict(*o) for o in obs])
        return m, float(np.sqrt(((pred - tgt) ** 2).sum(axis=1).mean()))

    def predict(self, yaw: float, pitch: float) -> tuple[float, float]:
        z = (np.array([yaw, pitch]) - self.mu) / self.sigma
        f = features(z[0], z[1])
        return float(f @ self.coef_x), float(f @ self.coef_y)

    def to_dict(self) -> dict:
        return {"coef_x": self.coef_x.tolist(), "coef_y": self.coef_y.tolist(),
                "mu": self.mu.tolist(), "sigma": self.sigma.tolist(), "basis": self.basis, "pointing": self.pointing}


class Gaze:
    def __init__(self, bus: Bus, clock: Clock, config: dict, pointing: str = "gaze") -> None:
        self.bus, self.clock = bus, clock
        self.pointing = pointing            # "gaze": the eyes move the cursor. "head": the nose does.
        self.warned_no_head = False
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
        self.screen = (1440.0, 900.0)       # page size
        self.origin = np.zeros(2)           # where the page's top left sits on the screen
        self.calib: dict | None = None
        self.last_frame: float | None = None

        bus.on("frame", lambda p: self.on_frame(p["frame"]))
        bus.on("screen", self._screen)
        bus.on("levels", lambda p: setattr(self, "closed_level", p["closed_level"]))
        bus.on("start_calibration", lambda p: self.start_calibration())
        bus.on("outcome", self._drift)

    def _screen(self, p: dict) -> None:
        self.screen = (float(p["w"]), float(p["h"]))
        self.origin = np.array([float(p.get("ox", 0.0)), float(p.get("oy", 0.0))])

    # ---------- every frame ----------

    def on_frame(self, f: Frame) -> None:
        now = self.clock.now()
        self._check_head(f)
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
        """A point in screen pixels (or the mouse's page point in test mode)."""
        if f.point is not None:
            return f.point[0] + self.origin[0], f.point[1] + self.origin[1]
        if self.mapping is None:
            return None
        r = reading(f, self.mapping.basis, self.pointing)
        return self.mapping.predict(*r) if r is not None else None

    def _check_head(self, f: Frame) -> None:
        """Head pointing needs a phone build that sends the head direction. Say so once."""
        if self.pointing == "head" and f.tracked and f.dir is not None and f.head is None and not self.warned_no_head:
            self.warned_no_head = True
            self.bus.emit("notice", {"text": "The phone app does not send the head direction. Update it to use head pointing."})

    def _shown(self) -> tuple[float, float]:
        """The smoothed screen point, corrected for drift, in the page's own pixels."""
        return (self.smoothed[0] + self.offset[0] - self.origin[0],
                self.smoothed[1] + self.offset[1] - self.origin[1])

    # ---------- drift correction ----------

    def _drift(self, p: dict) -> None:
        o = p["outcome"]
        if o.kind != "worked" or o.center is None or self.mapping is None:
            return
        pts = [(x, y) for t, x, y in self.history if o.fired_at - self.drift_window <= t <= o.fired_at]
        if not pts:
            return
        mean = np.mean(pts, axis=0) + self.offset
        center = np.asarray(o.center) + self.origin          # page pixels to screen pixels
        self.offset += self.drift_rate * (center - mean)
        size = float(np.linalg.norm(self.offset))
        if size > self.drift_cap:
            self.offset *= self.drift_cap / size
            self.bus.emit("drift_capped", {"offset": self.offset.tolist()})

    # ---------- calibration ----------

    def start_calibration(self) -> None:
        self.calib = {"i": -1, "started": 0.0, "samples": [], "obs": [], "targets": [], "spreads": [], "basis": None}
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
        c["targets"].append((x + self.origin[0], y + self.origin[1]))     # learned in screen pixels
        self.bus.emit("calib_dot", {"x": x, "y": y, "i": c["i"], "n": len(DOTS)})

    def _calibrate_step(self, f: Frame, now: float) -> None:
        c = self.calib
        if f.point is not None:
            # Mouse test mode has nothing to calibrate.
            self.calib = None
            self.bus.emit("calib_done", {"error_px": 0.0, "spread_px": None, "ok": True})
            return
        # If phone data paused or the face was lost, this dot starts over instead of being skipped.
        paused = self.last_frame is None or now - self.last_frame > 0.5
        self.last_frame = now
        if paused or not f.tracked:
            c["started"], c["samples"] = now, []
            return
        if c["basis"] is None and f.tracked and ray(f, self.pointing) is not None:
            c["basis"] = "plane" if f.eye is not None else "angles"
        elapsed = now - c["started"]
        eyes_closed = f.blink_l > self.closed_level or f.blink_r > self.closed_level
        r = reading(f, c["basis"], self.pointing) if c["basis"] and f.tracked and not eyes_closed else None
        if elapsed >= self.settle and r is not None:
            c["samples"].append(r)
        if elapsed >= self.settle + self.collect:
            if len(c["samples"]) >= 5:
                s = np.asarray(c["samples"])
                c["obs"].append(np.median(s, axis=0))          # median: a stray glance or blink cannot pull it
                c["spreads"].append(s)
            else:
                c["targets"].pop()
            self._next_dot(now)

    def _finish_calibration(self) -> None:
        c, self.calib = self.calib, None
        if len(c["obs"]) < 6:
            self.bus.emit("calib_done", {"error_px": None, "spread_px": None, "ok": False,
                                         "dots": len(c["obs"]), "basis": c["basis"], "pointing": self.pointing})
            return
        self.mapping, error = Mapping.fit(c["obs"], c["targets"], c["basis"], self.pointing)
        # Spread of gaze while holding still on a dot: the steady baseline for "shaky gaze?".
        spreads = []
        for s in c["spreads"]:
            pts = np.array([self.mapping.predict(*a) for a in s])
            spreads.append(float(np.linalg.norm(pts - pts.mean(axis=0), axis=1).mean()))
        self.spread_px = float(np.median(spreads))
        self.smoothed = None
        self.bus.emit("calib_done", {"error_px": error, "spread_px": self.spread_px,
                                     "ok": error <= self.redo_px, "dots": len(c["obs"]), "basis": c["basis"],
                                     "pointing": self.pointing})

    # ---------- saving ----------

    def save(self) -> dict | None:
        if self.mapping is None:
            return None
        return {**self.mapping.to_dict(), "spread_px": self.spread_px}

    def load(self, saved: dict | None) -> None:
        # A gaze calibration cannot be used for head pointing, or the other way round: calibrate again.
        if saved and saved.get("pointing", "gaze") == self.pointing:
            self.mapping = Mapping(saved["coef_x"], saved["coef_y"], saved["mu"], saved["sigma"],
                                   saved.get("basis", "angles"), self.pointing)
            self.spread_px = saved.get("spread_px")

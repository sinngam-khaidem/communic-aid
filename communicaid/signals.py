"""Signals: detect blink and hold, raised eyebrows, saying "go" (the "yes" signal) and the switch.

Signals only reports what the person did. Whether it was the signal being asked for is
Interaction's business. Short eye closures and brow lifts are reported as 'attempt', so
Outcomes can tell "gave up" from "blocked an accident".
"""

from __future__ import annotations

from collections import deque

from .common import SIGNALS, Bus, Clock, Frame


def brow_level(f: Frame) -> float:
    return (f.brow_in + f.brow_out_l + f.brow_out_r) / 3


class Hold:
    """Tracks one held movement (eyes closed, brows raised) using the frame's own clock."""

    def __init__(self, hold_s: float, attempt_s: float) -> None:
        self.hold_s, self.attempt_s = hold_s, attempt_s
        self.since: float | None = None
        self.fired = False

    def update(self, active: bool, t: float) -> str | None:
        """Returns 'signal' once when the hold is reached, 'attempt' when a short try ends."""
        if active:
            if self.since is None:
                self.since, self.fired = t, False
            elif not self.fired and t - self.since >= self.hold_s:
                self.fired = True
                return "signal"
            return None
        result = None
        if self.since is not None and not self.fired and t - self.since >= self.attempt_s:
            result = "attempt"
        self.since, self.fired = None, False
        return result

    def reset(self) -> None:
        self.since, self.fired = None, False


class Signals:
    def __init__(self, bus: Bus, clock: Clock, config: dict) -> None:
        self.bus, self.clock = bus, clock
        s = config["signals"]
        self.cfg = s
        self.closed_level = s["closed_level"]
        self.raised_level = s["raised_level"]
        self.open_level = 0.05
        self.brow_rest = 0.05
        self.can_do = {k: True for k in SIGNALS}
        attempt = s["attempt_min_ms"] / 1000
        self.blink = Hold(s["blink_hold_ms"] / 1000, attempt)
        self.brows = Hold(s["brow_hold_ms"] / 1000, attempt)
        self.last_yes = -1e9
        self.presses: deque[float] = deque()
        self.check: SignalCheck | None = None

        bus.on("frame", lambda p: self.on_frame(p["frame"]))
        bus.on("yes", self.on_yes)
        bus.on("press", self.on_press)
        bus.on("start_check", lambda p: self.start_check())
        bus.on("tick", self._tick)

    # ---------- detection ----------

    def on_frame(self, f: Frame) -> None:
        if self.check is not None:
            self.check.on_frame(f)
            return
        if not f.tracked:
            self.blink.reset()
            self.brows.reset()
            return
        closed = f.blink_l > self.closed_level and f.blink_r > self.closed_level
        self._report("blink", self.blink.update(closed, f.t))
        self._report("brows", self.brows.update(brow_level(f) > self.raised_level and not closed, f.t))

    def _report(self, kind: str, what: str | None) -> None:
        if what == "signal":
            self.bus.emit("signal", {"t": self.clock.now(), "kind": kind})
        elif what == "attempt":
            self.bus.emit("attempt", {"t": self.clock.now(), "kind": kind})

    def on_yes(self, p: dict) -> None:
        if self.check is not None:
            self.check.on_event("yes")
            return
        now = self.clock.now()
        if now - self.last_yes >= self.cfg["yes_debounce_s"]:
            self.last_yes = now
            self.bus.emit("signal", {"t": now, "kind": "yes"})

    def on_press(self, p: dict) -> None:
        if self.check is not None:
            self.check.on_event("switch")
            return
        now = self.clock.now()
        self.bus.emit("signal", {"t": now, "kind": "switch"})
        self.presses.append(now)
        while self.presses and now - self.presses[0] > self.cfg["escape_window_s"]:
            self.presses.popleft()
        if len(self.presses) >= self.cfg["escape_presses"]:
            self.presses.clear()
            self.bus.emit("escape", {})

    def _tick(self, p: dict) -> None:
        if self.check is not None:
            self.check.on_tick(self.clock.now())

    # ---------- signal check ----------

    def start_check(self) -> None:
        self.check = SignalCheck(self)
        self.check.begin(self.clock.now())

    def finish_check(self, results: dict[str, int], levels: dict) -> None:
        self.check = None
        need = (2 * self.cfg["check_tries"] + 2) // 3      # 2 out of 3
        self.can_do = {k: results.get(k, 0) >= need for k in SIGNALS}
        self.open_level = levels.get("open", self.open_level)
        self.brow_rest = levels.get("brow_rest", self.brow_rest)
        self.closed_level = levels.get("closed", self.closed_level)
        self.raised_level = levels.get("raised", self.raised_level)
        self.blink.reset()
        self.brows.reset()
        self.bus.emit("levels", self.save())
        self.bus.emit("check_done", {"can_do": self.can_do, "results": results})

    def save(self) -> dict:
        return {"closed_level": self.closed_level, "raised_level": self.raised_level,
                "open_level": self.open_level, "brow_rest": self.brow_rest, "can_do": self.can_do}

    def load(self, saved: dict | None) -> None:
        if not saved:
            return
        self.closed_level = saved["closed_level"]
        self.raised_level = saved["raised_level"]
        self.open_level = saved.get("open_level", self.open_level)
        self.brow_rest = saved.get("brow_rest", self.brow_rest)
        self.can_do = {k: bool(saved["can_do"].get(k, True)) for k in SIGNALS}
        self.bus.emit("levels", self.save())


class SignalCheck:
    """Onboarding check. Sets each person's levels and which signals they can do."""

    STEPS = ("relax_middle", "relax_top", "blink", "brows", "yes", "switch")
    PROMPTS = {
        "relax_middle": "Look at the dot and relax your face.",
        "relax_top": "Now look at the dot at the top. Keep your face relaxed.",
        "blink": "Close both eyes until you hear the tone.",
        "brows": "Raise your eyebrows until you hear the tone.",
        "yes": 'Say "go".',
        "switch": "Press your switch. If you have none, just wait.",
    }

    def __init__(self, signals: Signals) -> None:
        self.s = signals
        self.bus, self.cfg = signals.bus, signals.cfg
        self.step = -1
        self.tries = 0
        self.results: dict[str, int] = {}
        self.samples: dict[str, list] = {"open": [], "brow_mid": [], "brow_top": [], "blink_peak": [], "brow_peak": []}
        self.step_start = 0.0
        self.rest_until = 0.0
        self.peak = 0.0
        self.armed = False
        self.open, self.brow_rest = 0.05, 0.05
        self.hold = Hold(0, 0)

    @property
    def name(self) -> str:
        return self.STEPS[self.step]

    def begin(self, now: float) -> None:
        self._next_step(now)

    def _next_step(self, now: float) -> None:
        self.step += 1
        self.tries = 0
        if self.step >= len(self.STEPS):
            self._finish()
            return
        name = self.name
        self.results.setdefault(name, 0)
        if name == "blink":
            self._set_levels()
            self.hold = Hold(self.cfg["blink_hold_ms"] / 1000, 1)
        elif name == "brows":
            self.hold = Hold(self.cfg["brow_hold_ms"] / 1000, 1)
        self._start_try(now)

    def _start_try(self, now: float) -> None:
        self.step_start, self.peak = now, 0.0
        self.armed = False          # a try only counts once the eyes or brows were relaxed first
        self.hold.reset()
        dot = {"relax_middle": (0.5, 0.5), "relax_top": (0.5, 0.06)}.get(self.name)
        n = self.cfg["check_tries"]
        text = self.PROMPTS[self.name]
        if self.name not in ("relax_middle", "relax_top"):
            text += f"  ({self.tries + 1} of {n})"
        self.bus.emit("check_prompt", {"text": text, "dot": dot, "step": self.name})

    def _set_levels(self) -> None:
        mean = lambda xs, d: sum(xs) / len(xs) if xs else d
        self.open = mean(self.samples["open"], 0.05)
        self.brow_rest = max(mean(self.samples["brow_mid"], 0.05), mean(self.samples["brow_top"], 0.05))

    def on_frame(self, f: Frame) -> None:
        now = self.s.clock.now()
        name = self.name
        if not f.tracked or now < self.rest_until:
            return
        if name == "relax_middle":
            self.samples["open"].append((f.blink_l + f.blink_r) / 2)
            self.samples["brow_mid"].append(brow_level(f))
        elif name == "relax_top":
            self.samples["brow_top"].append(brow_level(f))
        elif name == "blink":
            threshold = self.open + 0.4 * (1 - self.open)
            value = min(f.blink_l, f.blink_r)
            self._held(value > threshold, value, f.t, now, "blink_peak")
        elif name == "brows":
            value = brow_level(f)
            self._held(value > self.brow_rest + 0.15, value, f.t, now, "brow_peak")

    def _held(self, active: bool, value: float, t: float, now: float, key: str) -> None:
        if not self.armed:
            self.armed = not active
            return
        if active:
            self.peak = max(self.peak, value)
        if self.hold.update(active, t) == "signal":
            self.samples[key].append(self.peak)
            self._success(now)

    def on_event(self, kind: str) -> None:
        if self.step >= 0 and self.name == kind and self.s.clock.now() >= self.rest_until:
            self._success(self.s.clock.now())

    def on_tick(self, now: float) -> None:
        if now < self.rest_until:
            return
        if self.rest_until and now >= self.rest_until and self.rest_until > self.step_start:
            self._advance(now)
            return
        name = self.name
        if name in ("relax_middle", "relax_top"):
            if now - self.step_start >= self.cfg["check_relax_s"]:
                self._next_step(now)
        elif now - self.step_start >= self.cfg["check_try_s"]:
            self._advance(now)

    def _success(self, now: float) -> None:
        self.results[self.name] += 1
        self.bus.emit("sound", {"name": "tick"})
        self.rest_until = now + 1.0

    def _advance(self, now: float) -> None:
        self.rest_until = 0.0
        self.tries += 1
        if self.tries >= self.cfg["check_tries"]:
            self._next_step(now)
        else:
            self._start_try(now)

    def _finish(self) -> None:
        mean = lambda xs: sum(xs) / len(xs) if xs else None
        levels = {"open": self.open, "brow_rest": self.brow_rest}
        blink_peak, brow_peak = mean(self.samples["blink_peak"]), mean(self.samples["brow_peak"])
        if blink_peak is not None:
            levels["closed"] = (self.open + blink_peak) / 2
        if brow_peak is not None:
            levels["raised"] = (self.brow_rest + brow_peak) / 2
        results = {k: v for k, v in self.results.items() if k in SIGNALS}
        self.s.finish_check(results, levels)

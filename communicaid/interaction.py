"""Interaction: the life of one button press (DESIGN_PLAN 4.1 and 4.2).

Knows nothing about what buttons do or how learning works. It asks the policy for a dwell
and a check, and reports looks, fires, waits, accepts, wrong signals and timeouts.
"""

from __future__ import annotations

from typing import Protocol

from .common import SIGNALS, Bus, Clock, Target, tier_of

UNDO = ("undo", "redo")


class Policy(Protocol):
    last: dict

    def dwell_for(self, tier: int, group: str) -> int: ...
    def check_for(self, tier: int, group: str, allowed: list[str]) -> str: ...


class Interaction:
    def __init__(self, bus: Bus, clock: Clock, config: dict, policy: Policy, tiers: dict[str, int]) -> None:
        self.bus, self.clock, self.policy, self.tiers = bus, clock, policy, tiers
        c = config["interaction"]
        self.margin = c["margin_px"]
        self.switch_s = c["switch_ms"] / 1000
        self.look_end_s = c["look_end_ms"] / 1000
        self.min_look_s = c["min_look_ms"] / 1000
        self.drain = c["drain_speed"]
        self.wait_s = c["wait_s"]
        self.cancel_wait_s = c["cancel_wait_ms"] / 1000
        self.pause_s = c["pause_ms"] / 1000
        self.lost_s = c["lost_ms"] / 1000
        self.undo_ms = config["dwell"]["undo"]
        self.high_tier_ms = config["dwell"]["high_tier"]

        self.targets: dict[str, Target] = {}
        self.gaze: dict = {"valid": False}
        self.lost_since: float | None = None
        self.current: str | None = None
        self.cand: str | None = None
        self.cand_since = 0.0
        self.off_since: float | None = None
        self.look_start = 0.0
        self.look_filled = False
        self.look_dwell = 0.0
        self.progress: dict[str, float] = {}
        self.phase: dict[str, str] = {}
        self.waiting: dict | None = None
        self.locked: str | None = None
        self.pause_until = 0.0
        self.dimmed = False
        self.last_tick: float | None = None
        self.seq = 0

        self.group = "rested+steady"
        self.poor_tracking = False
        self.enabled = {s: True for s in SIGNALS}
        self.can_do = {s: True for s in SIGNALS}

        bus.on("targets", lambda p: self.set_targets(p["targets"]))
        bus.on("gaze", self._gaze)
        bus.on("signal", self.on_signal)
        bus.on("attempt", self._attempt)
        bus.on("context", self._context)
        bus.on("settings", lambda p: self.enabled.update(p["enabled"]))
        bus.on("levels", lambda p: self.can_do.update(p["can_do"]))
        bus.on("check_done", lambda p: self.can_do.update(p["can_do"]))
        bus.on("tick", lambda p: self.tick(self.clock.now()))

    # ---------- inputs ----------

    def set_targets(self, targets: list[Target]) -> None:
        self.targets = {t.action: t for t in targets}
        if self.waiting and self.waiting["action"] not in self.targets:
            self.waiting = None
        if self.current is not None and self.current not in self.targets:
            self._end_look(self.current, self.clock.now())
            self.current = None
        self.progress = {a: p for a, p in self.progress.items() if a in self.targets}
        self.phase = {a: ph for a, ph in self.phase.items() if a in self.targets}

    def _gaze(self, p: dict) -> None:
        self.gaze = p

    def _context(self, p: dict) -> None:
        self.group = p["group"]
        self.poor_tracking = p["poor_tracking"]

    def _attempt(self, p: dict) -> None:
        if self.waiting:
            self.waiting["attempted"] = True

    def allowed(self, tier: int) -> list[str]:
        options = [s for s in SIGNALS if self.enabled.get(s) and self.can_do.get(s)]
        if self.poor_tracking:
            options = [s for s in options if s not in ("blink", "brows")]
        return (["dwell"] + options) if tier == 2 else options

    # ---------- every tick ----------

    def tick(self, now: float) -> None:
        dt = 0.0 if self.last_tick is None else max(0.0, now - self.last_tick)
        self.last_tick = now
        if self.dimmed and now >= self.pause_until:
            self.dimmed = False
            self.bus.emit("dim", {"on": False})

        g = self.gaze
        if not g.get("valid"):
            self.lost_since = self.lost_since if self.lost_since is not None else now
            if now - self.lost_since >= self.lost_s:
                self._lost(now)
            self._check_wait(now)
            return
        self.lost_since = None
        if g.get("frozen"):
            # Eyes closed: hold everything still, but a waiting button can still be confirmed.
            self._check_wait(now)
            return

        self._update_current(self._hit(g["x"], g["y"]), now)
        if self.locked and self.current != self.locked and now >= self.pause_until:
            self._set_phase(self.locked, "idle", now)
            self.locked = None
        self._check_wait(now)
        if self.waiting is None:
            self._fill(dt, now)

    def _hit(self, x: float, y: float) -> str | None:
        hits = [t for t in self.targets.values() if t.contains(x, y, self.margin)]
        if not hits:
            return None
        return min(hits, key=lambda t: (t.center[0] - x) ** 2 + (t.center[1] - y) ** 2).action

    def _update_current(self, raw: str | None, now: float) -> None:
        if raw == self.current:
            self.off_since, self.cand = None, None
            return
        if self.off_since is None:
            self.off_since = now
        if raw is not None:
            if self.cand != raw:
                self.cand, self.cand_since = raw, now
            elif now - self.cand_since >= self.switch_s:
                self._switch(raw, now)
        else:
            self.cand = None
            if self.current is not None and now - self.off_since >= self.look_end_s:
                self._switch(None, now)

    def _switch(self, new: str | None, now: float) -> None:
        if self.current is not None:
            self._end_look(self.current, self.off_since or now)
        self.current = new
        self.off_since, self.cand = None, None
        if new is not None:
            self.look_start = self.cand_since if self.cand_since <= now else now
            self.look_filled = False
            self.look_dwell = self._dwell_of(new)
            self.bus.emit("look_start", {"action": new, "t": self.look_start})

    def _end_look(self, action: str, left_at: float) -> None:
        duration = left_at - self.look_start
        if duration >= self.min_look_s:
            self.bus.emit("look", {"action": action, "tier": tier_of(action, self.tiers),
                                   "start": self.look_start, "end": left_at,
                                   "filled": self.look_filled, "dwell": self.look_dwell, "group": self.group})

    def _dwell_of(self, action: str) -> float:
        if action in UNDO:
            return self.undo_ms
        tier = tier_of(action, self.tiers)
        if tier >= 2:
            return self.high_tier_ms
        ms = self.policy.dwell_for(tier, self.group)
        self.bus.emit("dwell_now", {"tier": tier, "group": self.group, "ms": ms})
        return ms

    # ---------- dwell fill ----------

    def _fill(self, dt: float, now: float) -> None:
        dt_ms = dt * 1000
        cur = self.current
        paused = now < self.pause_until
        for action in list(self.progress):
            if action == cur:
                continue
            if self.progress[action] > 0:
                self.progress[action] = max(0.0, self.progress[action] - dt_ms * self.drain)
                self._set_phase(action, "drain" if self.progress[action] > 0 else "idle", now)
        if cur is None or cur == self.locked or (paused and cur not in UNDO):
            return
        if self.off_since is not None:
            # Grace period: gaze just left, hold the fill where it is.
            self._set_phase(cur, "hold", now)
            return
        p = self.progress.get(cur, 0.0) + dt_ms
        self.progress[cur] = p
        self._set_phase(cur, "fill", now)
        if p >= self.look_dwell:
            self._filled(cur, now)

    def _set_phase(self, action: str, phase: str, now: float) -> None:
        if self.phase.get(action) == phase:
            return
        self.phase[action] = phase
        dwell = self.look_dwell if action == self.current else self._dwell_guess(action)
        p = self.progress.get(action, 0.0)
        frac = min(1.0, p / dwell) if dwell else 0.0
        msg = {"action": action, "do": phase, "from": frac}
        if phase == "fill":
            msg["ms"] = max(0.0, dwell - p)
        elif phase == "drain":
            msg["ms"] = p / self.drain
        self.bus.emit("button", msg)

    def _dwell_guess(self, action: str) -> float:
        return self.undo_ms if action in UNDO else (self.high_tier_ms if tier_of(action, self.tiers) >= 2 else self.look_dwell or 1000)

    def _filled(self, action: str, now: float) -> None:
        self.look_filled = True
        tier = tier_of(action, self.tiers)
        if action in UNDO or tier <= 1:
            self._fire(action, "dwell", 0.0, now)
            return
        options = self.allowed(tier)
        if not options:
            self.bus.emit("notice", {"text": "Tracking is poor. This button needs a signal I can't see right now."})
            self.progress[action] = 0.0
            self.phase[action] = "idle"
            self.bus.emit("button", {"action": action, "do": "idle", "from": 0})
            self.locked = action
            return
        check = self.policy.check_for(tier, self.group, options)
        self.bus.emit("choice", {"action": action, "tier": tier, "group": self.group,
                                 "check": check, "options": options, "scores": self.policy.last})
        if check == "dwell":
            self._fire(action, "dwell", 0.0, now)
            return
        self.waiting = {"action": action, "check": check, "tier": tier, "group": self.group,
                        "since": now, "until": now + self.wait_s, "attempted": False, "other_since": None}
        self.progress[action] = 0.0
        self.phase[action] = "wait"
        self.bus.emit("wait", {"action": action, "check": check, "tier": tier, "group": self.group})
        self.bus.emit("button", {"action": action, "do": "wait", "check": check, "ms": self.wait_s * 1000})

    def _fire(self, action: str, check: str, signal_time: float, now: float) -> None:
        self.seq += 1
        target = self.targets.get(action)
        tier = tier_of(action, self.tiers)
        dwell = self.look_dwell if action == self.current else self._dwell_guess(action)
        self.bus.emit("fire", {"seq": self.seq, "action": action, "tier": tier, "group": self.group,
                               "dwell": dwell, "check": check, "signal_time": signal_time,
                               "center": target.center if target else None, "t": now})
        self.progress[action] = 0.0
        self.phase[action] = "locked"
        self.bus.emit("button", {"action": action, "do": "fired", "from": 0})
        self.locked = action
        self.pause_until = now + self.pause_s
        self.dimmed = True
        self.bus.emit("dim", {"on": True, "except": list(UNDO)})

    # ---------- waiting for a second signal ----------

    def on_signal(self, p: dict) -> None:
        w = self.waiting
        if w is None:
            return
        now = self.clock.now()
        kind = p["kind"]
        if kind == w["check"]:
            self.waiting = None
            self.bus.emit("accept", {"action": w["action"], "check": kind})
            self.bus.emit("button", {"action": w["action"], "do": "accept", "check": kind})
            self._fire(w["action"], kind, now - w["since"], now)
        elif self.enabled.get(kind) and self.can_do.get(kind):
            w["attempted"] = True
            self.bus.emit("wrong", {"action": w["action"], "check": w["check"], "got": kind})
            self.bus.emit("button", {"action": w["action"], "do": "wrong", "check": w["check"]})

    def _check_wait(self, now: float) -> None:
        w = self.waiting
        if w is None:
            return
        reason = None
        if now >= w["until"]:
            reason = "timeout"
        elif self.current is not None and self.current != w["action"]:
            w["other_since"] = w["other_since"] if w["other_since"] is not None else now
            if now - w["other_since"] >= self.cancel_wait_s:
                reason = "looked_away"
        else:
            w["other_since"] = None
        if reason:
            self.waiting = None
            self.bus.emit("timeout", {"action": w["action"], "check": w["check"], "tier": w["tier"],
                                      "group": w["group"], "attempted": w["attempted"], "reason": reason})
            self.phase[w["action"]] = "idle"
            self.bus.emit("button", {"action": w["action"], "do": "timeout"})
            if w["action"] == self.current:
                self.locked = w["action"]   # no refill until gaze leaves and comes back

    def _lost(self, now: float) -> None:
        """Face lost for too long: nothing is carried out (DESIGN_PLAN 3.8)."""
        if self.current is not None:
            self._end_look(self.current, self.lost_since or now)
            self.current = None
        for action, p in self.progress.items():
            if p > 0:
                self.progress[action] = 0.0
                self._set_phase(action, "idle", now)
        if self.waiting:
            w, self.waiting = self.waiting, None
            self.bus.emit("timeout", {"action": w["action"], "check": w["check"], "tier": w["tier"],
                                      "group": w["group"], "attempted": True, "reason": "lost"})
            self.bus.emit("button", {"action": w["action"], "do": "timeout"})

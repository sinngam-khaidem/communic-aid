"""Outcomes: label what happened (DESIGN_PLAN 6.2).

Each label is fixed only when its window closes, and only once per action. The final state
decides: action, undo, redo is "worked", because the undo was the mistake.

An unfilled look on a tier 0 or 1 button is a give-up (a missed selection) only when all three hold:
  * it got at least give_up_min_fill of the way (a brief glance is not an attempt),
  * the same button was chosen within give_up_confirm_s after it (so it was wanted),
  * that choice needed a fresh fill (if the old fill carried over, the look away was only a slip).
A short or slipped look on the way to choosing that button is part of the selection and gets no label.
Any other unfilled look is "passed by", a stray glance.
"""

from __future__ import annotations

from .common import Bus, Clock, Outcome, tier_of

UNDO = ("undo", "redo")


class Outcomes:
    def __init__(self, bus: Bus, clock: Clock, config: dict, tiers: dict[str, int]) -> None:
        self.bus, self.clock, self.tiers = bus, clock, tiers
        w = config["windows"]
        self.undo_s, self.backspace_s = w["undo_s"], w["backspace_s"]
        self.min_fill = w.get("give_up_min_fill", 0.5)
        self.confirm_s = w.get("give_up_confirm_s", 5.0)
        self.come_back_signal_s = w["come_back_signal_s"]
        self.started: dict[str, float] = {}   # when the latest look at each button began
        self.fires: list[dict] = []      # waiting for the undo window to close
        self.looks: list[dict] = []      # unfilled looks, waiting to see if the person comes back
        self.timeouts: list[dict] = []   # signal requests that timed out

        bus.on("look_start", self._look_start)
        bus.on("look", self._look)
        bus.on("fire", self._fire)
        bus.on("undo", lambda p: self._mark(p["seq"], True))
        bus.on("redo", self._redo)
        bus.on("timeout", self._timeout)
        bus.on("signal", self._late_try)
        bus.on("attempt", self._late_try)
        bus.on("tick", lambda p: self.flush(self.clock.now()))

    def _emit(self, outcome: Outcome) -> None:
        self.bus.emit("outcome", {"outcome": outcome})

    # ---------- looks (dwell learner) ----------

    def _look_start(self, p: dict) -> None:
        self.started[p["action"]] = p["t"]
        for t in [t for t in self.timeouts if t["action"] == p["action"] and p["t"] <= t["deadline"]]:
            self.timeouts.remove(t)
            self._emit(Outcome("router", "gave_up", t["action"], t["tier"], t["group"], check=t["check"]))

    def _look(self, p: dict) -> None:
        if p["filled"] or p["tier"] > 1 or p["action"] in UNDO:
            return
        duration = (p["end"] - p["start"]) * 1000
        self.looks.append({"action": p["action"], "tier": p["tier"], "group": p["group"], "dwell": p["dwell"],
                           "duration": duration, "fill": p.get("fill", duration / p["dwell"]),
                           "deadline": p["end"] + self.confirm_s})

    def _chosen(self, action: str, now: float, dwell: float) -> None:
        """The button was chosen: decide what each earlier unfilled look at it was."""
        fresh = now - self.started.get(action, now) >= 0.9 * dwell / 1000
        for look in [l for l in self.looks if l["action"] == action]:
            self.looks.remove(look)
            if fresh and look["fill"] >= self.min_fill:
                self._emit(Outcome("dwell", "gave_up", look["action"], look["tier"], look["group"],
                                   dwell=look["dwell"], duration=look["duration"]))

    # ---------- fired actions ----------

    def _fire(self, p: dict) -> None:
        if p["action"] in UNDO:
            return
        now = p["t"]
        self._chosen(p["action"], now, p["dwell"])
        # The next action closes every open undo window.
        for f in list(self.fires):
            accident = f["undone"] or (
                p["action"] == "backspace" and f["action"].startswith("key:") and now - f["t"] <= self.backspace_s)
            self._finish(f, accident)
        self.fires.append({**p, "undone": False, "deadline": now + self.undo_s})

    def _mark(self, seq: int, undone: bool) -> None:
        for f in self.fires:
            if f["seq"] == seq:
                f["undone"] = undone
                if undone:   # keep the label open while Redo is on offer
                    f["deadline"] = max(f["deadline"], self.clock.now() + self.undo_s)

    def _redo(self, p: dict) -> None:
        self._mark(p["seq"], False)
        self.bus.emit("undo_misfire", {"seq": p["seq"]})

    def _finish(self, f: dict, accident: bool) -> None:
        self.fires.remove(f)
        learner = "dwell" if f["tier"] <= 1 else "router"
        self._emit(Outcome(learner, "accident" if accident else "worked", f["action"], f["tier"], f["group"],
                           dwell=f["dwell"], check=f["check"], signal_time=f["signal_time"],
                           center=tuple(f["center"]) if f["center"] else None, fired_at=f["t"]))

    # ---------- signal requests that timed out ----------

    def _timeout(self, p: dict) -> None:
        if p["reason"] == "lost":
            return      # the camera lost the face: says nothing about the person or the signal
        if p["attempted"]:
            self._emit(Outcome("router", "gave_up", p["action"], p["tier"], p["group"], check=p["check"]))
            return
        self.timeouts.append({**p, "deadline": self.clock.now() + self.come_back_signal_s})

    def _late_try(self, p: dict) -> None:
        """A signal or a partial try just after a timeout means they meant it: the signal was too slow or hard."""
        now = self.clock.now()
        for t in [t for t in self.timeouts if now <= t["deadline"]]:
            self.timeouts.remove(t)
            self._emit(Outcome("router", "gave_up", t["action"], t["tier"], t["group"], check=t["check"]))

    # ---------- closing windows ----------

    def flush(self, now: float) -> None:
        for f in [f for f in self.fires if now >= f["deadline"]]:
            self._finish(f, f["undone"])
        for look in [l for l in self.looks if now > l["deadline"]]:
            self.looks.remove(look)
            self._emit(Outcome("dwell", "passed_by", look["action"], look["tier"], look["group"],
                               dwell=look["dwell"], duration=look["duration"]))
        for t in [t for t in self.timeouts if now > t["deadline"]]:
            self.timeouts.remove(t)
            self._emit(Outcome("router", "blocked", t["action"], t["tier"], t["group"], check=t["check"]))

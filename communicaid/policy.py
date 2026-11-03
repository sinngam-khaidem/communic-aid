"""Policy: choose a dwell and a check, and learn from outcomes (DESIGN_PLAN 6.4 to 6.6).

Both learners only store counts of what happened. Costs and reward values are read from the
config at the moment of choosing, so tuning them never wipes learning.

AdaptivePolicy is the Adaptive study condition. FixedPolicy is the Fixed baseline.
"""

from __future__ import annotations

import numpy as np

from .common import SIGNALS, Outcome, cost

GROUPS = ("rested+steady", "rested+shaky", "tired+steady", "tired+shaky")
OUTCOMES = ("worked", "gave_up", "blocked", "accident")


class DwellLearner:
    """Learns two habits per group: how long stray glances last, and how long the person waits.

    Six numbers per group (DESIGN_PLAN 6.4):
      intended, unintended, passed-by count, stray glance time, give-up count, waiting time.
    """

    PRIOR = np.array([2.0, 2.0, 3.0, 900.0, 1.0, 5000.0])

    def __init__(self, config: dict, rng: np.random.Generator) -> None:
        self.config, self.rng = config, rng
        self.obs = {g: np.zeros(6) for g in GROUPS}
        self.looks = {g: 0 for g in GROUPS}
        self.selections = {g: 0 for g in GROUPS}
        self.current: dict[str, float] = {}
        self.last: dict = {}

    def numbers(self, group: str) -> np.ndarray:
        d = self.config["dwell"]
        if self.looks[group] >= d["borrow_looks"]:
            return self.PRIOR + self.obs[group]
        return self.PRIOR + sum(self.obs.values())

    def score(self, d: np.ndarray, pi: float, g: float, p: float, tier: int) -> np.ndarray:
        r = self.config["reward"]
        accident = np.exp(-d / g)
        give_up = 1 - np.exp(-d / p)
        worked = 1 - r["time_penalty"] * d / 1000
        return pi * ((1 - give_up) * worked + r["give_up"] * give_up) - (1 - pi) * accident * cost(self.config, tier)

    def dwell_for(self, tier: int, group: str) -> int:
        """The dwell in use. It only changes after a selection (see _step), never on a glance."""
        d = self.config["dwell"]
        if self.selections[group] < d["warmup_selections"]:
            return int(d["start"])
        # Limits apply on read too, so changing min or max in the config takes effect straight away.
        return int(round(np.clip(self.current.get(f"{tier}|{group}", float(d["start"])), d["min"], d["max"])))

    def _step(self, tier: int, group: str) -> None:
        """After each selection: draw plausible habits, pick the best dwell, move a little towards it."""
        d = self.config["dwell"]
        key = f"{tier}|{group}"
        if self.selections[group] < d["warmup_selections"]:
            self.last = {"tier": tier, "group": group, "dwell": d["start"], "warmup": True}
            return
        intended, unintended, passed, stray, give_ups, waiting = self.numbers(group)
        # Thompson sampling: draw plausible habits, wider when there is little data.
        pi = self.rng.beta(intended, unintended)
        g = stray / self.rng.gamma(passed)
        p = waiting / self.rng.gamma(give_ups)
        grid = np.arange(d["min"], d["max"] + 1, d["step"], dtype=float)
        best = float(grid[np.argmax(self.score(grid, pi, g, p, tier))])
        cur = self.current.get(key, float(d["start"]))
        # Shorter only in small, slow steps; longer more readily, because accidents cost more than waiting.
        step = float(np.clip(d["smoothing"] * (best - cur), -d["max_step_down"], d["max_step_up"]))
        cur = float(np.clip(cur + step, d["min"], d["max"]))
        self.current[key] = cur
        self.last = {"tier": tier, "group": group, "dwell": round(cur), "best": best,
                     "stray_ms": round(g), "patience_ms": round(p), "intended": round(pi, 2)}

    def learn(self, o: Outcome) -> None:
        n = self.obs[o.group]
        if o.kind == "worked":
            n[0] += 1; n[5] += o.dwell
        elif o.kind == "gave_up":
            n[0] += 1; n[4] += 1; n[5] += o.duration
        elif o.kind == "accident":
            n[1] += 1; n[3] += o.dwell
        elif o.kind == "passed_by":
            n[1] += 1; n[2] += 1; n[3] += o.duration
        else:
            return
        self.looks[o.group] += 1
        if o.kind in ("worked", "accident"):
            self.selections[o.group] += 1
            for tier in (0, 1):
                self._step(tier, o.group)

    def save(self) -> dict:
        return {"obs": {g: v.tolist() for g, v in self.obs.items()}, "looks": self.looks,
                "selections": self.selections, "current": self.current}

    def load(self, s: dict) -> None:
        self.obs = {g: np.array(s["obs"][g]) for g in GROUPS}
        self.looks = {g: int(s["looks"][g]) for g in GROUPS}
        self.selections = {g: int(s.get("selections", {}).get(g, 0)) for g in GROUPS}
        self.current = dict(s.get("current", {}))


class Router:
    """Contextual bandit over checks for tiers 2 and 3 (DESIGN_PLAN 6.5)."""

    def __init__(self, config: dict, rng: np.random.Generator) -> None:
        self.config, self.rng = config, rng
        self.tally: dict[str, list[float]] = {}
        self.tries: dict[str, int] = {}
        self.signal_time = {s: [float(config["reward"]["effort_start_s"]), 1] for s in SIGNALS}
        self.preferred = "blink"
        self.last: dict = {}

    def prior(self, option: str) -> np.ndarray:
        if option == "dwell":
            return np.array([1.0, 0.0, 0.0, 1.0])
        p = np.ones(4)
        if option == self.preferred:
            p[0] += self.config["router"]["preferred_bonus"]
        return p

    def counts(self, group: str, tier: int, option: str) -> np.ndarray:
        if self.tries.get(f"{group}|{tier}", 0) >= self.config["router"]["borrow_tries"]:
            obs = np.array(self.tally.get(f"{group}|{tier}|{option}", [0.0] * 4))
        else:
            obs = sum((np.array(self.tally.get(f"{g}|{tier}|{option}", [0.0] * 4)) for g in GROUPS), np.zeros(4))
        return self.prior(option) + obs

    def effort(self, option: str) -> float:
        r = self.config["reward"]
        total, n = self.signal_time[option]
        return r["effort_base"] + r["effort_per_s"] * total / n

    def values(self, tier: int, option: str) -> np.ndarray:
        r, c = self.config["reward"], cost(self.config, tier)
        worked = 1.0 if option == "dwell" else 1.0 - self.effort(option)
        return np.array([worked, r["give_up"], r["blocked"] * c, -c])

    def check_for(self, tier: int, group: str, allowed: list[str]) -> str:
        scores = {}
        for option in allowed:
            chances = self.rng.dirichlet(np.maximum(self.counts(group, tier, option), 1e-3))
            scores[option] = float(chances @ self.values(tier, option))
        best = max(scores, key=scores.get)
        self.last = {"tier": tier, "group": group, "check": best, "scores": {k: round(v, 3) for k, v in scores.items()}}
        return best

    def learn(self, o: Outcome) -> None:
        if o.kind not in OUTCOMES:
            return
        key = f"{o.group}|{o.tier}|{o.check}"
        self.tally.setdefault(key, [0.0] * 4)[OUTCOMES.index(o.kind)] += 1
        self.tries[f"{o.group}|{o.tier}"] = self.tries.get(f"{o.group}|{o.tier}", 0) + 1
        if o.kind == "worked" and o.check in self.signal_time and o.signal_time > 0:
            self.signal_time[o.check][0] += o.signal_time
            self.signal_time[o.check][1] += 1

    def save(self) -> dict:
        return {"tally": self.tally, "tries": self.tries, "signal_time": self.signal_time}

    def load(self, s: dict) -> None:
        self.tally = {k: list(v) for k, v in s["tally"].items()}
        self.tries = dict(s["tries"])
        self.signal_time.update({k: list(v) for k, v in s["signal_time"].items()})


class AdaptivePolicy:
    name = "adaptive"

    def __init__(self, config: dict, rng: np.random.Generator) -> None:
        self.config, self.rng = config, rng
        self.dwell = DwellLearner(config, rng)
        self.router = Router(config, rng)
        self.last: dict = {}

    def dwell_for(self, tier: int, group: str) -> int:
        ms = self.dwell.dwell_for(tier, group)
        self.last = self.dwell.last
        return ms

    def check_for(self, tier: int, group: str, allowed: list[str]) -> str:
        check = self.router.check_for(tier, group, allowed)
        self.last = self.router.last
        return check

    def learn(self, o: Outcome) -> None:
        (self.dwell if o.learner == "dwell" else self.router).learn(o)

    def set_preferred(self, signal: str) -> None:
        self.router.preferred = signal

    def reset(self) -> None:
        self.dwell = DwellLearner(self.config, self.rng)
        preferred = self.router.preferred
        self.router = Router(self.config, self.rng)
        self.router.preferred = preferred

    def save(self) -> dict:
        return {"dwell": self.dwell.save(), "router": self.router.save()}

    def load(self, saved: dict | None) -> None:
        if saved:
            self.dwell.load(saved["dwell"])
            self.router.load(saved["router"])


class FixedPolicy:
    """Fixed study condition (DESIGN_PLAN 12): one dwell, tier 2 dwell only, tier 3 the preferred signal."""

    name = "fixed"

    def __init__(self, config: dict) -> None:
        self.config = config
        self.preferred = "blink"
        self.last: dict = {}

    def dwell_for(self, tier: int, group: str) -> int:
        return int(self.config["dwell"]["fixed_condition"])

    def check_for(self, tier: int, group: str, allowed: list[str]) -> str:
        if tier == 2 and "dwell" in allowed:
            return "dwell"
        signals = [s for s in allowed if s != "dwell"]
        return self.preferred if self.preferred in signals else signals[0]

    def learn(self, o: Outcome) -> None:
        pass

    def set_preferred(self, signal: str) -> None:
        self.preferred = signal

    def reset(self) -> None:
        pass

    def save(self) -> dict:
        return {}

    def load(self, saved: dict | None) -> None:
        pass

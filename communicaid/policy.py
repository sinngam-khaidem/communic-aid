from __future__ import annotations

import numpy as np

from .common import SIGNALS, Outcome, cost

GROUPS = ("rested+steady", "rested+shaky", "tired+steady", "tired+shaky")
OUTCOMES = ("worked", "gave_up", "blocked", "accident")


def reward(config: dict, o: Outcome, effort: float) -> float:
    """
    The value of one outcome, as the learners score it.

    `effort` is how costly the signal was, used only when a signal confirmed the action.
    A passed-by glance is worth 0: it teaches the learner, but nothing was gained or lost.
    """
    r, c = config["reward"], cost(config, o.tier)
    if o.learner == "dwell":
        return {
            "worked": 1 - r["time_penalty"] * o.dwell / 1000, 
            "gave_up": r["give_up"],
            "accident": -c, 
            "passed_by": 0.0
        }.get(o.kind, 0.0)
    
    worked = 1.0 if o.check == "dwell" else 1.0 - effort
    return {
        "worked": worked, 
        "gave_up": r["give_up"], 
        "blocked": r["blocked"] * c, 
        "accident": -c
    }.get(o.kind, 0.0)


class DwellLearner:
    """
    It learns two habits per group: 
        - how long stray glances last
        - how long the person waits.

    Six numbers are recorded per group: 
        - intended, unintended, passed-by count, stray glance time, give-up count, waiting time.
    """

    PRIOR = np.array([2.0, 2.0, 3.0, 900.0, 1.0, 5000.0])

    def __init__(self, config: dict, rng: np.random.Generator) -> None:
        self.config, self.rng = config, rng
        self.obs = {g: np.zeros(6) for g in GROUPS}
        self.looks = {g: 0 for g in GROUPS}
        self.selections = {g: 0 for g in GROUPS}
        self.current: dict[str, float] = {}
        self.last: dict = {}
        self.changes: list[dict] = []     # what the last learn() changed, for the console

    def numbers(self, group: str) -> np.ndarray:
        d = self.config["dwell"]
        if self.looks[group] >= d["borrow_looks"]:
            return self.PRIOR + self.obs[group]
        
        return self.PRIOR + sum(self.obs.values())

    def score(self, d: np.ndarray, pi: float, g: float, p: float, tier: int) -> np.ndarray:
        """
        The expected value of each dwell in `d`, given the current beliefs about the user.

        Args:
            - d: array of dwell times to score
            - pi: probability of an intended glance (from the beta distribution)
            - g: mean stray glance duration (from the gamma distribution)
            - p: mean patience duration (from the gamma distribution)
            - tier: the tier of the action being scored (for cost lookup)
        Returns:
            - array of expected values for each dwell in `d`
        """
        r = self.config["reward"]
        accident = np.exp(-d / g) # A(d)
        give_up = 1 - np.exp(-d / p) # G(d)

        worked = 1 - r["time_penalty"] * d / 1000
        return pi * ((1 - give_up) * worked + r["give_up"] * give_up) - (1 - pi) * accident * cost(self.config, tier)

    def dwell_for(self, tier: int, group: str) -> int:
        """
        Return the dwell time to use for this tier and group, based on the current beliefs about the user.

        Args:
            - tier: the tier of the action being scored (for cost lookup)
            - group: the group of the user (for observation lookup)
        Returns:
            - the dwell time to use, in milliseconds
        """
        d = self.config["dwell"]
        if self.selections[group] < d["warmup_selections"]:
            return int(d["start"])
        
        return int(
            round(
                np.clip(
                    self.current.get(f"{tier}|{group}", float(d["start"])), 
                    d["min"], 
                    d["max"]
                )
            )
        )

    def _step(self, tier: int, group: str) -> None:
        """
        Update the dwell time for a given tier and group, based on the current beliefs about the user.

        Args:
            - tier: the tier of the action being scored (for cost lookup)
            - group: the group of the user (for observation lookup)
        """
        d = self.config["dwell"]
        key = f"{tier}|{group}"

        # If the group has less than 20 selections, dwell stays at the initial value of 1500 ms.
        if self.selections[group] < d["warmup_selections"]:
            self.last = {"tier": tier, "group": group, "dwell": d["start"], "warmup": True}
            self.changes.append(
                {
                    "tier": tier, 
                    "group": group,
                    "warmup": self.selections[group],
                    "of": d["warmup_selections"], 
                    "dwell": d["start"]
                }
            )
            return
        
        intended, unintended, passed, stray, give_ups, waiting = self.numbers(group)

        # Thompson Sampling: draw plausible habits, wider when there is little data.
        # Alternative to plain average: it encourages exploration, and is more robust to outliers.
        pi = self.rng.beta(intended, unintended)
        g = stray / self.rng.gamma(passed)
        p = waiting / self.rng.gamma(give_ups)

        grid = np.arange(d["min"], d["max"] + 1, d["step"], dtype=float)
        best = float(
                grid[
                    np.argmax(self.score(grid, pi, g, p, tier))
                ]
            )
        cur = before = self.current.get(key, float(d["start"]))

        # Shorter only in small, slow steps; longer more readily, because accidents cost more than waiting.
        step = float(np.clip(d["smoothing"] * (best - cur), -d["max_step_down"], d["max_step_up"]))
        cur = float(np.clip(cur + step, d["min"], d["max"]))
        self.current[key] = cur
        self.changes.append({"tier": tier, "group": group, "before": round(before), "after": round(cur), "best": round(best)})
        self.last = {"tier": tier, "group": group, "dwell": round(cur), "best": best,
                     "stray_ms": round(g), "patience_ms": round(p), "intended": round(pi, 2)}

    def learn(self, o: Outcome) -> None:
        self.changes = []
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
    """Contextual bandit over checks for tiers 2 and 3."""

    def __init__(self, config: dict, rng: np.random.Generator) -> None:
        self.config, self.rng = config, rng
        self.tally: dict[str, list[float]] = {}
        self.tries: dict[str, int] = {}
        self.signal_time = {s: [float(config["reward"]["effort_start_s"]), 1] for s in SIGNALS}
        self.preferred = "blink"
        self.last: dict = {}
        self.changes: list[dict] = []

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
        self.changes = [{"check": o.check, "tier": o.tier, "group": o.group,
                         "tally": dict(zip(OUTCOMES, (int(x) for x in self.tally[key])))}]
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
        self._learner = self.dwell if o.learner == "dwell" else self.router
        self._learner.learn(o)

    @property
    def changes(self) -> list[dict]:
        learner = getattr(self, "_learner", None)
        return learner.changes if learner else []

    def reward(self, o: Outcome) -> float:
        effort = self.router.effort(o.check) if o.check in self.router.signal_time else 0.0
        return reward(self.config, o, effort)

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
    """Fixed study condition: one dwell, tier 2 dwell only, tier 3 the preferred signal."""

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

    changes: list[dict] = []

    def reward(self, o: Outcome) -> float:
        r = self.config["reward"]
        return reward(self.config, o, r["effort_base"] + r["effort_per_s"] * r["effort_start_s"])

    def set_preferred(self, signal: str) -> None:
        self.preferred = signal

    def reset(self) -> None:
        pass

    def save(self) -> dict:
        return {}

    def load(self, saved: dict | None) -> None:
        pass

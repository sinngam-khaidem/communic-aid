"""Simulated people for checking the learners before real people use them (DESIGN_PLAN 6.8).

    python tests/simulate.py

Each person has hidden habits. The learners never see them, only the outcomes.
"""

from __future__ import annotations

import numpy as np

from communicaid.common import Outcome, load_config
from communicaid.policy import AdaptivePolicy

# Dwell habits: typical stray glance (ms), median patience (ms), share of looks that are intended.
DWELL_PEOPLE = {
    "rested, steady gaze": {"stray": 250, "patience": 2500, "intended": 0.5},
    "tired": {"stray": 450, "patience": 1800, "intended": 0.5},
}

# Signal habits: chance the signal works when meant, chance it fires by mistake,
# chance a dwell completes without being meant (Rekha's evening from the reports).
ROUTER_PEOPLE = {
    "Rekha, evening": {"unintended": 0.15,
                       "signals": {"blink": (0.45, 0.05), "brows": (0.9, 0.04), "switch": (0.95, 0.02)}},
    "Arjun, shaky gaze": {"unintended": 0.35,
                          "signals": {"blink": (0.7, 0.1), "brows": (0.35, 0.3), "switch": (0.95, 0.02)}},
}


def simulate_dwell(person: dict, tier: int, looks: int = 400, seed: int = 0, group: str = "rested+steady"):
    rng = np.random.default_rng(seed)
    policy = AdaptivePolicy(load_config(), rng)
    used, accidents, give_ups = [], 0, 0
    for _ in range(looks):
        d = policy.dwell_for(tier, group)
        used.append(d)
        if rng.random() < person["intended"]:
            patience = rng.lognormal(np.log(person["patience"]), 0.35)
            if patience < d:
                give_ups += 1
                o = Outcome("dwell", "gave_up", "key:a", tier, group, dwell=d, duration=patience)
            else:
                o = Outcome("dwell", "worked", "key:a", tier, group, dwell=d)
        else:
            glance = rng.exponential(person["stray"])
            if glance >= d:
                accidents += 1
                o = Outcome("dwell", "accident", "key:a", tier, group, dwell=d)
            else:
                o = Outcome("dwell", "passed_by", "key:a", tier, group, dwell=d, duration=glance)
        policy.learn(o)
    return float(np.mean(used[-100:])), accidents, give_ups


def simulate_router(person: dict, tier: int, tries: int = 300, seed: int = 0, group: str = "tired+steady",
                    config: dict | None = None):
    rng = np.random.default_rng(seed)
    policy = AdaptivePolicy(config or load_config(), rng)
    allowed = (["dwell"] if tier == 2 else []) + list(person["signals"])
    chosen = []
    for _ in range(tries):
        check = policy.check_for(tier, group, allowed)
        chosen.append(check)
        unintended = rng.random() < person["unintended"]
        if check == "dwell":
            kind = "accident" if unintended else "worked"
        else:
            works, false_fire = person["signals"][check]
            if unintended:
                kind = "accident" if rng.random() < false_fire else "blocked"
            else:
                kind = "worked" if rng.random() < works else "gave_up"
        policy.learn(Outcome("router", kind, "delete", tier, group, check=check, signal_time=1.0))
    last = chosen[-100:]
    return {c: last.count(c) for c in allowed}


if __name__ == "__main__":
    print("Dwell learner, average dwell over the last 100 looks:")
    for name, person in DWELL_PEOPLE.items():
        row = [f"tier {t}: {simulate_dwell(person, t)[0]:.0f} ms" for t in (0, 1)]
        print(f"  {name:22s} " + "   ".join(row))
    print("\nRouter, choices over the last 100 tries:")
    for name, person in ROUTER_PEOPLE.items():
        for tier in (2, 3):
            print(f"  {name:22s} tier {tier}: {simulate_router(person, tier)}")

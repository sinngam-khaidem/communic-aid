import numpy as np
from pytest import approx

from communicaid.common import Outcome
from communicaid.console import Console
from communicaid.policy import AdaptivePolicy


def test_rewards_match_the_plan(config):
    p = AdaptivePolicy(config, np.random.default_rng(0))
    worked_dwell = Outcome("dwell", "worked", "open:priya", 0, "rested+steady", dwell=1500)
    assert p.reward(worked_dwell) == approx(1 - 0.6 * 1.5)
    assert p.reward(Outcome("dwell", "accident", "key:a", 1, "rested+steady", dwell=900)) == approx(-2)
    assert p.reward(Outcome("dwell", "passed_by", "key:a", 1, "rested+steady", duration=200)) == approx(0)
    effort = 0.35 + 0.25 * 1.2
    assert p.reward(Outcome("router", "worked", "call", 3, "rested+steady", check="brows")) == approx(1 - effort)
    assert p.reward(Outcome("router", "blocked", "call", 3, "rested+steady", check="brows")) == approx(0.15 * 8)
    assert p.reward(Outcome("router", "accident", "send", 2, "rested+steady", check="dwell")) == approx(-4)


def test_console_lines_are_readable(world, config, capsys):
    bus, clock, _ = world
    Console(bus, clock, colour=False)
    clock.advance(65)
    bus.emit("choice", {"action": "call", "tier": 3, "group": "tired+steady", "check": "brows",
                        "scores": {"scores": {"brows": -1.49, "switch": -3.68, "yes": -5.65}}})
    glance = Outcome("dwell", "passed_by", "key:a", 1, "tired+steady", duration=200)
    for _ in range(3):
        bus.emit("learned", {"outcome": glance, "reward": 0.0, "changes": []})
    worked = Outcome("router", "worked", "call", 3, "tired+steady", check="brows", signal_time=0.9)
    bus.emit("learned", {"outcome": worked, "reward": 0.425, "changes": [
        {"check": "brows", "tier": 3, "group": "tired+steady",
         "tally": {"worked": 3, "gave_up": 1, "blocked": 0, "accident": 0}}]})
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("01:05  CHOOSE")
    assert "-> raise eyebrows" in out[0] and "raise eyebrows -1.49   switch -3.68" in out[0]
    assert "3 stray glances passed by, reward 0 each" in out[1]
    assert "OUTCOME" in out[2] and "worked" in out[2] and "reward +0.42" in out[2] and "signal took 0.9 s" in out[2]
    assert "ROUTER" in out[3] and "raise eyebrows: worked 3, gave up 1" in out[3]

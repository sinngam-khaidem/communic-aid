import numpy as np

from communicaid.common import Outcome
from communicaid.policy import AdaptivePolicy, FixedPolicy

from simulate import DWELL_PEOPLE, ROUTER_PEOPLE, simulate_dwell, simulate_router


def test_warmup_uses_the_starting_dwell(config):
    policy = AdaptivePolicy(config, np.random.default_rng(0))
    assert policy.dwell_for(1, "rested+steady") == config["dwell"]["start"]


def test_glances_alone_never_change_the_dwell(config):
    policy = AdaptivePolicy(config, np.random.default_rng(0))
    for _ in range(200):
        policy.learn(Outcome("dwell", "passed_by", "key:a", 1, "rested+steady", dwell=1500, duration=150))
    assert policy.dwell_for(1, "rested+steady") == config["dwell"]["start"]


def test_dwell_moves_in_small_steps_after_warmup(config):
    policy = AdaptivePolicy(config, np.random.default_rng(0))
    seen = []
    for _ in range(config["dwell"]["warmup_selections"] + 10):
        policy.learn(Outcome("dwell", "worked", "key:a", 1, "rested+steady", dwell=policy.dwell_for(1, "rested+steady")))
        seen.append(policy.dwell_for(1, "rested+steady"))
    warm = config["dwell"]["warmup_selections"]
    assert all(d == config["dwell"]["start"] for d in seen[:warm - 1])
    assert max(abs(a - b) for a, b in zip(seen, seen[1:])) <= config["dwell"]["max_step"] + 1


def test_dwell_is_longer_when_tired(config):
    rested = simulate_dwell(DWELL_PEOPLE["rested, steady gaze"], tier=1)[0]
    tired = simulate_dwell(DWELL_PEOPLE["tired"], tier=1)[0]
    assert tired > rested + 50


def test_dwell_is_longer_when_mistakes_cost_more(config):
    person = DWELL_PEOPLE["rested, steady gaze"]
    assert simulate_dwell(person, tier=1)[0] > simulate_dwell(person, tier=0)[0]


def test_router_stops_asking_for_a_signal_that_fails():
    choices = simulate_router(ROUTER_PEOPLE["Rekha, evening"], tier=3)
    assert choices["blink"] < 20
    assert choices["brows"] + choices["switch"] > 80


def test_router_asks_for_a_signal_when_dwell_alone_causes_accidents():
    choices = simulate_router(ROUTER_PEOPLE["Arjun, shaky gaze"], tier=2)
    assert choices["dwell"] < 30


def test_changing_costs_keeps_what_was_learned(config):
    policy = AdaptivePolicy(config, np.random.default_rng(0))
    for _ in range(10):
        policy.learn(Outcome("router", "worked", "send", 2, "rested+steady", check="blink", signal_time=1.0))
    before = policy.save()
    config["costs"]["tier2"] = 6.0
    policy.check_for(2, "rested+steady", ["dwell", "blink"])
    assert policy.save() == before


def test_save_and_load_round_trip(config):
    a = AdaptivePolicy(config, np.random.default_rng(0))
    a.learn(Outcome("dwell", "passed_by", "key:a", 1, "tired+shaky", dwell=600, duration=200))
    a.learn(Outcome("router", "blocked", "delete", 3, "tired+shaky", check="brows"))
    b = AdaptivePolicy(config, np.random.default_rng(0))
    b.load(a.save())
    assert b.save() == a.save()


def test_fixed_policy(config):
    p = FixedPolicy(config)
    p.set_preferred("switch")
    assert p.dwell_for(0, "x") == config["dwell"]["fixed_condition"]
    assert p.check_for(2, "x", ["dwell", "blink", "switch"]) == "dwell"
    assert p.check_for(3, "x", ["blink", "switch"]) == "switch"
    assert p.check_for(3, "x", ["blink"]) == "blink"

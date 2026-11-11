"""Each row of the tables in DESIGN_PLAN 6.2 is one test."""

from communicaid.chat import TIERS
from communicaid.outcomes import Outcomes

from conftest import run

seq = iter(range(1, 10_000))


def fire(bus, clock, action, tier, check="dwell", dwell=600):
    n = next(seq)
    bus.emit("fire", {"seq": n, "action": action, "tier": tier, "group": "rested+steady", "dwell": dwell,
                      "check": check, "signal_time": 0.8, "center": (10, 10), "t": clock.now()})
    return n


def make(world, config):
    bus, clock, rec = world
    Outcomes(bus, clock, config, TIERS)
    return bus, clock, rec


def test_fired_and_kept_is_worked(world, config):
    bus, clock, rec = make(world, config)
    fire(bus, clock, "open:priya", 0)
    run(bus, clock, 5.1)
    assert rec.outcomes() == [("dwell", "worked")]


def test_undone_is_accident(world, config):
    bus, clock, rec = make(world, config)
    n = fire(bus, clock, "open:priya", 0)
    run(bus, clock, 1.0)
    bus.emit("undo", {"seq": n})
    run(bus, clock, 10.0)
    assert rec.outcomes() == [("dwell", "accident")]


def test_undo_then_redo_is_worked(world, config):
    bus, clock, rec = make(world, config)
    n = fire(bus, clock, "send", 2, check="blink")
    run(bus, clock, 1.0)
    bus.emit("undo", {"seq": n})
    run(bus, clock, 1.0)
    bus.emit("redo", {"seq": n})
    run(bus, clock, 10.0)
    assert rec.outcomes() == [("router", "worked")]


def test_letter_then_backspace_is_accident(world, config):
    bus, clock, rec = make(world, config)
    fire(bus, clock, "key:a", 1)
    run(bus, clock, 1.0)
    fire(bus, clock, "backspace", 1)
    run(bus, clock, 6.0)
    assert rec.outcomes() == [("dwell", "accident"), ("dwell", "worked")]


def test_next_action_closes_the_window(world, config):
    bus, clock, rec = make(world, config)
    fire(bus, clock, "key:a", 1)
    run(bus, clock, 1.0)
    fire(bus, clock, "key:b", 1)
    assert rec.outcomes() == [("dwell", "worked")]


def look(bus, action, start, end, filled=False, tier=0, fill=None):
    bus.emit("look", {"action": action, "tier": tier, "start": start, "end": end, "filled": filled, "dwell": 900,
                      "group": "rested+steady", "fill": (end - start) / 0.9 if fill is None else fill})


def choose(bus, clock, action, after, look_for=0.9):
    """Come back after `after` seconds, look for `look_for` seconds, and the button fires."""
    run(bus, clock, after)
    bus.emit("look_start", {"action": action, "t": clock.now()})
    run(bus, clock, look_for)
    fire(bus, clock, action, 0, dwell=900)


def test_long_look_then_chosen_with_a_fresh_fill_is_gave_up(world, config):
    bus, clock, rec = make(world, config)
    look(bus, "open:priya", 0.0, 0.7)                  # 78% of the fill, then looked away
    choose(bus, clock, "open:priya", after=2.0)
    assert rec.outcomes() == [("dwell", "gave_up")]
    assert rec.of("outcome")[0]["outcome"].duration == 700


def test_short_glance_before_choosing_is_not_a_give_up(world, config):
    bus, clock, rec = make(world, config)
    look(bus, "open:priya", 0.0, 0.2)                  # 22% of the fill
    choose(bus, clock, "open:priya", after=1.0)
    run(bus, clock, 6.0)
    assert rec.outcomes() == [("dwell", "worked")]


def test_slip_with_the_fill_carried_over_is_not_a_give_up(world, config):
    bus, clock, rec = make(world, config)
    look(bus, "open:priya", 0.0, 0.7)
    choose(bus, clock, "open:priya", after=0.2, look_for=0.25)   # the old fill finished it
    run(bus, clock, 6.0)
    assert rec.outcomes() == [("dwell", "worked")]


def test_never_chosen_is_passed_by(world, config):
    bus, clock, rec = make(world, config)
    look(bus, "open:priya", 0.0, 0.3)
    run(bus, clock, 6.0)
    assert rec.outcomes() == [("dwell", "passed_by")]


def test_chosen_too_late_is_passed_by(world, config):
    bus, clock, rec = make(world, config)
    look(bus, "open:priya", 0.0, 0.7)
    choose(bus, clock, "open:priya", after=6.0)
    assert rec.outcomes()[0] == ("dwell", "passed_by")


def test_timeout_with_an_attempt_is_gave_up(world, config):
    bus, clock, rec = make(world, config)
    bus.emit("timeout", {"action": "delete", "check": "blink", "tier": 3, "group": "rested+steady",
                         "attempted": True, "reason": "timeout"})
    assert rec.outcomes() == [("router", "gave_up")]


def test_timeout_then_came_back_is_gave_up(world, config):
    bus, clock, rec = make(world, config)
    bus.emit("timeout", {"action": "delete", "check": "blink", "tier": 3, "group": "rested+steady",
                         "attempted": False, "reason": "timeout"})
    run(bus, clock, 2.0)
    bus.emit("look_start", {"action": "delete", "t": clock.now()})
    assert rec.outcomes() == [("router", "gave_up")]


def test_late_signal_after_timeout_is_gave_up(world, config):
    bus, clock, rec = make(world, config)
    bus.emit("timeout", {"action": "call", "check": "brows", "tier": 3, "group": "rested+steady",
                         "attempted": False, "reason": "timeout"})
    run(bus, clock, 1.0)
    bus.emit("signal", {"kind": "brows", "t": clock.now()})
    run(bus, clock, 4.0)
    assert rec.outcomes() == [("router", "gave_up")]


def test_timeout_and_gone_is_blocked_accident(world, config):
    bus, clock, rec = make(world, config)
    bus.emit("timeout", {"action": "delete", "check": "blink", "tier": 3, "group": "rested+steady",
                         "attempted": False, "reason": "timeout"})
    run(bus, clock, 4.0)
    assert rec.outcomes() == [("router", "blocked")]


def test_lost_tracking_teaches_nothing(world, config):
    bus, clock, rec = make(world, config)
    bus.emit("timeout", {"action": "delete", "check": "blink", "tier": 3, "group": "rested+steady",
                         "attempted": True, "reason": "lost"})
    run(bus, clock, 4.0)
    assert rec.outcomes() == []

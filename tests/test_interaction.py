from communicaid.chat import TIERS
from communicaid.common import Target
from communicaid.interaction import Interaction

from conftest import run


class FakePolicy:
    last: dict = {}

    def __init__(self, dwell=500, check="blink"):
        self.dwell, self.check = dwell, check

    def dwell_for(self, tier, group):
        return self.dwell

    def check_for(self, tier, group, allowed):
        return self.check if self.check in allowed else allowed[0]


def setup(world, config, **policy):
    bus, clock, rec = world
    Interaction(bus, clock, config, FakePolicy(**policy), TIERS)
    bus.emit("targets", {"targets": [Target("open:priya", 100, 100, 200, 120),
                                     Target("delete", 600, 100, 200, 120),
                                     Target("send", 100, 400, 200, 120)]})
    return bus, clock, rec


def look(bus, x, y):
    bus.emit("gaze", {"valid": True, "frozen": False, "x": x, "y": y})


def test_tier0_fires_after_dwell(world, config):
    bus, clock, rec = setup(world, config, dwell=500)
    look(bus, 200, 160)
    run(bus, clock, 0.45)
    assert rec.of("fire") == []
    run(bus, clock, 0.3)
    fires = rec.of("fire")
    assert [f["action"] for f in fires] == ["open:priya"]
    assert fires[0]["check"] == "dwell"


def test_fired_button_stays_locked_while_looked_at(world, config):
    bus, clock, rec = setup(world, config, dwell=500)
    look(bus, 200, 160)
    run(bus, clock, 3.0)
    assert len(rec.of("fire")) == 1


def test_leaving_early_drains_and_does_not_fire(world, config):
    bus, clock, rec = setup(world, config, dwell=500)
    look(bus, 200, 160)
    run(bus, clock, 0.3)
    look(bus, 1000, 800)
    run(bus, clock, 1.0)
    assert rec.of("fire") == []
    assert [p["filled"] for p in rec.of("look")] == [False]


def test_tier3_waits_for_the_signal(world, config):
    bus, clock, rec = setup(world, config, check="blink")
    look(bus, 700, 160)
    run(bus, clock, 1.2)
    assert [w["check"] for w in rec.of("wait")] == ["blink"]
    assert rec.of("fire") == []
    bus.emit("signal", {"kind": "blink"})
    fires = rec.of("fire")
    assert [(f["action"], f["check"]) for f in fires] == [("delete", "blink")]


def test_wrong_signal_shakes_and_keeps_waiting(world, config):
    bus, clock, rec = setup(world, config, check="blink")
    look(bus, 700, 160)
    run(bus, clock, 1.2)
    bus.emit("signal", {"kind": "switch"})
    assert len(rec.of("wrong")) == 1
    assert rec.of("fire") == []
    run(bus, clock, 4.0)
    timeouts = rec.of("timeout")
    assert len(timeouts) == 1 and timeouts[0]["attempted"] is True


def test_waiting_survives_eyes_closing(world, config):
    """A blink and hold freezes gaze; the waiting button must still accept the blink."""
    bus, clock, rec = setup(world, config, check="blink")
    look(bus, 700, 160)
    run(bus, clock, 1.2)
    bus.emit("gaze", {"valid": True, "frozen": True, "x": 700, "y": 160})
    run(bus, clock, 0.6)
    bus.emit("signal", {"kind": "blink"})
    assert [f["action"] for f in rec.of("fire")] == ["delete"]


def test_tier2_can_fire_on_dwell_alone(world, config):
    bus, clock, rec = setup(world, config, check="dwell")
    look(bus, 200, 460)
    run(bus, clock, 1.2)
    assert [(f["action"], f["check"]) for f in rec.of("fire")] == [("send", "dwell")]


def test_tier3_never_offers_dwell_only(world, config):
    bus, clock, rec = setup(world, config, check="dwell")
    look(bus, 700, 160)
    run(bus, clock, 1.2)
    assert rec.of("fire") == []
    assert rec.of("wait")[0]["check"] != "dwell"


def test_poor_tracking_removes_face_signals(world, config):
    bus, clock, rec = world
    i = Interaction(bus, clock, config, FakePolicy(), TIERS)
    bus.emit("context", {"group": "rested+steady", "poor_tracking": True})
    assert i.allowed(3) == ["yes", "switch"]
    assert i.allowed(2) == ["dwell", "yes", "switch"]


def test_lost_face_cancels_the_fill(world, config):
    bus, clock, rec = setup(world, config, dwell=800)
    look(bus, 200, 160)
    run(bus, clock, 0.5)
    bus.emit("gaze", {"valid": False})
    run(bus, clock, 0.5)
    look(bus, 200, 160)
    run(bus, clock, 0.5)
    assert rec.of("fire") == []

from communicaid.common import Frame
from communicaid.signals import Signals


def feed(bus, clock, seconds, **readings):
    for _ in range(int(seconds * 60)):
        clock.advance(1 / 60)
        bus.emit("frame", {"frame": Frame(t=clock.now(), **readings)})


def test_normal_blink_is_ignored_but_counts_as_attempt(world, config):
    bus, clock, rec = world
    Signals(bus, clock, config)
    feed(bus, clock, 0.5)
    feed(bus, clock, 0.25, blink_l=0.9, blink_r=0.9)     # an ordinary 250 ms blink
    feed(bus, clock, 0.5)
    assert rec.of("signal") == []
    assert [p["kind"] for p in rec.of("attempt")] == ["blink"]


def test_blink_and_hold_fires_once(world, config):
    bus, clock, rec = world
    Signals(bus, clock, config)
    feed(bus, clock, 0.3)
    feed(bus, clock, 1.2, blink_l=0.9, blink_r=0.9)      # held well past 500 ms
    feed(bus, clock, 0.3)
    assert [p["kind"] for p in rec.of("signal")] == ["blink"]


def test_raised_eyebrows(world, config):
    bus, clock, rec = world
    Signals(bus, clock, config)
    feed(bus, clock, 0.3)
    feed(bus, clock, 0.4, brow_in=0.8, brow_out_l=0.7, brow_out_r=0.7)
    feed(bus, clock, 0.3)
    assert [p["kind"] for p in rec.of("signal")] == ["brows"]


def test_closed_eyes_do_not_count_as_brows(world, config):
    bus, clock, rec = world
    Signals(bus, clock, config)
    feed(bus, clock, 0.8, blink_l=0.9, blink_r=0.9, brow_in=0.8, brow_out_l=0.8, brow_out_r=0.8)
    assert [p["kind"] for p in rec.of("signal")] == ["blink"]


def test_yes_is_debounced(world, config):
    bus, clock, rec = world
    Signals(bus, clock, config)
    bus.emit("yes", {})
    clock.advance(0.5)
    bus.emit("yes", {})
    clock.advance(2.0)
    bus.emit("yes", {})
    assert [p["kind"] for p in rec.of("signal")] == ["yes", "yes"]


def test_three_quick_presses_escape(world, config):
    bus, clock, rec = world
    Signals(bus, clock, config)
    for _ in range(3):
        bus.emit("press", {})
        clock.advance(0.4)
    assert len(rec.of("escape")) == 1
    assert [p["kind"] for p in rec.of("signal")] == ["switch"] * 3

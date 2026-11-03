"""Things that keep the experience calm: no flickering banners, no getting stuck in calibration."""

from communicaid.chat import Chat
from communicaid.common import Frame
from communicaid.context import Context

from conftest import run


def frames(bus, clock, seconds, **kw):
    for _ in range(int(seconds * 60)):
        clock.advance(1 / 60)
        bus.emit("frame", {"frame": Frame(t=clock.now(), **kw)})
        bus.emit("tick", {})


def test_banner_does_not_flicker(world, config):
    bus, clock, rec = world
    Context(bus, clock, config)
    for _ in range(4):                       # too close for half a second, then fine, over and over
        frames(bus, clock, 0.5, dist=0.2)
        frames(bus, clock, 0.5, dist=0.45)
    assert [b for b in rec.of("banner") if b["text"]] == []


def test_banner_shows_once_the_problem_holds(world, config):
    bus, clock, rec = world
    Context(bus, clock, config)
    frames(bus, clock, 1.6, dist=0.2)
    assert [b["text"] for b in rec.of("banner")] == ["Move a little further from the screen."]


def test_failed_calibration_tries_again_instead_of_moving_on(world, config):
    bus, clock, rec = world
    chat = Chat(bus, clock, config)
    bus.emit("screen", {"w": 1440, "h": 900})            # starts the first calibration
    bus.emit("calib_done", {"error_px": None, "spread_px": None, "ok": False})
    assert chat.s["landing"] == "calibrate"
    run(bus, clock, 3.2)
    assert len(rec.of("start_calibration")) == 2


def test_loose_calibration_is_accepted_after_three_tries(world, config):
    bus, clock, rec = world
    chat = Chat(bus, clock, config)
    bus.emit("screen", {"w": 1440, "h": 900})
    for _ in range(3):
        bus.emit("calib_done", {"error_px": 140.0, "spread_px": 8.0, "ok": False})
        run(bus, clock, 3.2)
    assert chat.s["landing"] == "about"

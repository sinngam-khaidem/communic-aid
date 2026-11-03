"""Gaze stays accurate when the head moves and when the window changes."""

import numpy as np

from communicaid.common import Frame
from communicaid.gaze import Gaze

# A simple world: the phone's plane is z = 0 in camera space, the face sits at negative z,
# and the screen shows 3 px per mm of that plane around its centre.
CENTRE, PX_PER_MM = np.array([720.0, 450.0]), 3.0


def plane_point(px):
    """Screen pixel to a point on the phone's plane, in metres."""
    x_mm = (px[0] - CENTRE[0]) / PX_PER_MM
    y_mm = -(px[1] - CENTRE[1]) / PX_PER_MM
    return np.array([x_mm / 1000, y_mm / 1000, 0.0])


def frame(t, eye, px, with_eye=True):
    d = plane_point(px) - np.asarray(eye)
    d = d / np.linalg.norm(d)
    return Frame(t=t, dir=tuple(d), eye=tuple(eye) if with_eye else None, tracked=True, dist=0.5)


def calibrate(bus, clock, gaze, eye, with_eye=True):
    gaze.start_calibration()
    while gaze.calib is not None:
        dot = gaze.calib["targets"][-1] if gaze.calib["targets"] else CENTRE
        clock.advance(1 / 60)
        gaze.on_frame(frame(clock.now(), eye, dot, with_eye))


def look(bus, clock, gaze, rec, eye, px, with_eye=True):
    for _ in range(60):
        clock.advance(1 / 60)
        gaze.on_frame(frame(clock.now(), eye, px, with_eye))
    g = rec.of("gaze")[-1]
    return np.array([g["x"], g["y"]])


def setup(world, config):
    bus, clock, rec = world
    gaze = Gaze(bus, clock, config)
    bus.emit("screen", {"w": 1440, "h": 900, "ox": 0, "oy": 0})
    return bus, clock, rec, gaze


def test_calibration_fits_well(world, config):
    bus, clock, rec, gaze = setup(world, config)
    calibrate(bus, clock, gaze, eye=(0.0, 0.02, -0.5))
    done = rec.of("calib_done")[-1]
    assert done["ok"] and done["basis"] == "plane" and done["error_px"] < 10


def test_head_movement_does_not_move_the_gaze(world, config):
    bus, clock, rec, gaze = setup(world, config)
    calibrate(bus, clock, gaze, eye=(0.0, 0.02, -0.5))
    moved = (0.06, 0.05, -0.45)              # 6 cm right, 3 cm up, 5 cm closer
    target = np.array([300.0, 600.0])
    error = np.linalg.norm(look(bus, clock, gaze, rec, moved, target) - target)
    assert error < 30


def test_angles_alone_would_miss_after_head_movement(world, config):
    """Why head compensation matters: the old method drifts by the head's movement."""
    bus, clock, rec, gaze = setup(world, config)
    calibrate(bus, clock, gaze, eye=(0.0, 0.02, -0.5), with_eye=False)
    moved = (0.06, 0.05, -0.45)
    target = np.array([300.0, 600.0])
    error = np.linalg.norm(look(bus, clock, gaze, rec, moved, target, with_eye=False) - target)
    assert error > 100


def test_leaving_full_screen_does_not_shift_the_gaze(world, config):
    bus, clock, rec, gaze = setup(world, config)
    eye = (0.0, 0.02, -0.5)
    calibrate(bus, clock, gaze, eye)
    bus.emit("screen", {"w": 1440, "h": 783, "ox": 0, "oy": 117})     # the toolbar appears
    on_screen = np.array([700.0, 500.0])
    page = look(bus, clock, gaze, rec, eye, on_screen)
    assert np.allclose(page, on_screen - [0, 117], atol=10)


def test_blinks_during_calibration_are_ignored(world, config):
    bus, clock, rec, gaze = setup(world, config)
    eye = (0.0, 0.02, -0.5)
    gaze.start_calibration()
    n = 0
    while gaze.calib is not None:
        dot = gaze.calib["targets"][-1]
        clock.advance(1 / 60)
        n += 1
        f = frame(clock.now(), eye, dot)
        if n % 20 < 5:                       # eyes shut a quarter of the time, gaze swinging down
            f = Frame(t=f.t, dir=tuple(np.array(f.dir) + [0, -0.2, 0]), eye=f.eye, tracked=True,
                      blink_l=0.9, blink_r=0.9, dist=0.5)
        gaze.on_frame(f)
    assert rec.of("calib_done")[-1]["error_px"] < 10

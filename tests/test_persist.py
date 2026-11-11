"""The logger samples gaze for heatmaps and logs the button layout only when it changes."""

import json

from communicaid.common import Frame, Target
from communicaid.persist import GAZE_HZ, Persist


def logger(world, config, tmp_path):
    bus, clock, rec = world
    meta = {"session": "s1", "condition": "adaptive", "pointing": "head", "config": config}
    return bus, clock, Persist(bus, clock, tmp_path, "P01", meta)


def lines(path):
    return [json.loads(l) for l in path.read_text().splitlines()]


def test_gaze_is_sampled_with_screen_and_eye(world, config, tmp_path):
    bus, clock, persist = logger(world, config, tmp_path)
    bus.emit("state", {"state": {"screen": "thread"}})
    for i in range(120):                                   # 2 seconds at 60 frames a second
        clock.advance(1 / 60)
        bus.emit("frame", {"frame": Frame(t=clock.now(), dir=(0, 0, 1), eye=(0.01, 0.02, -0.5))})
        bus.emit("gaze", {"t": clock.now(), "valid": True, "frozen": False, "x": 100 + i, "y": 200})
    persist.close()
    gaze = lines(tmp_path / "data" / "P01" / "gaze.jsonl")
    assert abs(len(gaze) - 2 * GAZE_HZ) <= 2
    first = gaze[0]
    assert first["screen"] == "thread" and first["pointing"] == "head" and first["valid"]
    assert first["eye_mm"] == [10.0, 20.0, -500.0]


def test_layout_is_logged_only_when_it_changes(world, config, tmp_path):
    bus, clock, persist = logger(world, config, tmp_path)
    bus.emit("state", {"state": {"screen": "chats"}})
    send = [Target("open_priya", 10, 20, 300, 80)]
    bus.emit("targets", {"targets": send})
    bus.emit("targets", {"targets": send})                 # same buttons again: no new line
    bus.emit("state", {"state": {"screen": "thread"}})
    bus.emit("targets", {"targets": [Target("send", 900, 700, 120, 60)]})
    persist.close()
    layouts = [l for l in lines(tmp_path / "data" / "P01" / "events.jsonl") if l["event"] == "layout"]
    assert [l["screen"] for l in layouts] == ["chats", "thread"]
    assert layouts[1]["buttons"] == [{"action": "send", "x": 900, "y": 700, "w": 120, "h": 60}]

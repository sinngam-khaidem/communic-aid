"""The one module every other module may import: the bus, the clock and shared data classes.

Modules never import each other. They publish and subscribe to named events here.
"""

from __future__ import annotations

import time
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent

Handler = Callable[[dict], None]


class Bus:
    """Synchronous publish and subscribe. Handlers run in the order they subscribed."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._all: list[Callable[[str, dict], None]] = []

    def on(self, event: str, handler: Handler) -> None:
        self._handlers[event].append(handler)

    def on_all(self, handler: Callable[[str, dict], None]) -> None:
        self._all.append(handler)

    def emit(self, event: str, payload: dict | None = None) -> None:
        payload = payload if payload is not None else {}
        for handler in self._all:
            handler(event, payload)
        for handler in list(self._handlers.get(event, ())):
            handler(payload)


class Clock:
    """Seconds since start. Tests use FakeClock so a session can be replayed exactly."""

    def __init__(self) -> None:
        self._t0 = time.monotonic()

    def now(self) -> float:
        return time.monotonic() - self._t0

    def hour(self) -> int:
        return time.localtime().tm_hour


class FakeClock(Clock):
    def __init__(self, t: float = 0.0, hour: int = 10) -> None:
        self.t = t
        self._hour = hour

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds

    def hour(self) -> int:
        return self._hour


@dataclass
class Frame:
    """One reading from a source. ARKit fills `dir`; the mouse test source fills `point`."""

    t: float
    dir: tuple[float, float, float] | None = None
    eye: tuple[float, float, float] | None = None     # eye midpoint in camera space, metres (newer phone builds)
    point: tuple[float, float] | None = None
    blink_l: float = 0.0
    blink_r: float = 0.0
    brow_in: float = 0.0
    brow_out_l: float = 0.0
    brow_out_r: float = 0.0
    tracked: bool = True
    dist: float = 0.5


@dataclass
class Target:
    action: str
    x: float
    y: float
    w: float
    h: float

    def contains(self, px: float, py: float, margin: float = 0.0) -> bool:
        return (self.x - margin <= px <= self.x + self.w + margin
                and self.y - margin <= py <= self.y + self.h + margin)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)


@dataclass
class Outcome:
    """A final label for one look (dwell learner) or one signal request (router)."""

    learner: str            # "dwell" or "router"
    kind: str               # dwell: worked, accident, gave_up, passed_by. router: worked, gave_up, blocked, accident
    action: str
    tier: int
    group: str
    dwell: float = 0.0      # ms in use
    check: str = "dwell"
    duration: float = 0.0   # ms, for gave_up and passed_by looks
    signal_time: float = 0.0
    center: tuple[float, float] | None = None
    fired_at: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


SIGNALS = ("blink", "brows", "yes", "switch")


def tier_of(action: str, tiers: dict[str, int]) -> int:
    """Look up an action's tier by its name before any ':' (for example 'key:a' -> 'key')."""
    return tiers.get(action.split(":", 1)[0], 0)


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or ROOT / "config.toml"
    with open(path, "rb") as f:
        return tomllib.load(f)


def cost(config: dict, tier: int) -> float:
    return float(config["costs"][f"tier{tier}"])


@dataclass
class Settings:
    """What the person chose in Settings. Owned by Chat, read by others through the 'settings' event."""

    enabled: dict[str, bool] = field(default_factory=lambda: {s: True for s in SIGNALS})
    preferred: str = "blink"
    sounds: bool = True
    keyboard: str = "grouped"
    onboarded: bool = False

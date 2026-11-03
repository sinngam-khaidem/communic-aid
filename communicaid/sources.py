"""Sources: turn incoming data into bus events (frame, yes, press, escape).

ArkitSource reads the phone's UDP packets. BrowserSource reads keys from the view, and in
test mode turns the mouse and held keys into the same frames the phone sends.
"""

from __future__ import annotations

import asyncio
import json

import numpy as np

from .common import Bus, Clock, Frame


def frame_from_packet(msg: dict) -> Frame:
    """Contract v1 (DESIGN_PLAN 3.1). Older phone builds without the new fields still work."""
    d = msg.get("dir")
    return Frame(
        t=float(msg.get("t", 0.0)),
        dir=tuple(d) if d else None,
        blink_l=float(msg.get("blinkL", 0.0)),
        blink_r=float(msg.get("blinkR", 0.0)),
        brow_in=float(msg.get("browIn", 0.0)),
        brow_out_l=float(msg.get("browOutL", 0.0)),
        brow_out_r=float(msg.get("browOutR", 0.0)),
        tracked=bool(msg.get("tracked", d is not None)),
        dist=float(msg.get("dist", 0.5)),
    )


class ArkitSource(asyncio.DatagramProtocol):
    def __init__(self, bus: Bus, clock: Clock, port: int) -> None:
        self.bus, self.clock, self.port = bus, clock, port
        self.transport = None
        self.packets = 0

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(lambda: self, local_addr=("0.0.0.0", self.port))

    def stop(self) -> None:
        if self.transport:
            self.transport.close()

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            msg = json.loads(data)
        except ValueError:
            return
        self.packets += 1
        kind = msg.get("type", "frame")
        if kind == "frame":
            self.bus.emit("frame", {"frame": frame_from_packet(msg)})
        elif kind == "yes":
            self.bus.emit("yes", {"t": self.clock.now()})


class BrowserSource:
    """Keys always come from the view. With mouse=True the mouse also stands in for gaze."""

    def __init__(self, bus: Bus, clock: Clock, config: dict, mouse: bool, rng: np.random.Generator) -> None:
        self.bus, self.clock, self.mouse, self.rng = bus, clock, mouse, rng
        self.switch_keys = set(config["signals"]["switch_keys"])
        self.noise = float(config["gaze"]["mouse_noise_px"])
        self.held: set[str] = set()
        self.point: tuple[float, float] | None = None
        bus.on("key", self._key)
        if mouse:
            bus.on("mouse", self._mouse)
            bus.on("tick", self._tick)

    def _key(self, p: dict) -> None:
        key, down = p["key"], p["down"]
        k = key.lower() if len(key) == 1 else key
        if down:
            self.held.add(k)
        else:
            self.held.discard(k)
            return
        if key == "Escape":
            self.bus.emit("escape", {})
        elif key in self.switch_keys:
            self.bus.emit("press", {"t": self.clock.now()})
        elif self.mouse and k == "y":
            self.bus.emit("yes", {"t": self.clock.now()})

    def _mouse(self, p: dict) -> None:
        self.point = (float(p["x"]), float(p["y"]))

    def _tick(self, p: dict) -> None:
        point = self.point
        if point is not None and self.noise > 0:
            dx, dy = self.rng.normal(0, self.noise, 2)
            point = (point[0] + dx, point[1] + dy)
        eyes = 1.0 if "b" in self.held else 0.02
        brows = 1.0 if "e" in self.held else 0.05
        self.bus.emit("frame", {"frame": Frame(
            t=self.clock.now(), point=point, blink_l=eyes, blink_r=eyes,
            brow_in=brows, brow_out_l=brows, brow_out_r=brows,
            tracked=point is not None, dist=0.5)})

"""ViewServer: serve the view and pass messages both ways.

Holds no rules. Bus events listed in FORWARD go to every open browser as {"type": event, ...}.
Browser messages come back onto the bus: screen size, button positions, keys, mouse.
"""

from __future__ import annotations

import asyncio
import json

from aiohttp import WSMsgType, web

from .common import ROOT, Bus, Target

FORWARD = ("state", "gaze", "button", "dim", "sound", "banner", "calib_dot", "calib_done",
           "check_prompt", "check_done", "choice", "context", "dwell_now", "config", "notice", "stale",
           "preview", "signal", "link")


class ViewServer:
    def __init__(self, bus: Bus, port: int, init: dict) -> None:
        self.bus, self.port, self.init = bus, port, init
        self.queues: set[asyncio.Queue] = set()
        self.sockets: set[web.WebSocketResponse] = set()
        self.latest: dict[str, dict] = {}
        for event in FORWARD:
            bus.on(event, lambda p, e=event: self._send(e, p))

    def _send(self, event: str, payload: dict) -> None:
        msg = {"type": event, **payload}
        if event in ("state", "context", "dwell_now", "config", "stale", "link"):
            self.latest[event] = msg
        if not self.queues:
            return
        text = json.dumps(msg, default=str)
        for q in self.queues:
            q.put_nowait(text)

    async def start(self) -> None:
        @web.middleware
        async def no_cache(request, handler):
            # Local app: always serve the latest view files.
            response = await handler(request)
            response.headers["Cache-Control"] = "no-store"
            return response

        app = web.Application(middlewares=[no_cache])
        app.router.add_get("/", self._index)
        app.router.add_get("/ws", self._ws)
        app.router.add_static("/view/", ROOT / "view")
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, "localhost", self.port).start()

    async def stop(self) -> None:
        # Close open pages first, so Ctrl+C does not wait for browsers to hang up.
        for ws in list(self.sockets):
            await ws.close()
        await self.runner.cleanup()

    async def _index(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(ROOT / "view" / "index.html")

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=10)
        await ws.prepare(request)
        q: asyncio.Queue = asyncio.Queue()
        await ws.send_str(json.dumps({"type": "init", **self.init}))
        for msg in self.latest.values():
            await ws.send_str(json.dumps(msg, default=str))
        self.queues.add(q)
        self.sockets.add(ws)
        writer = asyncio.create_task(self._writer(ws, q))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    self._receive(json.loads(msg.data))
        finally:
            self.queues.discard(q)
            self.sockets.discard(ws)
            writer.cancel()
        return ws

    async def _writer(self, ws: web.WebSocketResponse, q: asyncio.Queue) -> None:
        while True:
            text = await q.get()
            await ws.send_str(text)

    def _receive(self, m: dict) -> None:
        kind = m.get("type")
        if kind == "hello":
            self.bus.emit("screen", {"w": m["w"], "h": m["h"], "ox": m.get("ox", 0), "oy": m.get("oy", 0)})
        elif kind == "targets":
            self.bus.emit("targets", {"targets": [Target(t["action"], t["x"], t["y"], t["w"], t["h"])
                                                  for t in m["targets"]]})
        elif kind == "key":
            self.bus.emit("key", {"key": m["key"], "down": m["down"]})
        elif kind == "mouse":
            self.bus.emit("mouse", {"x": m["x"], "y": m["y"]})
        elif kind == "set_costs":
            self.bus.emit("set_costs", {"costs": m["costs"]})
        elif kind == "reset_learning":
            self.bus.emit("reset_learning", {})

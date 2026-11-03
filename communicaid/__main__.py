"""Start Communic-aid and connect the modules. The only file that knows every module.

    python -m communicaid --person P01                 # iPhone gaze over UDP
    python -m communicaid --person P01 --source mouse  # no phone: mouse is gaze, B E Y S are signals
    python -m communicaid --person P01 --condition fixed
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import time

import numpy as np

from .chat import TIERS, Chat
from .common import ROOT, SIGNALS, Bus, Clock, load_config
from .context import Context
from .gaze import Gaze
from .interaction import Interaction
from .outcomes import Outcomes
from .persist import Persist
from .policy import AdaptivePolicy, FixedPolicy
from .signals import Signals
from .sources import ArkitSource, BrowserSource
from .view_server import ViewServer


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def build(args, bus: Bus, clock: Clock) -> dict:
    config = load_config(args.config)
    rng = np.random.default_rng(args.seed)
    session = time.strftime("%Y%m%d-%H%M%S")
    persist = Persist(bus, clock, ROOT, args.person,
                      {"session": session, "condition": args.condition, "config": config}, raw=args.raw)

    policy = AdaptivePolicy(config, rng) if args.condition == "adaptive" else FixedPolicy(config)
    policy.load(persist.load("learner"))

    browser = BrowserSource(bus, clock, config, mouse=args.source == "mouse", rng=rng)
    gaze = Gaze(bus, clock, config)
    signals = Signals(bus, clock, config)
    context = Context(bus, clock, config)
    interaction = Interaction(bus, clock, config, policy, TIERS)
    outcomes = Outcomes(bus, clock, config, TIERS)

    # Policy learns first, then its state is saved.
    bus.on("outcome", lambda p: policy.learn(p["outcome"]))
    if args.condition == "adaptive":
        bus.on("outcome", lambda p: persist.save("learner", policy.save()))
    chat = Chat(bus, clock, config)

    bus.on("settings", lambda p: (policy.set_preferred(p["preferred"]), persist.save("settings", p)))
    bus.on("calib_done", lambda p: persist.save("calibration", gaze.save()))
    bus.on("levels", lambda p: persist.save("signals", p))

    def set_costs(p: dict) -> None:
        for k, v in p["costs"].items():
            if k in config["costs"] and k != "version":
                config["costs"][k] = float(v)
        config["costs"]["version"] = p["costs"].get("version") or f"edited-{time.strftime('%H%M%S')}"
        bus.emit("config", {"costs": config["costs"]})

    bus.on("set_costs", set_costs)
    bus.on("reset_learning", lambda p: (policy.reset(), persist.save("learner", policy.save())))

    gaze.load(persist.load("calibration"))
    signals.load(persist.load("signals"))
    chat.load_settings(persist.load("settings"), has_calibration=gaze.mapping is not None,
                       needs_calibration=args.source == "arkit")
    chat.publish_settings()

    server = ViewServer(bus, args.port or config["server"]["http_port"], init={
        "tiers": TIERS, "signals": list(SIGNALS), "person": args.person, "condition": args.condition,
        "source": args.source, "costs": config["costs"]})
    arkit = ArkitSource(bus, clock, args.udp_port or config["server"]["udp_port"]) if args.source == "arkit" else None
    return {"config": config, "server": server, "arkit": arkit, "persist": persist, "chat": chat,
            "browser": browser, "context": context, "outcomes": outcomes, "interaction": interaction}


async def run(args) -> None:
    bus, clock = Bus(), Clock()
    app = build(args, bus, clock)
    config = app["config"]
    await app["server"].start()
    if app["arkit"]:
        await app["arkit"].start()
    port = args.port or config["server"]["http_port"]
    print(f"Communic-aid running for {args.person} ({args.condition}, source: {args.source})")
    print(f"  open  http://localhost:{port}  in full screen")
    if app["arkit"]:
        print(f"  phone: send to {local_ip()} port {args.udp_port or config['server']['udp_port']}")
    app["chat"].publish()
    period = 1 / config["server"]["tick_hz"]
    try:
        while True:
            bus.emit("tick", {})
            await asyncio.sleep(period)
    finally:
        if app["arkit"]:
            app["arkit"].stop()
        await app["server"].stop()
        app["persist"].close()


def main() -> None:
    ap = argparse.ArgumentParser(prog="communicaid", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--person", default="P00", help="participant ID, used for the data folder")
    ap.add_argument("--source", choices=("arkit", "mouse"), default="arkit")
    ap.add_argument("--condition", choices=("adaptive", "fixed"), default="adaptive")
    ap.add_argument("--port", type=int, default=None, help="web port (default from config.toml)")
    ap.add_argument("--udp-port", type=int, default=None, help="phone UDP port (default from config.toml)")
    ap.add_argument("--config", default=None, help="path to a config.toml")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--raw", action="store_true", help="also log every raw frame")
    args = ap.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()

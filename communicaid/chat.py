"""Chat: the app state and the action list with tiers (DESIGN_PLAN 5, 7 and the undo rules).

Knows nothing about gaze, signals or learning. It reacts to 'fire' and 'escape', and
publishes 'state' for the view and 'settings' for everyone else.

Undo keeps a copy of the state before and after each action: Undo puts back the
"before" copy, Redo puts back the "after" copy, then the strip closes.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import asdict

from .common import ROOT, SIGNALS, Bus, Clock, Settings
from .typing_test import SECONDS, load_passage, score

# The single place where tiers live (DESIGN_PLAN 5). Keys are the action name before any ':'.
TIERS: dict[str, int] = {
    # 0 Navigation
    "open": 0, "back": 0, "scroll_up": 0, "scroll_down": 0, "compose": 0, "close_keyboard": 0,
    "more": 0, "close": 0, "forward": 0, "nav_chats": 0, "nav_settings": 0, "groups": 0,
    "continue": 0, "age": 0, "disability": 0, "app": 0, "undo": 0, "redo": 0,
    # 1 Typing and settings
    "key": 1, "group": 1, "space": 1, "backspace": 1, "predict": 1, "quick": 1, "mute": 1,
    "toggle": 1, "prefer": 1, "sounds": 1, "keyboard": 1, "recalibrate": 1, "check_signals": 1,
    # 2 Sending
    "send": 2, "react": 2, "end_call": 2,
    # 3 Irreversible
    "call": 3, "delete": 3, "forward_to": 3,
}

NOT_UNDOABLE = {"undo", "redo", "continue", "age", "disability", "app", "recalibrate", "check_signals"}

KEY_GROUPS = ["abc", "def", "ghi", "jkl", "mno", "pqrs", "tuv", "wxyz"]


def load_words() -> list[str]:
    path = ROOT / "communicaid" / "words.txt"
    return [w.strip() for w in path.read_text().splitlines() if w.strip() and not w.startswith("#")]


class Chat:
    def __init__(self, bus: Bus, clock: Clock, config: dict) -> None:
        self.bus, self.clock, self.config = bus, clock, config
        data = json.loads((ROOT / "communicaid" / "chats.json").read_text())
        self.quick = data["quick"]
        self.replies = {c["id"]: c.get("replies", []) for c in data["chats"]}
        self.words = load_words()
        self.typed: dict[str, int] = {}
        self.settings = Settings()
        self.can_do = {s: True for s in SIGNALS}
        self.s = {
            "screen": "landing", "landing": "calibrate", "return_to": None,
            "about": {"age": None, "disability": [], "app": []},
            "chats": [{"id": c["id"], "name": c["name"], "messages": c["messages"]} for c in data["chats"]],
            "chat_id": None, "draft": "", "kb_group": None, "selected": None, "picker": False,
            "call": None, "scroll": 0, "calib": None, "check": None,
            "typing": None,      # the typing test, when the app was started with --typing
        }
        self.undo: dict | None = None
        self.last: tuple | None = None       # (seq, before, after)
        self.pending_replies: list[dict] = []
        self.next_id = 1000
        self.started = False
        self.calib_tries = 0
        self.calib_again_at: float | None = None

        bus.on("fire", self.on_fire)
        bus.on("escape", lambda p: self.escape())
        bus.on("tick", lambda p: self.tick(self.clock.now()))
        bus.on("screen", self._screen)
        bus.on("calib_done", self._calib_done)
        bus.on("check_done", self._check_done)
        bus.on("levels", lambda p: self.can_do.update(p["can_do"]))

    # ---------- start and settings ----------

    def load_settings(self, saved: dict | None, has_calibration: bool, needs_calibration: bool) -> None:
        if saved:
            self.settings = Settings(**{**asdict(Settings()), **saved})
        # The typing test skips the onboarding questions and the signal check: it only needs calibration.
        home = "typing" if self.s["typing"] else "chats"
        if self.settings.onboarded or self.s["typing"]:
            if needs_calibration and not has_calibration:
                self.s.update(screen="landing", landing="calibrate", return_to=home)
            else:
                self.s.update(screen=home)

    def start_typing(self, keyboard: str, passage: int) -> None:
        """Typing test mode: copy a passage for two minutes with the chosen keyboard, no word suggestions."""
        self.s["typing"] = {"keyboard": keyboard, "passage": passage, "text": load_passage(passage), "typed": "",
                            "kb_group": None,
                            "first": None, "left": SECONDS, "selections": 0, "backspaces": 0,
                            "result": None, "done": False}

    def publish(self) -> None:
        state = {**self.s, "settings": asdict(self.settings), "can_do": self.can_do,
                 "undo": {"mode": self.undo["mode"]} if self.undo else None,
                 "predictions": self.predictions(), "quick": self.quick,
                 "kb_groups": KEY_GROUPS}
        self.bus.emit("state", {"state": state})

    def publish_settings(self) -> None:
        self.bus.emit("settings", asdict(self.settings))

    def _screen(self, p: dict) -> None:
        # The view is up and knows its size: calibration can start.
        if not self.started:
            self.started = True
            if self.s["screen"] == "landing" and self.s["landing"] == "calibrate":
                self.bus.emit("start_calibration", {})
        self.publish()

    def _calib_done(self, p: dict) -> None:
        self.s["calib"] = {"error_px": p.get("error_px"), "ok": p.get("ok")}
        if self.s["screen"] == "landing" and self.s["landing"] == "calibrate":
            self.calib_tries += 1
            usable = p.get("error_px") is not None
            # No usable fit means gaze cannot select anything, so always try again. A loose fit is
            # retried a couple of times, then accepted so the person is never stuck here.
            if not usable or (not p.get("ok") and self.calib_tries < 3):
                self.calib_again_at = self.clock.now() + 3.0
                self.publish()
                return
            self.calib_tries = 0
            if self.s["return_to"]:
                self.s.update(screen=self.s["return_to"], return_to=None)
            else:
                self.s["landing"] = "about"
        self.publish()

    def _check_done(self, p: dict) -> None:
        self.can_do.update(p["can_do"])
        self.s["check"] = p["results"]
        if not self.can_do.get(self.settings.preferred):
            usable = [k for k in SIGNALS if self.can_do.get(k) and self.settings.enabled.get(k)]
            if usable:
                self.settings.preferred = usable[0]
                self.publish_settings()
        if self.s["screen"] == "landing":
            if self.s["return_to"]:
                self.s.update(screen=self.s["return_to"], return_to=None)
            else:
                self.s["landing"] = "ready"
        self.publish()

    # ---------- actions ----------

    def on_fire(self, p: dict) -> None:
        action, seq = p["action"], p["seq"]
        now = self.clock.now()
        before_settings = asdict(self.settings)
        if action == "undo" and self.undo and self.undo["mode"] == "undo" and self.last:
            self._restore(self.last[1])
            self.undo = {"mode": "redo", "until": now + self.config["windows"]["undo_s"]}
            self.bus.emit("undo", {"seq": self.last[0], "action": self.last[3]})
        elif action == "redo" and self.undo and self.undo["mode"] == "redo" and self.last:
            self._restore(self.last[2])
            self.undo = None
            self.bus.emit("redo", {"seq": self.last[0], "action": self.last[3]})
        else:
            before = self._snapshot()
            self.apply(action, now)
            if action.split(":", 1)[0] in NOT_UNDOABLE:
                self.undo, self.last = None, None
            else:
                self.last = (seq, before, self._snapshot(), action)
                self.undo = {"mode": "undo", "until": now + self.config["windows"]["undo_s"]}
        if asdict(self.settings) != before_settings:
            self.publish_settings()
        self.publish()

    def _snapshot(self) -> dict:
        return {"s": copy.deepcopy(self.s), "settings": copy.deepcopy(self.settings)}

    def _restore(self, snap: dict) -> None:
        self.s = copy.deepcopy(snap["s"])
        self.settings = copy.deepcopy(snap["settings"])

    def chat(self, chat_id: str | None = None) -> dict | None:
        cid = chat_id or self.s["chat_id"]
        return next((c for c in self.s["chats"] if c["id"] == cid), None)

    def apply(self, action: str, now: float) -> None:
        name, _, arg = action.partition(":")
        s = self.s
        if s["screen"] == "typing":
            self._typing(name, arg, now)
            return
        if name == "open":
            s.update(chat_id=arg, screen="thread", scroll=0)
        elif name == "back":
            s.update(screen={"thread": "chats", "settings": "chats", "compose": "thread",
                             "actions": "thread", "call": "thread"}.get(s["screen"], "chats"),
                     picker=False, kb_group=None)
        elif name == "nav_chats":
            s.update(screen="chats", picker=False)
        elif name == "nav_settings":
            s.update(screen="settings", picker=False)
        elif name == "scroll_up":
            s["scroll"] += 2
        elif name == "scroll_down":
            s["scroll"] = max(0, s["scroll"] - 2)
        elif name == "compose":
            s.update(screen="compose", kb_group=None)
        elif name == "close_keyboard":
            s.update(screen="thread", kb_group=None)
        elif name == "more":
            s.update(selected=arg, screen="actions", picker=False)
        elif name == "close":
            s.update(screen="thread", picker=False)
        elif name == "forward":
            s["picker"] = True
        elif name == "forward_to":
            msg = self._selected()
            target = self.chat(arg)
            if msg and target:
                target["messages"].append(self._message("me", msg["text"], forwarded=True))
            s.update(screen="thread", picker=False)
        elif name == "react":
            msg = self._selected()
            if msg:
                msg["reaction"] = None if msg.get("reaction") else "❤"
            s["screen"] = "thread"
        elif name == "delete":
            c = self.chat()
            if c:
                c["messages"] = [m for m in c["messages"] if m["id"] != s["selected"]]
            s.update(screen="thread", selected=None)
        elif name == "send":
            text = s["draft"].strip()
            c = self.chat()
            if text and c:
                msg = self._message("me", text)
                c["messages"].append(msg)
                s.update(draft="", scroll=0, screen="thread", kb_group=None)
                self.bus.emit("sound", {"name": "sent"})
                self.pending_replies.append({"chat_id": c["id"], "msg_id": msg["id"],
                                             "at": now + self.config["chat"]["reply_after_s"]})
                for w in text.lower().split():
                    self.typed[w] = self.typed.get(w, 0) + 1
        elif name == "call":
            s.update(call={"chat_id": s["chat_id"], "since": now, "connected": False, "seconds": 0, "muted": False},
                     screen="call")
        elif name == "mute" and s["call"]:
            s["call"]["muted"] = not s["call"]["muted"]
        elif name == "end_call":
            s.update(call=None, screen="thread")
        elif name == "group":
            s["kb_group"] = arg
        elif name == "groups":
            s["kb_group"] = None
        elif name == "key":
            s["draft"] += arg
            s["kb_group"] = None
        elif name == "space":
            s["draft"] += " "
        elif name == "backspace":
            s["draft"] = s["draft"][:-1]
        elif name == "predict":
            words = s["draft"].split(" ")
            words[-1] = arg
            s["draft"] = " ".join(words) + " "
        elif name == "quick":
            s["draft"] = self.quick[int(arg)]
        elif name == "toggle":
            self._toggle(arg)
        elif name == "prefer" and self.settings.enabled.get(arg):
            self.settings.preferred = arg
        elif name == "sounds":
            self.settings.sounds = not self.settings.sounds
        elif name == "keyboard":
            self.settings.keyboard = arg
        elif name == "recalibrate":
            s.update(screen="landing", landing="calibrate", return_to="settings")
            self.bus.emit("start_calibration", {})
        elif name == "check_signals":
            s.update(screen="landing", landing="check", return_to="settings")
            self.bus.emit("start_check", {})
        elif name in ("age", "disability", "app"):
            about = s["about"]
            if name == "age":
                about["age"] = None if about["age"] == arg else arg
            else:
                about[name] = [v for v in about[name] if v != arg] if arg in about[name] else about[name] + [arg]
        elif name == "continue":
            if s["landing"] == "about":
                s["landing"] = "check"
                self.bus.emit("start_check", {})
            elif s["landing"] == "ready":
                self.settings.onboarded = True
                s.update(screen="chats")

    def _typing(self, name: str, arg: str, now: float) -> None:
        """One pick in the typing test. The two minutes start with the first character."""
        t = self.s["typing"]
        if t["done"]:
            return
        if name in ("key", "space", "backspace", "group", "groups"):
            t["selections"] += 1
        if name == "group":
            t["kb_group"] = arg
        elif name == "groups":
            t["kb_group"] = None
        elif name in ("key", "space"):
            t["typed"] += arg if name == "key" else " "
            t["kb_group"] = None
            if t["first"] is None:
                t["first"] = now
                self.bus.emit("typing_start", {"keyboard": t["keyboard"], "passage": t["passage"]})
        elif name == "backspace":
            t["typed"] = t["typed"][:-1]
            t["backspaces"] += 1

    def _typing_tick(self, now: float) -> bool:
        """Count down once typing has started; at zero, stop and score. True when the screen changed."""
        t = self.s["typing"]
        if not t or t["done"] or t["first"] is None:
            return False
        left = max(0, math.ceil(SECONDS - (now - t["first"])))
        if left > 0:
            changed, t["left"] = left != t["left"], left
            return changed
        t.update(left=0, done=True, kb_group=None)
        t["result"] = score(t["text"], t["typed"], SECONDS, t["selections"], t["backspaces"])
        self.undo = None                     # nothing to undo once the time is up
        self.bus.emit("typing_result", {"keyboard": t["keyboard"], "passage": t["passage"], **t["result"]})
        return True

    def _toggle(self, signal: str) -> None:
        enabled = self.settings.enabled
        if enabled.get(signal) and sum(enabled.values()) == 1:
            self.bus.emit("notice", {"text": "One signal always stays on."})
            return
        enabled[signal] = not enabled.get(signal)
        if not enabled[signal] and self.settings.preferred == signal:
            self.settings.preferred = next(k for k, v in enabled.items() if v)

    def _selected(self) -> dict | None:
        c = self.chat()
        return next((m for m in c["messages"] if m["id"] == self.s["selected"]), None) if c else None

    def _message(self, sender: str, text: str, forwarded: bool = False) -> dict:
        self.next_id += 1
        return {"id": f"m{self.next_id}", "from": sender, "text": text, "forwarded": forwarded}

    def escape(self) -> None:
        """Calm way out from anywhere: go to the chat list, keep the draft (Scenario 4)."""
        if self.s["screen"] in ("landing", "typing"):
            return
        self.s.update(screen="chats", kb_group=None, picker=False, call=None)
        self.undo = None
        self.publish()

    # ---------- predictions ----------

    def predictions(self) -> list[str]:
        draft = self.s["draft"]
        if not draft:
            return []
        partial = draft.split(" ")[-1].lower()
        if not partial:
            ranked = sorted(self.typed, key=self.typed.get, reverse=True)
            return (ranked + [w for w in ("I", "you", "the") if w not in ranked])[:3]
        rank = {w: i for i, w in enumerate(self.words)}
        found = [w for w in self.words if w.lower().startswith(partial) and w.lower() != partial]
        found += [w for w in self.typed if w.startswith(partial) and w != partial and w not in rank]
        found.sort(key=lambda w: (-self.typed.get(w.lower(), 0), rank.get(w, 10**6)))
        return found[:3]

    # ---------- time ----------

    def tick(self, now: float) -> None:
        changed = self._typing_tick(now)
        if self.calib_again_at is not None and now >= self.calib_again_at:
            self.calib_again_at = None
            self.bus.emit("start_calibration", {})
        if self.undo and now >= self.undo["until"]:
            self.undo = None
            changed = True
        for r in [r for r in self.pending_replies if now >= r["at"]]:
            self.pending_replies.remove(r)
            c = self.chat(r["chat_id"])
            if c and any(m["id"] == r["msg_id"] for m in c["messages"]) and self.replies.get(c["id"]):
                options = self.replies[c["id"]]
                c["messages"].append(self._message("them", options[len(c["messages"]) % len(options)]))
                self.bus.emit("sound", {"name": "received"})
                changed = True
        call = self.s["call"]
        if call:
            elapsed = now - call["since"]
            connect = self.config["chat"]["call_connect_s"]
            if not call["connected"] and elapsed >= connect:
                call["connected"] = True
                changed = True
            seconds = int(max(0, elapsed - connect))
            if call["connected"] and seconds != call["seconds"]:
                call["seconds"] = seconds
                changed = True
        if changed:
            self.publish()

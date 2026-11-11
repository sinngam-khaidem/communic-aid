"""Console: print the learning in the terminal, one easy line per event.

    CHOOSE   which check the router picked for a tier 2 or 3 action, and every option's score
    OUTCOME  what happened after an action, and the reward the learner gave it
    DWELL    how the dwell time moved after a selection (or how far the warm-up has got)
    ROUTER   the router's updated tally for the check it just learned about
    GROUP    the person's context group changed

Stray glances happen all the time, so they are counted and shown as one dim line, not one each.
Only reads events. Nothing listens to Console.
"""

from __future__ import annotations

import os
import sys

from pathlib import Path

from .common import ROOT, Bus, Clock

NAMES = {"dwell": "dwell only", "blink": "blink and hold", "brows": "raise eyebrows",
         "yes": 'say "proceed"', "switch": "switch"}
KINDS = {"worked": "worked", "gave_up": "gave up", "blocked": "blocked an accident",
         "accident": "accident", "passed_by": "passed by"}
COLOURS = {"worked": "32", "gave_up": "33", "blocked": "36", "accident": "31",
           "CHOOSE": "35", "OUTCOME": "1", "DWELL": "34", "ROUTER": "34", "GROUP": "1", "CALIB": "36", "PHONE": "36",
           "dim": "2"}


class Console:
    def __init__(self, bus: Bus, clock: Clock, colour: bool | None = None) -> None:
        self.clock = clock
        self.colour = sys.stdout.isatty() and not os.environ.get("NO_COLOR") if colour is None else colour
        self.glances = 0
        bus.on("choice", self._choice)
        bus.on("learned", self._learned)
        bus.on("context", self._context)
        bus.on("calib_done", self._calib)
        bus.on("link", self._link)

    def legend(self) -> None:
        self._print("\n  Learning log", "GROUP")
        self._print("  CALIB    how well calibration fitted: under 100 px is good\n"
                    "  CHOOSE   the router's pick for a tier 2 or 3 action, with every option's score\n"
                    "  OUTCOME  what happened and its reward. It appears once the 5 s undo window closes,\n"
                    "           so it can come after the next action\n"
                    "  DWELL    how the dwell moved after a selection    ROUTER  the router's updated tally\n"
                    "  GROUP    the person's context group changed\n", "dim")

    # ---------- formatting ----------

    def _paint(self, text: str, key: str) -> str:
        code = COLOURS.get(key)
        return f"\033[{code}m{text}\033[0m" if self.colour and code else text

    def _print(self, text: str, key: str | None = None) -> None:
        print(self._paint(text, key) if key else text)

    def _line(self, tag: str, text: str) -> None:
        t = int(self.clock.now())
        print(f"{t // 60:02d}:{t % 60:02d}  {self._paint(f'{tag:<8}', tag)} {text}")

    @staticmethod
    def _action(action: str) -> str:
        return action.replace(":", " ").replace("_", " ")

    def _flush_glances(self) -> None:
        if self.glances:
            n, self.glances = self.glances, 0
            self._print(f"         ({n} stray glance{'s' if n > 1 else ''} passed by, reward 0 each)", "dim")

    # ---------- events ----------

    def _choice(self, p: dict) -> None:
        self._flush_glances()
        head = f"{self._action(p['action']):<16} tier {p['tier']}  {p['group']:<14} -> {self._paint(NAMES[p['check']], 'CHOOSE')}"
        scores = (p.get("scores") or {}).get("scores")
        if scores:
            ranked = sorted(scores.items(), key=lambda kv: -kv[1])
            head += "   scores: " + "   ".join(f"{NAMES[k]} {v:+.2f}" for k, v in ranked)
        else:
            head += "   (fixed condition)"
        self._line("CHOOSE", head)

    def _learned(self, p: dict) -> None:
        o, r = p["outcome"], p["reward"]
        if o.kind == "passed_by":
            self.glances += 1
            return
        self._flush_glances()
        if o.learner == "dwell":
            detail = f"dwell {o.dwell:.0f} ms" if o.kind in ("worked", "accident") else f"looked {o.duration:.0f} ms"
        else:
            detail = f"check: {NAMES.get(o.check, o.check)}"
            if o.signal_time:
                detail += f", signal took {o.signal_time:.1f} s"
        kind = self._paint(f"{KINDS[o.kind]:<19}", o.kind)
        self._line("OUTCOME", f"{self._action(o.action):<16} tier {o.tier}  {kind} reward {r:+.2f}   {detail}")
        self._changes(p["changes"])

    def _changes(self, changes: list[dict]) -> None:
        if not changes:
            return
        first = changes[0]
        if "tally" in first:
            tally = ", ".join(f"{KINDS[k]} {v}" for k, v in first["tally"].items())
            self._line("ROUTER", f"tier {first['tier']}  {first['group']:<14} {NAMES[first['check']]}: {tally}")
        elif "warmup" in first:
            self._line("DWELL", f"{first['group']}: warm-up {first['warmup']} of {first['of']} selections, "
                                f"staying at {first['dwell']} ms")
        else:
            moves = "   ".join(f"tier {c['tier']} {c['before']} -> {c['after']} ms" for c in changes)
            picks = " / ".join(f"{c['best']}" for c in changes)
            self._line("DWELL", f"{first['group']}: {moves}   (learner's picks {picks} ms)")

    def _link(self, p: dict) -> None:
        if p["phone"]:
            self._line("PHONE", self._paint(f"connected, sending from {p['address']}", "worked"))
        else:
            self._line("PHONE", self._paint("not sending. In GazeStreamer, check the Mac address and press Start streaming.", "gave_up"))

    def _calib(self, p: dict) -> None:
        if "dots" not in p:
            return                                       # mouse test mode: nothing was calibrated
        how = "head-compensated" if p.get("basis") == "plane" else "angles only (update the phone app)"
        if p.get("error_px") is None:
            self._line("CALIB", self._paint(f"not enough steady readings ({p.get('dots', 0)} of 9 dots)", "gave_up"))
            return
        quality = self._paint("good", "worked") if p["ok"] else self._paint("loose", "gave_up")
        self._line("CALIB", f"fit error {p['error_px']:.0f} px ({quality})   steadiness {p['spread_px']:.0f} px   "
                            f"{p['dots']} of 9 dots   {how}")

    def _context(self, p: dict) -> None:
        extra = ", poor tracking" if p.get("poor_tracking") else ""
        self._line("GROUP", f"now {p['group']}{extra}")


# ---------- settings at startup ----------

NO_UNIT = {"warmup_selections", "smoothing", "borrow_looks", "borrow_tries", "preferred_bonus", "tick_hz",
           "check_tries", "escape_presses", "slip_count", "slip_window", "shaky_looks", "tired_hour",
           "http_port", "udp_port", "drain_speed", "shaky_ratio", "poor_fraction", "drift_rate", "version",
           "effort_per_s", "poor_recover_fraction"}


def _notes(path) -> tuple[dict, dict]:
    """Read the comments in config.toml: one per setting, and the lines just above each [section]."""
    keys, sections, above, section = {}, {}, [], None
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if line.startswith("#"):
            above.append(line.lstrip("# ").strip())
        elif line.startswith("["):
            section = line.strip("[]")
            sections[section] = " ".join(a for a in above if a)
            above = []
        elif "=" in line and section:
            key, _, rest = line.partition("=")
            if "#" in rest and not rest.strip().startswith(("[", '"')):
                keys[(section, key.strip())] = rest.split("#", 1)[1].strip()
            above = []
        else:
            above = []
    return keys, sections


def _value(section: str, key: str, value) -> str:
    if isinstance(value, list):
        return ", ".join(repr(v) for v in value)
    if isinstance(value, bool) or isinstance(value, str) or key in NO_UNIT:
        return str(value)
    if key.endswith("_s"):
        return f"{value} s"
    if key.endswith("_ms") or key.endswith("_px"):
        return f"{value} {key.rsplit('_', 1)[1]}"
    if section in ("dwell",) or key in ("start", "min", "max"):
        return f"{value} ms"
    if key in ("min_dist", "max_dist"):
        return f"{value} m"
    return str(value)


def print_config(config: dict, path: Path, info: dict) -> None:
    """Print every setting as a neat table per section, using rich."""
    from rich import box
    from rich.columns import Columns
    from rich.console import Console as RichConsole
    from rich.panel import Panel
    from rich.table import Table

    out = RichConsole()
    keys, _ = _notes(path)
    tables = []
    for section, values in config.items():
        title = f"[bold]{section}[/]"
        often = section in ("costs", "reward")
        if often:
            title += "  [yellow]tuned often[/]"
        has_notes = any((section, k) in keys for k in values)
        table = Table(title=title, box=box.SIMPLE_HEAD, title_justify="left", show_edge=False, pad_edge=False)
        table.add_column("setting", style="cyan", no_wrap=True)
        table.add_column("value", style="bold yellow" if often else "bold", no_wrap=True)
        if has_notes:
            table.add_column("note", style="dim", max_width=44)
        for key, value in values.items():
            row = [key, _value(section, key, value)]
            table.add_row(*(row + [keys.get((section, key), "")] if has_notes else row))
        tables.append(table)
    head = "   ".join(f"[dim]{k}[/] [bold]{v}[/]" for k, v in info.items())
    name = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    out.print(Panel(head, title="[bold]Communic-aid settings[/]", subtitle=f"[dim]{name}[/]", expand=False))
    out.print(Columns(tables, padding=(1, 4)))

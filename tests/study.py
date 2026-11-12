"""
Start one session of the Adaptive vs Fixed study, in the right order for the participant.

    python tests/study.py P03 1                   # first session
    python tests/study.py P03 2                   # second session
    python tests/study.py P03 1 --source mouse    # anything after the session number goes to the app

Odd numbered participants do Adaptive first and even numbered do Fixed first, so getting used to
the app does not favour one condition. Pointing is gaze in both.

Sessions save into data/P03-adaptive and data/P03-fixed. Before the second session, the
participant's onboarding answers and signal levels are copied from the first, so they are not asked
again. Calibration is always done fresh.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

from communicaid.common import ROOT

SETUP = ("settings.json", "signals.json")       # copied to the second session; calibration is not


def order(person: str) -> tuple[str, str]:
    """The two conditions in the order this participant does them."""
    number = re.search(r"\d+", person)
    if not number or "-" in person:
        raise SystemExit(f"Use a participant ID with a number and no dash, for example P03 (not {person}).")
    return ("adaptive", "fixed") if int(number.group()) % 2 else ("fixed", "adaptive")


def prepare(person: str, session: int) -> list[str]:
    """Copy the setup if needed, and return the command that starts the app."""
    conditions = order(person)
    condition = conditions[session - 1]
    folder = ROOT / "data" / f"{person}-{condition}"
    if (folder / "events.jsonl").exists():
        print(f"Note: {folder.name} already has data. This session is added to it.")
    if session == 2:
        first = ROOT / "data" / f"{person}-{conditions[0]}"
        if not (first / "settings.json").exists():
            print(f"Note: {first.name} has no onboarding answers, so the participant will be asked again.")
        else:
            folder.mkdir(parents=True, exist_ok=True)
            for name in SETUP:
                if (first / name).exists() and not (folder / name).exists():
                    shutil.copy(first / name, folder / name)
    return [sys.executable, "-m", "communicaid", "--person", folder.name, "--condition", condition, "--pointing", "gaze"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("person", help="participant ID, for example P03")
    ap.add_argument("session", type=int, choices=(1, 2), help="1 or 2")
    args, rest = ap.parse_known_args()
    first, second = order(args.person)
    print(f"{args.person}: session 1 is {first}, session 2 is {second}. Now: session {args.session}.")
    command = prepare(args.person, args.session) + rest
    print(" ".join(command[1:]), flush=True)
    os.chdir(ROOT)
    os.execv(sys.executable, command)

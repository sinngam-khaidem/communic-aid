"""The typing test: scoring, the phrase lists, and a run through the app state."""

from communicaid.chat import Chat
from communicaid.typing_test import edit_distance, load_phrases, score

seq = iter(range(1, 100_000))


def test_words_per_minute_uses_the_standard_formula():
    r = score("see you at five", "see you at five", first=0.0, last=100.0, selections=30, backspaces=0)
    assert r["wpm"] == 1.68                    # (15 - 1) / 100 s * 60 / 5
    assert r["error_rate"] == 0 and r["exact"] and r["kspc"] == 2.0


def test_errors_left_count_the_letters_that_differ():
    assert edit_distance("see yu at five", "see you at five") == 1
    r = score("see you at five", "see yu at five", 0.0, 60.0, 14, 0)
    assert r["error_rate"] == round(1 / 15, 3) and not r["exact"]


def test_each_keyboard_gets_its_own_phrases():
    grouped, qwerty = load_phrases("grouped"), load_phrases("qwerty")
    assert len(grouped) == len(qwerty) == 5 and not set(grouped) & set(qwerty)
    assert all(set(p) <= set("abcdefghijklmnopqrstuvwxyz ") for p in grouped + qwerty)


def typing_app(world, config, keyboard):
    bus, clock, rec = world
    chat = Chat(bus, clock, config)
    chat.start_typing(keyboard)
    chat.load_settings(None, has_calibration=True, needs_calibration=True)
    return bus, clock, rec, chat


def pick(bus, clock, action, wait=1.0):
    clock.advance(wait)
    bus.emit("fire", {"action": action, "seq": next(seq)})


def test_a_phrase_typed_and_finished_is_scored(world, config):
    bus, clock, rec, chat = typing_app(world, config, "qwerty")
    assert chat.s["screen"] == "typing"              # no onboarding questions or signal check
    phrase = chat.s["typing"]["phrases"][0]
    for ch in phrase:
        pick(bus, clock, "space" if ch == " " else f"key:{ch}")
    pick(bus, clock, "next")
    r = rec.of("typing_trial")[-1]
    assert r["exact"] and r["n"] == 1 and r["keyboard"] == "qwerty"
    assert r["seconds"] == len(phrase) - 1           # from the first character to the last
    assert chat.s["typing"]["i"] == 1 and chat.s["typing"]["typed"] == ""


def test_grouped_picks_count_towards_the_effort(world, config):
    bus, clock, rec, chat = typing_app(world, config, "grouped")
    pick(bus, clock, "group:abc")
    pick(bus, clock, "key:a")
    pick(bus, clock, "group:pqrs")
    pick(bus, clock, "key:p")
    pick(bus, clock, "backspace")
    pick(bus, clock, "next")
    r = rec.of("typing_trial")[-1]
    assert r["typed"] == "a" and r["selections"] == 5 and r["backspaces"] == 1


def test_escape_does_not_leave_the_test_and_the_end_is_reported(world, config):
    bus, clock, rec, chat = typing_app(world, config, "qwerty")
    bus.emit("escape", {})
    assert chat.s["screen"] == "typing"
    for _ in range(5):
        pick(bus, clock, "key:a")
        pick(bus, clock, "next")
    assert chat.s["typing"]["done"] and rec.of("typing_done")[-1]["phrases"] == 5

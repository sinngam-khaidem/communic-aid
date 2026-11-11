"""The typing test: scoring, the passages, and a timed run through the app state."""

from communicaid.chat import Chat
import json

from communicaid.typing_test import SECONDS, edit_distance, load_passage, next_passage, passages, score, used_passages

seq = iter(range(1, 100_000))


def test_words_per_minute_uses_the_standard_formula():
    passage = load_passage(1)
    r = score(passage, passage[:25], seconds=120, selections=50, backspaces=0)
    assert r["wpm"] == 2.4                     # (25 - 1) / 120 s * 60 / 5
    assert r["accuracy"] == 1.0 and r["kspc"] == 2.0


def test_accuracy_counts_the_letters_that_differ():
    assert edit_distance("i woke yp", "i woke up") == 1
    r = score("i woke up early", "i woke yp", 120, 9, 0)
    assert r["errors"] == 1 and r["accuracy"] == round(1 - 1 / 9, 3)


def test_six_different_passages_of_the_same_length():
    texts = passages()
    assert len(texts) == 6 and len(set(texts)) == 6
    assert {len(t) for t in texts} == {248}
    assert set("".join(texts)) <= set("abcdefghijklmnopqrstuvwxyz ")
    assert load_passage(1) == texts[0] and load_passage(6) == texts[5]


def typed_before(root, folder, passage):
    d = root / "data" / folder
    d.mkdir(parents=True, exist_ok=True)
    with (d / "events.jsonl").open("a") as f:
        f.write(json.dumps({"event": "typing_result", "passage": passage, "keyboard": "grouped"}) + "\n")


def test_the_next_passage_is_one_this_participant_has_not_seen(tmp_path):
    assert next_passage(tmp_path, "P01-gaze") == 1
    typed_before(tmp_path, "P01-gaze", 1)
    typed_before(tmp_path, "P01-head", 2)              # another mode of the same participant counts too
    typed_before(tmp_path, "P02-gaze", 3)              # another participant does not
    assert used_passages(tmp_path, "P01-free") == {1, 2}
    assert next_passage(tmp_path, "P01-free") == 3
    for n in range(3, 7):
        typed_before(tmp_path, "P01-free", n)
    assert next_passage(tmp_path, "P01-gaze") is None


def typing_app(world, config, keyboard):
    bus, clock, rec = world
    chat = Chat(bus, clock, config)
    chat.start_typing(keyboard, 2)
    chat.load_settings(None, has_calibration=True, needs_calibration=True)
    return bus, clock, rec, chat


def pick(bus, clock, action, wait=1.0):
    clock.advance(wait)
    bus.emit("fire", {"action": action, "seq": next(seq)})
    bus.emit("tick", {})


def test_the_clock_waits_for_the_first_character(world, config):
    bus, clock, rec, chat = typing_app(world, config, "qwerty")
    assert chat.s["screen"] == "typing"              # no onboarding questions or signal check
    pick(bus, clock, "space", wait=0)
    chat.s["typing"]["typed"] = ""                   # undo that, then just wait
    chat.s["typing"]["first"] = None
    clock.advance(SECONDS + 30)
    bus.emit("tick", {})
    assert not chat.s["typing"]["done"] and chat.s["typing"]["left"] == SECONDS


def test_time_up_stops_typing_and_reports_the_speed(world, config):
    bus, clock, rec, chat = typing_app(world, config, "qwerty")
    text = chat.s["typing"]["text"]
    for ch in text[:30]:                              # one character a second for 30 s
        pick(bus, clock, "space" if ch == " " else f"key:{ch}")
    assert chat.s["typing"]["left"] == SECONDS - 29
    clock.advance(SECONDS)
    bus.emit("tick", {})
    t = chat.s["typing"]
    assert t["done"] and t["left"] == 0
    r = rec.of("typing_result")[-1]
    assert r["chars"] == 30 and r["accuracy"] == 1.0 and r["wpm"] == round(29 / SECONDS * 60 / 5, 2)
    assert r["passage"] == 2 and text == load_passage(2)
    pick(bus, clock, "key:x")                         # too late: nothing changes
    assert chat.s["typing"]["typed"] == text[:30]


def test_grouped_picks_count_towards_the_effort(world, config):
    bus, clock, rec, chat = typing_app(world, config, "grouped")
    for action in ("group:ghi", "key:i", "space", "group:tuv", "key:v", "backspace"):
        pick(bus, clock, action)
    t = chat.s["typing"]
    assert t["typed"] == "i " and t["selections"] == 6 and t["backspaces"] == 1


def test_escape_does_not_leave_the_test(world, config):
    bus, clock, rec, chat = typing_app(world, config, "qwerty")
    bus.emit("escape", {})
    assert chat.s["screen"] == "typing"

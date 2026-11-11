"""The dwell plot reads the learner's own steps, per group, across sessions."""

import json

import plot_dwell


def learned(session, group, kind, changes, condition="adaptive"):
    return {"event": "learned", "session": session, "condition": condition,
            "outcome": {"learner": "dwell", "kind": kind, "group": group}, "changes": changes}


def step(tier, group, before, after):
    return {"tier": tier, "group": group, "before": before, "after": after, "best": 800}


def test_lines_start_where_the_learner_was_and_keep_groups_apart(tmp_path, monkeypatch):
    folder = tmp_path / "data" / "P09-gaze"
    folder.mkdir(parents=True)
    rows = [
        learned("s1", "tired+steady", "worked", [step(0, "tired+steady", 1200, 1190), step(1, "tired+steady", 1300, 1295)]),
        learned("s1", "tired+steady", "passed_by", []),                    # no change: not a selection
        learned("s2", "tired+shaky", "accident", [step(0, "tired+shaky", 900, 990), step(1, "tired+shaky", 1000, 1090)]),
        learned("s2", "tired+steady", "worked", [step(0, "tired+steady", 1190, 1180), step(1, "tired+steady", 1295, 1290)]),
        learned("s3", "tired+steady", "worked", [step(0, "tired+steady", 1180, 1180)], condition="fixed"),
    ]
    (folder / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(plot_dwell, "ROOT", tmp_path)

    data = plot_dwell.load("P09-gaze")

    assert data["n"] == 3                                            # three selections, fixed session left out
    assert data["lines"][(0, "tired+steady")] == [(0, 1200), (1, 1190), (3, 1180)]   # starts at 1200, not 1500
    assert data["lines"][(0, "tired+shaky")] == [(0, 900), (2, 990)]                 # its own dwell
    assert data["selections"]["tired+steady"] == [1, 3]
    assert data["accidents"]["tired+shaky"] == [2]
    assert [s[2] for s in data["sessions"]] == ["s1", "s2"]

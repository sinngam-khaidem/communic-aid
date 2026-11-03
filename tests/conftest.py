import pytest

from communicaid.common import Bus, FakeClock, load_config


class Recorder:
    """Collects every event on the bus so tests can check what happened."""

    def __init__(self, bus: Bus) -> None:
        self.events: list[tuple[str, dict]] = []
        bus.on_all(lambda e, p: self.events.append((e, p)))

    def of(self, name: str) -> list[dict]:
        return [p for e, p in self.events if e == name]

    def outcomes(self) -> list[tuple[str, str]]:
        return [(p["outcome"].learner, p["outcome"].kind) for p in self.of("outcome")]


def run(bus: Bus, clock: FakeClock, seconds: float, hz: int = 60) -> None:
    for _ in range(int(round(seconds * hz))):
        clock.advance(1 / hz)
        bus.emit("tick", {})


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def world():
    bus, clock = Bus(), FakeClock()
    return bus, clock, Recorder(bus)

import threading

import pytest

from backend.simulation.state import (
    EnergyReading,
    SensorSnapshot,
    SimulationClock,
    SimulationStateStore,
    SiteReading,
    ZoneReading,
)


def make_snapshot(temperature: float = 22.0, zones: int = 2) -> SensorSnapshot:
    return SensorSnapshot(
        clock=SimulationClock(month=7, day=21, hour=14, minute=30),
        zones=tuple(
            ZoneReading(name=f"ZONE-{i}", air_temperature_c=temperature + i, occupant_count=3)
            for i in range(zones)
        ),
        site=SiteReading(outdoor_air_temperature_c=31.5),
        energy=EnergyReading(building_electricity_j=1_000_000.0, hvac_electricity_j=500_000.0),
    )


def test_empty_store_has_no_latest():
    store = SimulationStateStore()
    assert store.latest() is None
    assert store.history() == ()
    assert store.published_count == 0


def test_publish_assigns_monotonic_sequence_numbers():
    store = SimulationStateStore()
    first = store.publish(make_snapshot())
    second = store.publish(make_snapshot())
    assert (first.sequence, second.sequence) == (1, 2)
    assert store.latest() is second


def test_publish_stamps_wall_clock_time():
    store = SimulationStateStore()
    assert store.publish(make_snapshot()).captured_at is not None


def test_snapshots_are_immutable():
    snapshot = make_snapshot()
    with pytest.raises(AttributeError):
        snapshot.sequence = 99


def test_history_is_bounded_and_oldest_first():
    store = SimulationStateStore(history_limit=3)
    for temperature in (20.0, 21.0, 22.0, 23.0):
        store.publish(make_snapshot(temperature))

    history = store.history()
    assert len(history) == 3
    assert [s.sequence for s in history] == [2, 3, 4]
    assert store.published_count == 4, "sequence numbering survives history eviction"


def test_history_limit_argument_returns_most_recent():
    store = SimulationStateStore()
    for _ in range(5):
        store.publish(make_snapshot())
    assert [s.sequence for s in store.history(limit=2)] == [4, 5]


def test_derived_aggregates_ignore_missing_readings():
    snapshot = SensorSnapshot(
        clock=SimulationClock(month=1, day=1, hour=0, minute=0),
        zones=(
            ZoneReading(name="A", air_temperature_c=20.0, occupant_count=2),
            ZoneReading(name="B", air_temperature_c=None, occupant_count=None),
            ZoneReading(name="C", air_temperature_c=24.0, occupant_count=4),
        ),
        site=SiteReading(),
        energy=EnergyReading(),
    )
    assert snapshot.mean_air_temperature_c == 22.0
    assert snapshot.total_occupancy == 6


def test_derived_aggregates_are_none_when_nothing_is_readable():
    snapshot = SensorSnapshot(
        clock=SimulationClock(month=1, day=1, hour=0, minute=0),
        zones=(ZoneReading(name="A"),),
        site=SiteReading(),
        energy=EnergyReading(),
    )
    assert snapshot.mean_air_temperature_c is None
    assert snapshot.total_occupancy is None


def test_wait_for_first_unblocks_on_publish():
    store = SimulationStateStore()
    assert store.wait_for_first(timeout=0.01) is False

    threading.Timer(0.05, lambda: store.publish(make_snapshot())).start()
    assert store.wait_for_first(timeout=2.0) is True


def test_concurrent_publishers_produce_unique_sequences():
    """Sequence assignment must stay correct under contention, not just in theory."""
    store = SimulationStateStore(history_limit=10_000)
    publishes_per_thread = 200

    def publish_many() -> None:
        for _ in range(publishes_per_thread):
            store.publish(make_snapshot())

    threads = [threading.Thread(target=publish_many) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    expected = 8 * publishes_per_thread
    sequences = {s.sequence for s in store.history()}
    assert store.published_count == expected
    assert len(sequences) == expected, "duplicate sequence numbers under concurrency"


def test_history_snapshot_is_not_affected_by_later_publishes():
    store = SimulationStateStore()
    store.publish(make_snapshot())
    taken = store.history()
    store.publish(make_snapshot())
    assert len(taken) == 1, "callers must receive a detached copy, not a live view"


def test_rejects_nonsense_history_limit():
    with pytest.raises(ValueError):
        SimulationStateStore(history_limit=0)


def test_history_since_returns_only_newer_snapshots():
    store = SimulationStateStore()
    for _ in range(5):
        store.publish(make_snapshot())

    assert [s.sequence for s in store.history_since(0)] == [1, 2, 3, 4, 5]
    assert [s.sequence for s in store.history_since(3)] == [4, 5]
    assert store.history_since(5) == ()


def test_history_since_lets_a_slow_consumer_catch_up():
    """Polling latest() drops timesteps; draining by sequence must not."""
    store = SimulationStateStore()
    seen: list[int] = []
    last = 0
    for batch in range(3):
        for _ in range(4):
            store.publish(make_snapshot())
        for snapshot in store.history_since(last):
            last = snapshot.sequence
            seen.append(snapshot.sequence)

    assert seen == list(range(1, 13)), "no timestep may be skipped"

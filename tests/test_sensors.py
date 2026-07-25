import pytest

from backend.simulation.sensors import METERS, SITE_KEY, ZONE_VARIABLES, SensorCatalog, SensorReader

ZONES = ("SPACE1-1", "SPACE2-1")


class FakeExchange:
    """Stands in for pyenergyplus' exchange API.

    Returns -1 for anything in `unavailable`, mirroring how EnergyPlus reports a
    variable the model does not produce.
    """

    def __init__(self, unavailable: set[str] | None = None) -> None:
        self.unavailable = unavailable or set()
        self.requested: list[tuple[str, str]] = []
        self.handle_lookups = 0
        self._next_handle = 100

    def request_variable(self, state, variable, key):
        self.requested.append((variable, key))

    def get_variable_handle(self, state, variable, key):
        self.handle_lookups += 1
        if variable in self.unavailable:
            return -1
        self._next_handle += 1
        return self._next_handle

    def get_meter_handle(self, state, meter):
        self.handle_lookups += 1
        if meter in self.unavailable:
            return -1
        self._next_handle += 1
        return self._next_handle

    def get_variable_value(self, state, handle):
        return float(handle)

    def get_meter_value(self, state, handle):
        return float(handle) * 1000.0

    def month(self, state):
        return 7

    def day_of_month(self, state):
        return 21

    def hour(self, state):
        return 14

    def num_time_steps_in_hour(self, state):
        return 4

    def zone_time_step_number(self, state):
        return 3

    def warmup_flag(self, state):
        return 0


@pytest.fixture
def catalog():
    return SensorCatalog(zone_names=ZONES)


def test_requests_every_variable_for_every_zone(catalog):
    exchange = FakeExchange()
    SensorReader(exchange, catalog).request_variables(state=None)

    expected = len(ZONES) * len(ZONE_VARIABLES) + 3  # three site variables
    assert len(exchange.requested) == expected
    assert ("Zone Mean Air Temperature", "SPACE2-1") in exchange.requested
    assert ("Site Outdoor Air Drybulb Temperature", SITE_KEY) in exchange.requested


def test_read_before_resolve_is_an_error(catalog):
    reader = SensorReader(FakeExchange(), catalog)
    with pytest.raises(RuntimeError, match="resolve_handles"):
        reader.read(state=None)


def test_handles_are_resolved_once_not_per_timestep(catalog):
    exchange = FakeExchange()
    reader = SensorReader(exchange, catalog)
    reader.resolve_handles(state=None)

    lookups_after_resolve = exchange.handle_lookups
    for _ in range(10):
        reader.read(state=None)

    assert exchange.handle_lookups == lookups_after_resolve


def test_snapshot_covers_every_zone_in_catalog_order(catalog):
    reader = SensorReader(FakeExchange(), catalog)
    reader.resolve_handles(state=None)
    snapshot = reader.read(state=None)

    assert tuple(zone.name for zone in snapshot.zones) == ZONES
    assert snapshot.clock.label == "07-21 14:30"  # step 3 of 4 starts at :30
    assert all(zone.air_temperature_c is not None for zone in snapshot.zones)


def test_unavailable_variable_becomes_none_without_failing_the_read(catalog):
    exchange = FakeExchange(unavailable={"Zone Air CO2 Concentration", "Zone Mean Air Temperature"})
    reader = SensorReader(exchange, catalog)
    reader.resolve_handles(state=None)
    snapshot = reader.read(state=None)

    assert all(zone.air_temperature_c is None for zone in snapshot.zones)
    assert all(zone.relative_humidity_pct is not None for zone in snapshot.zones)
    assert snapshot.mean_air_temperature_c is None


def test_unavailable_meter_becomes_none(catalog):
    """Mirrors this project's real case: Electricity:Facility does not resolve."""
    exchange = FakeExchange(unavailable={"Electricity:Building"})
    reader = SensorReader(exchange, catalog)
    reader.resolve_handles(state=None)
    energy = reader.read(state=None).energy

    assert energy.building_electricity_j is None
    assert energy.hvac_electricity_j is not None
    assert energy.total_electricity_j == energy.hvac_electricity_j


def test_total_electricity_sums_building_and_hvac(catalog):
    reader = SensorReader(FakeExchange(), catalog)
    reader.resolve_handles(state=None)
    energy = reader.read(state=None).energy

    assert energy.total_electricity_j == pytest.approx(
        energy.building_electricity_j + energy.hvac_electricity_j
    )


def test_meter_table_matches_energy_reading_fields(catalog):
    """The declarative tables must stay in step with the dataclasses they fill."""
    reader = SensorReader(FakeExchange(), catalog)
    reader.resolve_handles(state=None)
    energy = reader.read(state=None).energy

    for field, _ in METERS:
        assert getattr(energy, field) is not None


def test_clock_uses_zone_timestep_index_not_system_minutes(catalog):
    """exchange.minutes() tracks the adaptive system timestep and can exceed 60.

    The zone timestep index is exact: step N of 4 always starts at (N-1)*15.
    """
    exchange = FakeExchange()
    reader = SensorReader(exchange, catalog)
    reader.resolve_handles(state=None)

    for step, expected_minute in ((1, 0), (2, 15), (3, 30), (4, 45)):
        exchange.zone_time_step_number = lambda state, s=step: s
        assert reader.read(state=None).clock.minute == expected_minute


def test_clock_handles_hourly_timesteps(catalog):
    exchange = FakeExchange()
    exchange.num_time_steps_in_hour = lambda state: 1
    exchange.zone_time_step_number = lambda state: 1
    reader = SensorReader(exchange, catalog)
    reader.resolve_handles(state=None)
    assert reader.read(state=None).clock.minute == 0

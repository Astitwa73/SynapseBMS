"""Shared state between the simulation thread and everything that observes it.

The simulation advances in milliseconds; the LLM agent reasons in seconds. They
are decoupled through this store: the simulation publishes immutable snapshots,
and readers take the latest one whenever they are ready for it.

Snapshots are frozen so that a reader holds the lock only long enough to copy a
reference. Once it has that reference the data can never change underneath it,
which makes torn reads -- one zone's temperature paired with another zone's from
the next timestep -- structurally impossible rather than merely unlikely.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone

DEFAULT_HISTORY_LIMIT = 2880  # 30 days at 15-minute timesteps


@dataclass(frozen=True, slots=True)
class SimulationClock:
    """Where the simulation believes it is in time.

    Timestamps mark the START of the timestep interval, the usual convention for
    interval telemetry. It also sidesteps the awkward end-of-interval cases where
    a quarter-hourly sample lands on minute 60 or hour 24.
    """

    month: int
    day: int
    hour: int
    minute: int
    is_warmup: bool = False

    @property
    def label(self) -> str:
        return f"{self.month:02d}-{self.day:02d} {self.hour:02d}:{self.minute:02d}"

    @property
    def calendar_day(self) -> tuple[int, int]:
        return (self.month, self.day)


@dataclass(frozen=True, slots=True)
class ZoneReading:
    """One thermal zone at one instant.

    Every measurement is optional: if EnergyPlus cannot supply a sensor we carry
    None through the system rather than a plausible-looking zero, so a wiring
    problem surfaces as a gap on the dashboard instead of a wrong decision.
    """

    name: str
    air_temperature_c: float | None = None
    relative_humidity_pct: float | None = None
    occupant_count: float | None = None
    cooling_setpoint_c: float | None = None
    heating_setpoint_c: float | None = None
    lighting_power_w: float | None = None
    ventilation_mass_flow_kg_s: float | None = None

    @property
    def is_occupied(self) -> bool:
        return bool(self.occupant_count)


@dataclass(frozen=True, slots=True)
class SiteReading:
    """Outdoor conditions driving the building."""

    outdoor_air_temperature_c: float | None = None
    outdoor_relative_humidity_pct: float | None = None
    direct_solar_w_per_m2: float | None = None


@dataclass(frozen=True, slots=True)
class EnergyReading:
    """Meter totals for the timestep, in joules as EnergyPlus reports them.

    Broken down by end use rather than collected into one figure: knowing that
    cooling dominates is what makes a control decision explainable, and it lets
    the dashboard show the effect of a lighting action on the lighting meter.
    """

    building_electricity_j: float | None = None
    hvac_electricity_j: float | None = None
    plant_electricity_j: float | None = None
    cooling_electricity_j: float | None = None
    heating_electricity_j: float | None = None
    fans_electricity_j: float | None = None
    pumps_electricity_j: float | None = None
    interior_lights_electricity_j: float | None = None
    interior_equipment_electricity_j: float | None = None

    @property
    def total_electricity_j(self) -> float | None:
        """Whole-building electricity.

        Derived rather than read from Electricity:Facility, which this model does
        not expose. EnergyPlus meters electricity on two independent axes, and
        mixing them double-counts:

          system category (disjoint)  Building + HVAC + Plant
          end use (disjoint)          Lights + Equipment + Fans + Cooling + Pumps

        Only the system-category meters are summed here. Plant matters: this
        model cools through a chilled-water loop, so the chiller and its pumps
        are metered under Plant, not HVAC. Omitting it hides exactly the energy
        the agent is controlling.
        """
        parts = [
            self.building_electricity_j,
            self.hvac_electricity_j,
            self.plant_electricity_j,
        ]
        present = [value for value in parts if value is not None]
        return sum(present) if present else None


@dataclass(frozen=True, slots=True)
class SensorSnapshot:
    """A complete, self-consistent view of the building at one timestep."""

    clock: SimulationClock
    zones: tuple[ZoneReading, ...]
    site: SiteReading
    energy: EnergyReading
    sequence: int = 0
    captured_at: datetime | None = None

    @property
    def mean_air_temperature_c(self) -> float | None:
        readings = [z.air_temperature_c for z in self.zones if z.air_temperature_c is not None]
        return sum(readings) / len(readings) if readings else None

    @property
    def total_occupancy(self) -> float | None:
        readings = [z.occupant_count for z in self.zones if z.occupant_count is not None]
        return sum(readings) if readings else None


class SimulationStateStore:
    """Thread-safe latest-value store with bounded history.

    The store owns sequence numbering so that publishers cannot produce
    out-of-order or duplicate sequence numbers.
    """

    def __init__(self, history_limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be at least 1")
        self._lock = threading.Lock()
        self._history: deque[SensorSnapshot] = deque(maxlen=history_limit)
        self._latest: SensorSnapshot | None = None
        self._sequence = 0
        self._first_publish = threading.Event()

    def publish(self, snapshot: SensorSnapshot) -> SensorSnapshot:
        """Record a snapshot, stamping it with a sequence number and wall time."""
        captured_at = snapshot.captured_at or datetime.now(timezone.utc)
        with self._lock:
            self._sequence += 1
            stamped = replace(snapshot, sequence=self._sequence, captured_at=captured_at)
            self._latest = stamped
            self._history.append(stamped)
        self._first_publish.set()
        return stamped

    def latest(self) -> SensorSnapshot | None:
        with self._lock:
            return self._latest

    def history(self, limit: int | None = None) -> tuple[SensorSnapshot, ...]:
        """Return recorded snapshots oldest-first, or the most recent `limit`."""
        with self._lock:
            snapshots = tuple(self._history)
        return snapshots[-limit:] if limit is not None else snapshots

    def history_since(self, sequence: int) -> tuple[SensorSnapshot, ...]:
        """Return snapshots published after `sequence`, oldest-first.

        Polling `latest` drops intermediate timesteps whenever a consumer is
        slower than the simulation -- fine for control, wrong for charts and
        logs. Sequence numbers let a consumer catch up on exactly what it missed.
        """
        with self._lock:
            return tuple(s for s in self._history if s.sequence > sequence)

    def wait_for_first(self, timeout: float | None = None) -> bool:
        """Block until at least one snapshot exists. Used by API readiness checks."""
        return self._first_publish.wait(timeout)

    @property
    def published_count(self) -> int:
        with self._lock:
            return self._sequence

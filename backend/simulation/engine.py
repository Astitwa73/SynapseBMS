"""Runs EnergyPlus on a background thread and publishes what it sees.

run_energyplus blocks for the whole simulation, so it gets a thread of its own.
Everything else in the system observes the result through the state store rather
than by calling into EnergyPlus, which keeps the simulation's timing independent
of how slowly anything else reasons.

Two constraints drove the design:

* A Python exception must never escape a callback. EnergyPlus invokes us from C,
  and unwinding a Python exception through that frame is undefined behaviour.
  Every callback body is therefore wrapped: we log and keep the simulation alive.
* The simulation is far faster than a demo can be watched, so the callback paces
  itself against wall-clock time. Throttling here rather than downstream means we
  slow the producer instead of discarding data.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from collections.abc import Callable, Mapping

from backend.config.paths import default_weather_file, ensure_pyenergyplus_importable
from backend.config.settings import SimulationSettings
from backend.control.actuators import ActuatorRegistry
from backend.control.store import ControlStore
from backend.simulation.sensors import SensorCatalog, SensorReader
from backend.simulation.state import SensorSnapshot, SimulationStateStore

logger = logging.getLogger(__name__)

THREAD_NAME = "energyplus"


@dataclass(frozen=True, slots=True)
class EngineStatus:
    """What the rest of the system is allowed to know about the engine."""

    is_running: bool
    timesteps_published: int
    exit_code: int | None
    error: str | None


class SimulationEngine:
    """Owns the EnergyPlus lifecycle: one simulation, one thread."""

    def __init__(
        self,
        settings: SimulationSettings,
        catalog: SensorCatalog,
        store: SimulationStateStore,
        control: ControlStore | None = None,
        lights_by_zone: Mapping[str, str] | None = None,
        on_timestep: Callable[[SensorSnapshot], None] | None = None,
    ) -> None:
        self._settings = settings
        self._catalog = catalog
        self._store = store
        self._control = control
        self._lights_by_zone = lights_by_zone or {}
        self._on_timestep = on_timestep
        self._actuators: ActuatorRegistry | None = None

        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._finished = threading.Event()
        self._exit_code: int | None = None
        self._error: str | None = None
        self._next_deadline = 0.0
        self._reporting_started = False

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Engine already started; construct a new one to re-run")

        ensure_pyenergyplus_importable()
        self._thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        """Ask the simulation to wind down and wait for the thread to exit.

        EnergyPlus cannot be interrupted mid-timestep, so this sets a flag that
        the callback honours: throttling stops immediately and the remaining
        timesteps run at full speed rather than at demo pace.
        """
        self._stop_requested.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.warning("Simulation thread did not exit within %.0fs", timeout)

    def wait_until_finished(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> EngineStatus:
        return EngineStatus(
            is_running=self.is_running,
            timesteps_published=self._store.published_count,
            exit_code=self._exit_code,
            error=self._error,
        )

    def _run(self) -> None:
        """Thread body. Owns the EnergyPlus state from creation to deletion."""
        from pyenergyplus.api import EnergyPlusAPI

        api = EnergyPlusAPI()
        state = api.state_manager.new_state()
        reader = SensorReader(api.exchange, self._catalog)

        try:
            api.runtime.set_console_output_status(state, False)
            reader.request_variables(state)
            api.runtime.callback_end_zone_timestep_after_zone_reporting(
                state, self._make_timestep_callback(api, reader)
            )

            # Writes must land before the predictor computes zone loads. Setting a
            # setpoint at the end of a timestep appears to succeed and changes
            # nothing until the next one.
            if self._control is not None:
                self._actuators = ActuatorRegistry(
                    api.exchange, self._catalog.zone_names, self._lights_by_zone
                )
                api.runtime.callback_begin_zone_timestep_after_init_heat_balance(
                    state, self._make_control_callback(api)
                )

            command = self._build_command()
            logger.info("Starting EnergyPlus: %s", " ".join(command))
            self._next_deadline = time.perf_counter()
            self._exit_code = api.runtime.run_energyplus(state, command)
            logger.info(
                "EnergyPlus finished with exit code %s after %d published timesteps",
                self._exit_code,
                self._store.published_count,
            )
        except Exception as exc:  # noqa: BLE001 - thread boundary; nothing above can catch
            self._error = f"{type(exc).__name__}: {exc}"
            logger.exception("Simulation thread failed")
        finally:
            api.state_manager.delete_state(state)
            self._finished.set()

    def _build_command(self) -> list[str]:
        output_dir = self._settings.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        weather = self._settings.weather_path or default_weather_file()

        command = ["-d", str(output_dir), "-w", str(weather)]
        if self._settings.design_day_only:
            command.insert(0, "-D")
        command.append(str(self._settings.model_path))
        return command

    def _make_timestep_callback(self, api, reader: SensorReader):
        """Build the callback EnergyPlus invokes at the end of every timestep."""

        def on_timestep(state) -> None:
            try:
                self._handle_timestep(api, reader, state)
            except Exception:  # noqa: BLE001 - must not unwind into EnergyPlus C code
                logger.exception("Sensor callback failed; simulation continues")

        return on_timestep

    def _make_control_callback(self, api):
        """Build the callback that applies the current command before the predictor."""

        def on_begin_timestep(state) -> None:
            try:
                self._apply_control(api, state)
            except Exception:  # noqa: BLE001 - must not unwind into EnergyPlus C code
                logger.exception("Control callback failed; simulation continues")

        return on_begin_timestep

    def _apply_control(self, api, state) -> None:
        if self._actuators is None or self._stop_requested.is_set():
            return
        if not api.exchange.api_data_fully_ready(state) or api.exchange.warmup_flag(state):
            return

        if not self._actuators.is_resolved:
            self._actuators.resolve_handles(state)

        snapshot = self._store.latest()
        if snapshot is not None:
            self._actuators.observe_lighting(
                {zone.name: zone.lighting_power_w for zone in snapshot.zones}
            )

        self._actuators.apply(state, self._control.current() if self._control else None)

    def _handle_timestep(self, api, reader: SensorReader, state) -> None:
        if self._stop_requested.is_set():
            return

        # Warmup repeats the same day to settle thermal mass. Its readings are
        # not real building state and would corrupt both history and averages.
        if not api.exchange.api_data_fully_ready(state) or api.exchange.warmup_flag(state):
            return

        if not reader.is_resolved:
            reader.resolve_handles(state)

        snapshot = reader.read(state)
        if not self._should_report(snapshot.clock.calendar_day):
            return

        stamped = self._store.publish(snapshot)

        # Runs inside the EnergyPlus callback, so it blocks the simulation until
        # it returns. That is wrong for a live demo, where the agent must not be
        # able to stall the building, and exactly right for a benchmark, where
        # every policy must get the same number of decisions however slow it is.
        if self._on_timestep is not None:
            self._on_timestep(stamped)

        self._throttle()

    def _should_report(self, calendar_day: tuple[int, int]) -> bool:
        """Fast-forward past uninteresting dates before slowing to demo pace."""
        if self._reporting_started:
            return True

        target = self._settings.report_from
        if target is not None and calendar_day < tuple(target):
            return False

        self._reporting_started = True
        self._next_deadline = time.perf_counter()
        logger.info("Reporting started at %02d-%02d", *calendar_day)
        return True

    def _throttle(self) -> None:
        """Pace the simulation to wall-clock time using absolute deadlines.

        Deadline-based rather than a flat sleep so that time spent reading
        sensors does not accumulate into drift over a long run.
        """
        interval = self._settings.seconds_per_timestep
        if interval <= 0:
            return

        now = time.perf_counter()
        remaining = self._next_deadline - now
        if remaining > 0:
            time.sleep(remaining)
        self._next_deadline = max(now, self._next_deadline) + interval

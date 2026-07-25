"""Discover which sensors a building model can actually provide.

EnergyPlus returns a handle of -1 for any output variable that the model does not
produce, and a variable is only produced if it was requested before the run
started. Rather than guess which variable names exist in a given model, this
script requests every candidate we might want, runs a short simulation, and
reports which handles resolved.

The result is the contract the sensor layer is built against.

    python scripts/inspect_model.py
    python scripts/inspect_model.py --model 5ZoneAirCooled.idf

Writes docs/available_sensors.json and prints a summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config.paths import (  # noqa: E402
    EnergyPlusNotFoundError,
    default_weather_file,
    ensure_pyenergyplus_importable,
)
from backend.config.settings import (  # noqa: E402
    DEFAULT_MODEL_NAME,
    DOCS_DIR,
    MODELS_DIR,
    run_output_dir,
)
from backend.simulation.idf import controllable_zone_names, zone_names  # noqa: E402

# Requested per zone, keyed by the zone name.
ZONE_VARIABLE_CANDIDATES = (
    "Zone Mean Air Temperature",
    "Zone Air Relative Humidity",
    "Zone Air Humidity Ratio",
    "Zone People Occupant Count",
    "Zone Air CO2 Concentration",
    "Zone Thermostat Cooling Setpoint Temperature",
    "Zone Thermostat Heating Setpoint Temperature",
    "Zone Lights Electricity Rate",
    "Zone Mechanical Ventilation Mass Flow Rate",
)

# Requested once, keyed by the reserved key "Environment".
SITE_VARIABLE_CANDIDATES = (
    "Site Outdoor Air Drybulb Temperature",
    "Site Outdoor Air Relative Humidity",
    "Site Direct Solar Radiation Rate per Area",
)

METER_CANDIDATES = (
    "Electricity:Facility",
    "Electricity:Building",
    "Electricity:HVAC",
    "Cooling:Electricity",
    "Heating:Electricity",
    "InteriorLights:Electricity",
    "InteriorEquipment:Electricity",
    "Fans:Electricity",
)

SITE_KEY = "Environment"


def build_candidate_list(zones: list[str]) -> list[tuple[str, str]]:
    """Return (variable_name, key) pairs to request before the run."""
    pairs = [(name, zone) for zone in zones for name in ZONE_VARIABLE_CANDIDATES]
    pairs.extend((name, SITE_KEY) for name in SITE_VARIABLE_CANDIDATES)
    return pairs


def inspect(model_path: Path) -> dict:
    from pyenergyplus.api import EnergyPlusAPI

    all_zones = zone_names(model_path)
    if not all_zones:
        raise RuntimeError(f"No Zone objects found in {model_path}")

    # Sensors are only requested for zones a BMS can actually act on; plenums and
    # other unconditioned zones would add noise to both reasoning and averages.
    zones = controllable_zone_names(model_path)
    if not zones:
        print("WARN: no ZoneControl:Thermostat found; falling back to all zones")
        zones = all_zones

    api = EnergyPlusAPI()
    state = api.state_manager.new_state()
    api.runtime.set_console_output_status(state, False)

    candidates = build_candidate_list(zones)
    for variable_name, key in candidates:
        api.exchange.request_variable(state, variable_name, key)

    findings: dict = {}

    def capture_once(current_state) -> None:
        """Resolve every handle on the first timestep where real data exists."""
        if findings or not api.exchange.api_data_fully_ready(current_state):
            return
        if api.exchange.warmup_flag(current_state):
            return

        findings["variables"] = {
            f"{variable_name} @ {key}": api.exchange.get_variable_handle(
                current_state, variable_name, key
            )
            for variable_name, key in candidates
        }
        findings["meters"] = {
            meter: api.exchange.get_meter_handle(current_state, meter)
            for meter in METER_CANDIDATES
        }
        findings["timesteps_per_hour"] = api.exchange.num_time_steps_in_hour(current_state)

    api.runtime.callback_end_zone_timestep_after_zone_reporting(state, capture_once)

    output_dir = run_output_dir("inspect")
    exit_code = api.runtime.run_energyplus(
        state,
        ["-D", "-d", str(output_dir), "-w", str(default_weather_file()), str(model_path)],
    )
    api.state_manager.delete_state(state)

    if exit_code != 0:
        raise RuntimeError(
            f"EnergyPlus exited with code {exit_code}. See {output_dir / 'eplusout.err'}"
        )
    if not findings:
        raise RuntimeError("Simulation finished without ever reaching a ready timestep")

    findings["model"] = model_path.name
    findings["controllable_zones"] = zones
    findings["excluded_zones"] = [z for z in all_zones if z not in zones]
    return findings


def report(findings: dict) -> None:
    resolved = {k: v for k, v in findings["variables"].items() if v >= 0}
    missing = sorted(k for k, v in findings["variables"].items() if v < 0)
    meters_ok = {k: v for k, v in findings["meters"].items() if v >= 0}
    meters_missing = sorted(k for k, v in findings["meters"].items() if v < 0)

    print(f"\nModel      : {findings['model']}")
    print(f"Controlled : {', '.join(findings['controllable_zones'])}")
    print(f"Excluded   : {', '.join(findings['excluded_zones']) or 'none'}")
    print(f"Timesteps/h: {findings['timesteps_per_hour']}")

    print(f"\nAvailable variables ({len(resolved)}/{len(findings['variables'])}):")
    for name in sorted(resolved):
        print(f"  OK   {name}")
    for name in missing:
        print(f"  --   {name}")

    print(f"\nAvailable meters ({len(meters_ok)}/{len(findings['meters'])}):")
    for name in sorted(meters_ok):
        print(f"  OK   {name}")
    for name in meters_missing:
        print(f"  --   {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME)
    args = parser.parse_args()

    model_path = MODELS_DIR / args.model
    if not model_path.is_file():
        print(f"FAIL: {model_path} not found.", file=sys.stderr)
        print("      Run: python scripts/prepare_model.py", file=sys.stderr)
        return 1

    try:
        ensure_pyenergyplus_importable()
        findings = inspect(model_path)
    except EnergyPlusNotFoundError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - diagnostic tool, surface everything
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    report(findings)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DOCS_DIR / "available_sensors.json"
    output_path.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    print(f"\nWrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

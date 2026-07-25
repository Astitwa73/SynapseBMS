"""Environment check for the EnergyPlus Python API.

Run this before building anything else. It answers the one question the whole
project rests on: can we drive a simulation in-process and receive callbacks
while it is running?

    python scripts/verify_energyplus.py          # import + version only
    python scripts/verify_energyplus.py --run    # also run a design-day sim
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config.paths import (  # noqa: E402
    EnergyPlusNotFoundError,
    default_weather_file,
    ensure_pyenergyplus_importable,
)
from backend.config.settings import run_output_dir  # noqa: E402

EXAMPLE_IDF = "ExampleFiles/1ZoneUncontrolled.idf"


def check_import() -> Path:
    install_dir = ensure_pyenergyplus_importable()
    from pyenergyplus.api import EnergyPlusAPI

    api = EnergyPlusAPI()
    print(f"  install dir  : {install_dir}")
    print(f"  API version  : {api.api_version()}")
    return install_dir


def check_callback_run(install_dir: Path) -> int:
    """Run a short simulation and count how many times our callback fires.

    A non-zero count is the real result here: it proves we can observe -- and
    later, actuate -- the building while EnergyPlus is mid-run.
    """
    from pyenergyplus.api import EnergyPlusAPI

    idf = install_dir / EXAMPLE_IDF
    epw = default_weather_file()
    print(f"  model        : {idf.name}")
    print(f"  weather      : {epw.name}")

    api = EnergyPlusAPI()
    state = api.state_manager.new_state()
    api.runtime.set_console_output_status(state, False)

    timesteps = 0

    def on_timestep(_state) -> None:
        nonlocal timesteps
        timesteps += 1

    api.runtime.callback_end_zone_timestep_after_zone_reporting(state, on_timestep)

    output_dir = run_output_dir("verify")
    exit_code = api.runtime.run_energyplus(
        state,
        ["-D", "-d", str(output_dir), "-w", str(epw), str(idf)],
    )
    api.state_manager.delete_state(state)

    print(f"  artifacts    : {output_dir}")

    if exit_code != 0:
        raise RuntimeError(
            f"EnergyPlus exited with code {exit_code}. See {output_dir / 'eplusout.err'}"
        )
    if timesteps == 0:
        raise RuntimeError("Simulation ran but no callbacks fired")

    print(f"  callbacks    : {timesteps} timesteps observed")
    return timesteps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="store_true",
        help="also run a design-day simulation to verify callbacks fire",
    )
    args = parser.parse_args()

    try:
        print("[1/2] Importing pyenergyplus")
        install_dir = check_import()

        if args.run:
            print("[2/2] Running design-day simulation")
            check_callback_run(install_dir)
        else:
            print("[2/2] Skipped (pass --run to verify callbacks)")
    except EnergyPlusNotFoundError as exc:
        print(f"\nFAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - surface anything to the operator
        print(f"\nFAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("\nOK: EnergyPlus Python API is usable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

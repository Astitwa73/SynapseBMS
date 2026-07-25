"""Copy a building model out of the EnergyPlus install into models/.

Models are project inputs and belong under version control next to the code that
reads them -- not resolved from whatever EnergyPlus version happens to be on the
machine. Doing this once, explicitly, means a run is reproducible even if the
install is upgraded underneath us.

    python scripts/prepare_model.py
    python scripts/prepare_model.py --model 5ZoneAirCooled.idf
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config.paths import EnergyPlusNotFoundError, energyplus_dir  # noqa: E402
from backend.config.settings import DEFAULT_MODEL_NAME, MODELS_DIR  # noqa: E402
from backend.simulation.idf import zone_names  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME, help="example file name")
    parser.add_argument("--force", action="store_true", help="overwrite an existing copy")
    args = parser.parse_args()

    try:
        source = energyplus_dir() / "ExampleFiles" / args.model
    except EnergyPlusNotFoundError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if not source.is_file():
        print(f"FAIL: {source} does not exist.", file=sys.stderr)
        print("       List available models with:", file=sys.stderr)
        print(f"       ls '{source.parent}'", file=sys.stderr)
        return 1

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    destination = MODELS_DIR / args.model

    if destination.exists() and not args.force:
        print(f"Already present: {destination}  (use --force to overwrite)")
    else:
        shutil.copy2(source, destination)
        print(f"Copied {source.name} -> {destination}")

    zones = zone_names(destination)
    print(f"\nZones found ({len(zones)}):")
    for zone in zones:
        print(f"  - {zone}")

    if not zones:
        print("\nWARN: no Zone objects parsed. The model may use an unexpected format.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Locates the EnergyPlus installation and makes its Python API importable.

EnergyPlus ships `pyenergyplus` inside its install directory rather than
publishing it to PyPI, so every entry point must resolve that directory before
importing anything from it. This module is the only place that logic lives.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ENERGYPLUS_DIR_ENV_VAR = "ENERGYPLUS_DIR"

# The weather file the shipped example models are written against.
PREFERRED_WEATHER_FILE = "WeatherData/USA_CO_Golden-NREL.724666_TMY3.epw"

_WINDOWS_INSTALL_GLOBS = ("C:/EnergyPlusV*", "C:/Program Files/EnergyPlusV*")
_POSIX_INSTALL_GLOBS = ("/usr/local/EnergyPlus-*", "/Applications/EnergyPlus-*")


class EnergyPlusNotFoundError(RuntimeError):
    """Raised when no usable EnergyPlus installation can be located."""


def energyplus_dir() -> Path:
    """Return the EnergyPlus install directory, preferring an explicit override.

    Resolution order: ENERGYPLUS_DIR, then the conventional install locations,
    newest version first when several are present.
    """
    override = os.environ.get(ENERGYPLUS_DIR_ENV_VAR)
    if override:
        candidate = Path(override)
        if not _is_energyplus_install(candidate):
            raise EnergyPlusNotFoundError(
                f"{ENERGYPLUS_DIR_ENV_VAR}={override} does not contain a "
                f"pyenergyplus package. Point it at the EnergyPlus install root."
            )
        return candidate

    discovered = sorted(_discover_installs(), reverse=True)
    if not discovered:
        raise EnergyPlusNotFoundError(
            "No EnergyPlus installation found. Install EnergyPlus, or set "
            f"{ENERGYPLUS_DIR_ENV_VAR} to its install root."
        )
    return discovered[0]


def ensure_pyenergyplus_importable() -> Path:
    """Make `import pyenergyplus` work in this process. Idempotent.

    On Windows the API's dependent DLLs sit beside energyplusapi.dll, and since
    Python 3.8 those are not found via PATH -- the directory has to be
    registered explicitly or the ctypes load fails with a bare OSError.
    """
    install_dir = energyplus_dir()

    if sys.platform == "win32":
        os.add_dll_directory(str(install_dir))

    path_entry = str(install_dir)
    if path_entry not in sys.path:
        sys.path.insert(0, path_entry)

    return install_dir


def example_file(relative_path: str) -> Path:
    """Resolve a file shipped with EnergyPlus, e.g. 'WeatherData/....epw'."""
    resolved = energyplus_dir() / relative_path
    if not resolved.exists():
        raise FileNotFoundError(f"EnergyPlus does not ship {relative_path}")
    return resolved


def default_weather_file() -> Path:
    """Pick a shipped weather file, preferring the one E+ examples assume."""
    install_dir = energyplus_dir()
    preferred = install_dir / PREFERRED_WEATHER_FILE
    if preferred.is_file():
        return preferred

    available = sorted((install_dir / "WeatherData").glob("*.epw"))
    if not available:
        raise FileNotFoundError("No .epw weather files found in the EnergyPlus install")
    return available[0]


def _discover_installs() -> list[Path]:
    globs = _WINDOWS_INSTALL_GLOBS if sys.platform == "win32" else _POSIX_INSTALL_GLOBS
    return [
        path
        for pattern in globs
        for path in Path(pattern).parent.glob(Path(pattern).name)
        if _is_energyplus_install(path)
    ]


def _is_energyplus_install(path: Path) -> bool:
    return (path / "pyenergyplus" / "api.py").is_file()

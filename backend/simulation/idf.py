"""Minimal read-only IDF parsing, used to discover what a building model contains.

We need zone names before we can ask EnergyPlus for zone sensors, and hardcoding
them couples our code to one specific example file. A full IDF library (eppy)
would do far more than we need and pulls in its own version-matched schema; the
grammar we actually depend on is small enough to read directly:

    ObjectType, field, field, ..., field;   with '!' starting a comment

This module is read-only by design. Anything that needs to *modify* a model
should be an explicit, reviewable script rather than a runtime transformation.
"""

from __future__ import annotations

from pathlib import Path


def parse_objects(idf_text: str) -> list[tuple[str, list[str]]]:
    """Return (object_type, fields) for every object in the file."""
    without_comments = "\n".join(line.split("!", 1)[0] for line in idf_text.splitlines())

    objects: list[tuple[str, list[str]]] = []
    for statement in without_comments.split(";"):
        fields = [field.strip() for field in statement.split(",")]
        fields = [field for field in fields if field]
        if fields:
            objects.append((fields[0], fields[1:]))
    return objects


def objects_of_type(idf_text: str, object_type: str) -> list[list[str]]:
    """Return the field lists of every object of the given type, case-insensitively."""
    wanted = object_type.casefold()
    return [fields for name, fields in parse_objects(idf_text) if name.casefold() == wanted]


def zone_names(idf_path: Path) -> list[str]:
    """Return every thermal zone declared in a model, in file order.

    Order matters for presentation: it keeps dashboard zone ordering stable
    across runs instead of depending on dictionary iteration.

    Note that this includes unoccupied zones such as return-air plenums. Use
    controllable_zone_names for the zones a BMS would actually manage.
    """
    return [fields[0] for fields in objects_of_type(_read(idf_path), "Zone") if fields]


def controllable_zone_names(idf_path: Path) -> list[str]:
    """Return the zones that a thermostat controls, in model declaration order.

    Building models contain zones no occupant experiences -- return-air plenums,
    shafts, unconditioned attics. Filtering them by name would be guesswork, so
    we use the definition the model itself states: a zone is controllable when a
    ZoneControl:Thermostat targets it, directly or through a ZoneList.
    """
    text = _read(idf_path)

    zone_lists = {
        fields[0].casefold(): fields[1:]
        for fields in objects_of_type(text, "ZoneList")
        if fields
    }

    controlled: set[str] = set()
    for fields in objects_of_type(text, "ZoneControl:Thermostat"):
        if len(fields) < 2:
            continue
        target = fields[1]
        controlled.update(
            name.casefold() for name in zone_lists.get(target.casefold(), [target])
        )

    return [name for name in zone_names(idf_path) if name.casefold() in controlled]


def _read(idf_path: Path) -> str:
    return idf_path.read_text(encoding="utf-8", errors="replace")

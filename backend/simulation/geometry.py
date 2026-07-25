"""Zone footprints and orientations, read from the model's own geometry.

The digital twin draws the building EnergyPlus is actually simulating rather
than a diagram that resembles it. Anyone who works with building models will
recognise the difference immediately, and a floor plan that does not match the
model is worse than a table -- it looks like evidence and is not.

Floor polygons come from the FLOOR surface of each zone. Facade orientation
comes from the outward normal of each exterior wall, computed with Newell's
method: EnergyPlus requires surface vertices counter-clockwise as seen from
outside, so the resulting normal points out of the building.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from backend.simulation.idf import objects_of_type

# Field offsets in BuildingSurface:Detailed. Positional, which is why the parser
# must preserve blank fields.
SURFACE_TYPE = 1
SURFACE_ZONE = 3
SURFACE_BOUNDARY = 5
SURFACE_VERTEX_COUNT = 10
SURFACE_FIRST_VERTEX = 11

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True, slots=True)
class ZoneGeometry:
    """One zone's plan footprint and how it sits in the building."""

    name: str
    footprint: tuple[tuple[float, float], ...]
    area_m2: float
    centroid: tuple[float, float]
    is_core: bool
    exterior_walls: int
    orientation: str | None
    azimuth_deg: float | None


@dataclass(frozen=True, slots=True)
class BuildingGeometry:
    zones: tuple[ZoneGeometry, ...]
    bounds: tuple[float, float, float, float]  # min_x, min_y, max_x, max_y

    @property
    def width_m(self) -> float:
        return self.bounds[2] - self.bounds[0]

    @property
    def depth_m(self) -> float:
        return self.bounds[3] - self.bounds[1]

    @property
    def floor_area_m2(self) -> float:
        return sum(zone.area_m2 for zone in self.zones)


def read_geometry(idf_path: Path, zone_names: tuple[str, ...] | None = None) -> BuildingGeometry:
    """Extract plan geometry for the given zones, or every zone with a floor."""
    surfaces = objects_of_type(
        idf_path.read_text(encoding="utf-8", errors="replace"), "BuildingSurface:Detailed"
    )

    floors: dict[str, list[tuple[float, float, float]]] = {}
    exterior_walls: dict[str, list[float]] = {}

    for fields in surfaces:
        if len(fields) <= SURFACE_FIRST_VERTEX:
            continue

        zone = fields[SURFACE_ZONE]
        if zone_names is not None and zone not in zone_names:
            continue

        vertices = _read_vertices(fields)
        if not vertices:
            continue

        surface_type = fields[SURFACE_TYPE].casefold()
        if surface_type == "floor":
            floors[zone] = vertices
        elif surface_type == "wall" and fields[SURFACE_BOUNDARY].casefold() == "outdoors":
            exterior_walls.setdefault(zone, []).append(_azimuth_of(vertices))

    zones = tuple(
        _build_zone(name, vertices, exterior_walls.get(name, []))
        for name, vertices in floors.items()
    )
    return BuildingGeometry(zones=zones, bounds=_bounds(zones))


def _read_vertices(fields: list[str]) -> list[tuple[float, float, float]]:
    """Read the X,Y,Z triples that follow the vertex count."""
    try:
        count = int(float(fields[SURFACE_VERTEX_COUNT]))
    except (ValueError, IndexError):
        return []

    vertices: list[tuple[float, float, float]] = []
    for index in range(count):
        start = SURFACE_FIRST_VERTEX + index * 3
        if start + 2 >= len(fields):
            break
        try:
            vertices.append(
                (float(fields[start]), float(fields[start + 1]), float(fields[start + 2]))
            )
        except ValueError:
            break
    return vertices


def _build_zone(name: str, vertices, wall_azimuths: list[float]) -> ZoneGeometry:
    footprint = tuple((x, y) for x, y, _ in vertices)
    azimuth = _mean_azimuth(wall_azimuths)

    return ZoneGeometry(
        name=name,
        footprint=footprint,
        area_m2=abs(_signed_area(footprint)),
        centroid=_centroid(footprint),
        # A zone with no wall facing outdoors is a core zone: no solar gain, no
        # envelope losses, and a different thermal character entirely.
        is_core=not wall_azimuths,
        exterior_walls=len(wall_azimuths),
        orientation=_compass(azimuth) if azimuth is not None else None,
        azimuth_deg=azimuth,
    )


def _azimuth_of(vertices: list[tuple[float, float, float]]) -> float:
    """Compass bearing of a surface's outward normal, via Newell's method.

    Newell's method is used rather than a single cross product because it is
    stable for non-planar and near-degenerate polygons, which real models
    contain. EnergyPlus orders vertices counter-clockwise from outside, so the
    normal points away from the building.
    """
    normal_x = normal_y = 0.0
    count = len(vertices)

    for index in range(count):
        current = vertices[index]
        following = vertices[(index + 1) % count]
        normal_x += (current[1] - following[1]) * (current[2] + following[2])
        normal_y += (current[2] - following[2]) * (current[0] + following[0])

    return math.degrees(math.atan2(normal_x, normal_y)) % 360.0


def _mean_azimuth(azimuths: list[float]) -> float | None:
    """Average bearings as unit vectors; averaging degrees breaks across north."""
    if not azimuths:
        return None

    x = sum(math.sin(math.radians(a)) for a in azimuths)
    y = sum(math.cos(math.radians(a)) for a in azimuths)
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return None
    return math.degrees(math.atan2(x, y)) % 360.0


def _compass(azimuth: float) -> str:
    return COMPASS[round(azimuth / 45.0) % 8]


def _signed_area(footprint: tuple[tuple[float, float], ...]) -> float:
    """Shoelace formula. Sign indicates winding, so callers take the magnitude."""
    total = 0.0
    count = len(footprint)
    for index in range(count):
        x1, y1 = footprint[index]
        x2, y2 = footprint[(index + 1) % count]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _centroid(footprint: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    area = _signed_area(footprint)
    if abs(area) < 1e-9:
        count = len(footprint) or 1
        return (
            sum(x for x, _ in footprint) / count,
            sum(y for _, y in footprint) / count,
        )

    cx = cy = 0.0
    count = len(footprint)
    for index in range(count):
        x1, y1 = footprint[index]
        x2, y2 = footprint[(index + 1) % count]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross

    return (cx / (6 * area), cy / (6 * area))


def _bounds(zones: tuple[ZoneGeometry, ...]) -> tuple[float, float, float, float]:
    points = [point for zone in zones for point in zone.footprint]
    if not points:
        return (0.0, 0.0, 0.0, 0.0)

    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return (min(xs), min(ys), max(xs), max(ys))

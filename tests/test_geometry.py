import math
from pathlib import Path

import pytest

from backend.simulation.geometry import _azimuth_of, _signed_area, read_geometry
from backend.simulation.idf import controllable_zone_names, parse_objects

MODEL = Path("models/5ZoneAirCooled.idf")

# A square room, 10 x 10, with one exterior wall facing south (-Y).
SAMPLE_IDF = """\
BuildingSurface:Detailed,
    FLOOR-A, Floor, SLAB, ZONE-A, , Ground, , NoSun, NoWind, 0, 4,
    0.0,0.0,0.0,
    10.0,0.0,0.0,
    10.0,10.0,0.0,
    0.0,10.0,0.0;

BuildingSurface:Detailed,
    WALL-A, Wall, EXT, ZONE-A, , Outdoors, , SunExposed, WindExposed, 0.5, 4,
    0.0,0.0,3.0,
    0.0,0.0,0.0,
    10.0,0.0,0.0,
    10.0,0.0,3.0;

BuildingSurface:Detailed,
    FLOOR-B, Floor, SLAB, ZONE-B, , Ground, , NoSun, NoWind, 0, 4,
    10.0,0.0,0.0,
    20.0,0.0,0.0,
    20.0,10.0,0.0,
    10.0,10.0,0.0;
"""


# --- the parser must keep blank fields, or every offset shifts ---------------


def test_blank_fields_are_preserved_so_offsets_stay_correct():
    """Space Name is blank in real IDFs; dropping it shifts vertices by one."""
    fields = parse_objects(SAMPLE_IDF)[0][1]

    assert fields[1] == "Floor"
    assert fields[3] == "ZONE-A"
    assert fields[4] == "", "the blank Space Name must survive parsing"
    assert fields[5] == "Ground"


# --- geometry ---------------------------------------------------------------


@pytest.fixture
def sample(tmp_path):
    model = tmp_path / "sample.idf"
    model.write_text(SAMPLE_IDF, encoding="utf-8")
    return read_geometry(model)


def test_floor_polygon_and_area_are_read_from_vertices(sample):
    zone = next(z for z in sample.zones if z.name == "ZONE-A")

    assert zone.area_m2 == pytest.approx(100.0)
    assert zone.footprint == ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    assert zone.centroid == pytest.approx((5.0, 5.0))


def test_a_zone_with_no_exterior_wall_is_a_core_zone(sample):
    core = next(z for z in sample.zones if z.name == "ZONE-B")

    assert core.is_core
    assert core.exterior_walls == 0
    assert core.orientation is None


def test_exterior_orientation_comes_from_the_outward_normal(sample):
    zone = next(z for z in sample.zones if z.name == "ZONE-A")

    assert zone.orientation == "S"
    assert zone.azimuth_deg == pytest.approx(180.0)
    assert not zone.is_core


def test_bounds_cover_every_zone(sample):
    assert sample.bounds == (0.0, 0.0, 20.0, 10.0)
    assert sample.floor_area_m2 == pytest.approx(200.0)


def test_signed_area_magnitude_is_winding_independent():
    clockwise = ((0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0))
    counter = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))

    assert _signed_area(clockwise) == -_signed_area(counter)
    assert abs(_signed_area(clockwise)) == pytest.approx(100.0)


@pytest.mark.parametrize(
    "vertices,expected",
    [
        ([(0, 0, 3), (0, 0, 0), (10, 0, 0), (10, 0, 3)], 180.0),  # faces -Y, south
        ([(10, 0, 3), (10, 0, 0), (10, 10, 0), (10, 10, 3)], 90.0),  # faces +X, east
        ([(10, 10, 3), (10, 10, 0), (0, 10, 0), (0, 10, 3)], 0.0),  # faces +Y, north
        ([(0, 10, 3), (0, 10, 0), (0, 0, 0), (0, 0, 3)], 270.0),  # faces -X, west
    ],
)
def test_newell_normal_gives_the_right_compass_bearing(vertices, expected):
    assert _azimuth_of([(float(x), float(y), float(z)) for x, y, z in vertices]) == pytest.approx(
        expected, abs=0.01
    )


def test_surfaces_without_vertices_are_skipped(tmp_path):
    model = tmp_path / "truncated.idf"
    model.write_text("BuildingSurface:Detailed, S1, Floor, C, ZONE-A;\n", encoding="utf-8")
    assert read_geometry(model).zones == ()


# --- against the real model -------------------------------------------------


@pytest.mark.skipif(not MODEL.is_file(), reason="run scripts/prepare_model.py first")
def test_real_model_is_a_core_plus_four_oriented_perimeter_zones():
    zones = tuple(controllable_zone_names(MODEL))
    geometry = read_geometry(MODEL, zones)

    cores = [z for z in geometry.zones if z.is_core]
    perimeter = [z for z in geometry.zones if not z.is_core]

    assert len(cores) == 1, "5ZoneAirCooled has exactly one core zone"
    assert len(perimeter) == 4
    assert {z.orientation for z in perimeter} == {"N", "E", "S", "W"}
    assert all(z.exterior_walls == 1 for z in perimeter)


@pytest.mark.skipif(not MODEL.is_file(), reason="run scripts/prepare_model.py first")
def test_real_model_footprints_tile_the_building_without_overlap():
    """Zone areas must sum to the building footprint, or the plan is wrong."""
    geometry = read_geometry(MODEL, tuple(controllable_zone_names(MODEL)))
    envelope = geometry.width_m * geometry.depth_m

    assert geometry.floor_area_m2 == pytest.approx(envelope, rel=0.01)


@pytest.mark.skipif(not MODEL.is_file(), reason="run scripts/prepare_model.py first")
def test_real_perimeter_zones_are_trapezoids_not_rectangles():
    """The donut layout has angled interior edges; rectangles would be a fiction."""
    geometry = read_geometry(MODEL, tuple(controllable_zone_names(MODEL)))
    south = next(z for z in geometry.zones if z.orientation == "S")

    edge_lengths = {
        round(math.dist(south.footprint[i], south.footprint[(i + 1) % 4]), 1)
        for i in range(4)
    }
    assert len(edge_lengths) > 2, "a rectangle would have at most two distinct edge lengths"

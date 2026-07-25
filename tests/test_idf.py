import pytest

from backend.simulation.idf import (
    controllable_zone_names,
    objects_of_type,
    parse_objects,
    zone_names,
)

SAMPLE_IDF = """\
! A trimmed sample in the real IDF style, comments and all.
Version,
    25.1;

Zone,
    SPACE1-1,                !- Name
    0,                       !- Direction of Relative North {deg}
    0, 0, 0;                 !- Origin

  Zone, SPACE2-1, 0, 0, 0, 0;

BuildingSurface:Detailed,
    WALL-1,                  !- Name
    Wall;                    !- Surface Type

zone,
    SPACE3-1,                !- lowercase object type is legal IDF
    0;
"""


def test_parses_object_types_and_fields():
    objects = parse_objects(SAMPLE_IDF)
    assert ("Version", ["25.1"]) in objects


def test_object_lookup_is_case_insensitive():
    assert len(objects_of_type(SAMPLE_IDF, "ZONE")) == 3


def test_comments_are_stripped_from_fields():
    fields = objects_of_type(SAMPLE_IDF, "BuildingSurface:Detailed")[0]
    assert fields == ["WALL-1", "Wall"]


def test_zone_names_preserve_file_order(tmp_path):
    model = tmp_path / "sample.idf"
    model.write_text(SAMPLE_IDF, encoding="utf-8")
    assert zone_names(model) == ["SPACE1-1", "SPACE2-1", "SPACE3-1"]


def test_model_without_zones_yields_empty_list(tmp_path):
    model = tmp_path / "empty.idf"
    model.write_text("Version, 25.1;\n", encoding="utf-8")
    assert zone_names(model) == []


# Mirrors the shape of 5ZoneAirCooled.idf: an unoccupied return-air plenum sits
# alongside the conditioned zones and must never be treated as controllable.
PLENUM_IDF = """\
Zone, PLENUM-1, 0, 0, 0;
Zone, SPACE1-1, 0, 0, 0;
Zone, SPACE2-1, 0, 0, 0;

ZoneControl:Thermostat,
    SPACE2-1 Control,        !- Name
    SPACE2-1,                !- Zone or ZoneList Name
    Zone Control Type Sched, !- Control Type Schedule Name
    ThermostatSetpoint:DualSetpoint,
    SPACE2-1 Setpoints;

ZoneControl:Thermostat,
    SPACE1-1 Control,
    space1-1,                !- zone references are case-insensitive in IDF
    Zone Control Type Sched,
    ThermostatSetpoint:DualSetpoint,
    SPACE1-1 Setpoints;
"""


@pytest.fixture
def plenum_model(tmp_path):
    model = tmp_path / "plenum.idf"
    model.write_text(PLENUM_IDF, encoding="utf-8")
    return model


def test_plenum_is_excluded_from_controllable_zones(plenum_model):
    assert controllable_zone_names(plenum_model) == ["SPACE1-1", "SPACE2-1"]
    assert "PLENUM-1" in zone_names(plenum_model)


def test_controllable_zones_follow_model_order_not_thermostat_order(plenum_model):
    """Thermostats are declared SPACE2-1 first; zone order must still win."""
    assert controllable_zone_names(plenum_model) == ["SPACE1-1", "SPACE2-1"]


def test_thermostat_targeting_a_zonelist_is_expanded(tmp_path):
    model = tmp_path / "zonelist.idf"
    model.write_text(
        """\
Zone, ATTIC, 0;
Zone, OFFICE-1, 0;
Zone, OFFICE-2, 0;
ZoneList, Occupied Zones, OFFICE-1, OFFICE-2;
ZoneControl:Thermostat,
    All Offices, Occupied Zones, Sched, ThermostatSetpoint:DualSetpoint, Setpoints;
""",
        encoding="utf-8",
    )
    assert controllable_zone_names(model) == ["OFFICE-1", "OFFICE-2"]


def test_no_thermostats_yields_no_controllable_zones(tmp_path):
    """Callers decide how to handle this; the parser must not invent zones."""
    model = tmp_path / "uncontrolled.idf"
    model.write_text("Zone, ONLY-ZONE, 0;\n", encoding="utf-8")
    assert controllable_zone_names(model) == []

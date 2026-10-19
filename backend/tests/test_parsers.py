import io
from datetime import date

from app.ingest import acled, gdelt, ucdp
from app.ingest.loader import collapse_duplicates
from tests.builders import acled_csv, acled_row, gdelt_row, gdelt_tsv, ucdp_csv, ucdp_row


def parse_ucdp(*rows):
    return list(ucdp.parse(io.StringIO(ucdp_csv(list(rows)))))


def parse_acled(*rows):
    return list(acled.parse(io.StringIO(acled_csv(list(rows)))))


def parse_gdelt(*rows):
    return list(gdelt.parse(io.StringIO(gdelt_tsv(list(rows)))))


def test_ucdp_valid_row_is_normalized():
    [row] = parse_ucdp(ucdp_row())
    event = row.event
    assert row.reasons == []
    assert event.source_event_id == "900001"
    assert event.event_date == date(2022, 3, 1)
    assert event.event_type == "state_based"
    assert event.is_violent
    assert event.geo_precision == "exact"
    assert event.country == "Testland"  # former name in parentheses stripped
    assert (event.fatalities_low, event.fatalities_best, event.fatalities_high) == (3, 5, 8)
    assert event.report_count == 3
    assert event.conflict_id == "11111"


def test_ucdp_collects_every_problem_in_a_row():
    [row] = parse_ucdp(ucdp_row(latitude="north", date_start="", type_of_violence="9"))
    assert row.event is None
    assert "invalid latitude: 'north'" in row.reasons
    assert "missing date_start" in row.reasons
    assert "unknown type_of_violence: 9" in row.reasons


def test_ucdp_rejects_out_of_range_and_inconsistent_values():
    rows = parse_ucdp(
        ucdp_row(latitude="123"),
        ucdp_row(longitude="0", latitude="0"),
        ucdp_row(best="10", low="3", high="8"),
        ucdp_row(date_start="2022-03-05", date_end="2022-03-01"),
        ucdp_row(where_prec="7"),
        ucdp_row(date_start="2999-01-01", date_end=""),
    )
    assert all(r.event is None for r in rows)
    assert "latitude out of range: 123.0" in rows[0].reasons
    assert any("0,0" in r for r in rows[1].reasons)
    assert any("low <= best <= high" in r for r in rows[2].reasons)
    assert any("before start date" in r for r in rows[3].reasons)
    assert any("where_prec 7" in r for r in rows[4].reasons)
    assert any("future" in r for r in rows[5].reasons)


def test_ucdp_country_level_precision():
    [row] = parse_ucdp(ucdp_row(where_prec="6"))
    assert row.event.geo_precision == "country"


def test_ucdp_file_without_required_columns_is_refused():
    try:
        list(ucdp.parse(io.StringIO("a,b\n1,2\n")))
    except ValueError as exc:
        assert "missing columns" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_gdelt_all_layouts_parse():
    for layout in (57, 58, 61):
        [row] = parse_gdelt(gdelt_row(layout))
        assert row.event is not None, (layout, row.reasons)
        assert row.event.event_type == "fight"
        assert row.event.is_violent
        assert row.event.country == "Testland"
        assert row.event.geo_precision == "exact"


def test_gdelt_filters_cooperation_and_keeps_signals():
    consult, protest = parse_gdelt(
        gdelt_row(EventRootCode="04", EventCode="040"),
        gdelt_row(EventRootCode="14", EventCode="141"),
    )
    assert consult.filtered_out and consult.event is None and consult.reasons == []
    assert protest.event.event_type == "protest"
    assert not protest.event.is_violent


def test_gdelt_rejects_rows_without_location_or_wrong_width():
    no_geo, wrong_width = parse_gdelt(
        gdelt_row(ActionGeo_Type="0", ActionGeo_Lat="", ActionGeo_Long=""),
        ["1", "2", "3"],
    )
    assert any("no action location" in r for r in no_geo.reasons)
    assert any("unexpected column count 3" in r for r in wrong_width.reasons)


def test_gdelt_rows_about_the_same_incident_collapse():
    rows = parse_gdelt(
        gdelt_row(GLOBALEVENTID="1", NumMentions="2"),
        gdelt_row(GLOBALEVENTID="2", NumMentions="9"),
        gdelt_row(GLOBALEVENTID="3", EventCode="193"),
    )
    kept, merged = collapse_duplicates([r.event for r in rows])
    assert merged == 1
    assert [e.source_event_id for e in kept] == ["1", "3"]
    assert kept[0].report_count == 9


def test_acled_valid_row_is_normalized():
    [row] = parse_acled(acled_row())
    event = row.event
    assert row.reasons == []
    assert event.source_event_id == event.dedupe_key == "TST100"
    assert event.event_date == date(2022, 3, 1)
    assert event.event_type == "battle"
    assert event.is_violent
    assert event.geo_precision == "exact"
    assert event.fatalities_best == 4
    assert event.fatalities_low is None and event.fatalities_high is None
    assert event.report_count == 2  # two outlets in `source`
    assert event.attributes["sub_event_type"] == "Armed clash"
    assert event.attributes["notes"].startswith("On 1 March 2022")


def test_acled_protests_riots_and_strategic_developments_are_signals():
    rows = parse_acled(
        acled_row(event_type="Protests", sub_event_type="Peaceful protest", fatalities="0"),
        acled_row(event_type="Riots", sub_event_type="Mob violence", fatalities="1"),
        acled_row(event_type="Strategic developments", sub_event_type="Arrests"),
        acled_row(event_type="Violence against civilians", sub_event_type="Attack"),
    )
    assert [r.event.event_type for r in rows] == [
        "protest",
        "riot",
        "strategic_development",
        "violence_against_civilians",
    ]
    assert [r.event.is_violent for r in rows] == [False, False, False, True]


def test_acled_export_tool_dates_and_regional_precision():
    [row] = parse_acled(acled_row(event_date="01 March 2022", geo_precision="3"))
    assert row.event.event_date == date(2022, 3, 1)
    assert row.event.geo_precision == "admin"


def test_acled_rejects_bad_rows():
    rows = parse_acled(
        acled_row(event_type="Parades"),
        acled_row(geo_precision="5", fatalities="-2"),
        acled_row(latitude="", event_date="sometime"),
    )
    assert all(r.event is None for r in rows)
    assert "unknown event_type: 'Parades'" in rows[0].reasons
    assert "unknown geo_precision: 5" in rows[1].reasons
    assert "missing latitude" in rows[2].reasons
    assert "invalid event_date: 'sometime'" in rows[2].reasons
    [negative] = parse_acled(acled_row(fatalities="-2"))
    assert "negative fatality count" in negative.reasons


def test_acled_file_without_required_columns_is_refused():
    try:
        list(acled.parse(io.StringIO("event_id_cnty,country\nX1,Testland\n")))
    except ValueError as exc:
        assert "missing columns" in str(exc)
    else:
        raise AssertionError("expected ValueError")

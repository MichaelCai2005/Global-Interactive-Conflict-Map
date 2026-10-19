import csv
import io

import pytest
from sqlalchemy import select

from app import countries
from app.ingest import epr, vdem, wdi
from app.ingest.loader import ingest_file
from app.models import CountryIndicator


def to_csv(columns: list[str], rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


WDI_COLUMNS = ["indicator", "countryiso3code", "date", "value"]
EPR_COLUMNS = ["gwid", "statename", "from", "to", "group", "groupid", "size", "status"]
VDEM_COLUMNS = [
    "country_name",
    "country_text_id",
    "country_id",
    "year",
    "v2x_polyarchy",
    "v2x_regime",
]


def epr_row(**overrides) -> dict:
    row = {"gwid": "500", "statename": "Uganda", "from": "2019", "to": "2020", "group": "A",
           "groupid": "1", "size": "0.6", "status": "DOMINANT"}  # fmt: skip
    row.update(overrides)
    return row


def parse(module, columns, rows):
    return list(module.parse(io.StringIO(to_csv(columns, rows))))


def values(rows) -> dict[tuple[str, str, int], float]:
    return {(v.indicator, v.iso3, v.year): v.value for r in rows for v in r.values}


@pytest.mark.parametrize(
    ("lookup", "code", "iso3"),
    [
        (countries.from_gw, "678", "YEM"),  # UCDP's code for unified Yemen
        (countries.from_gw, "345", "SRB"),
        (countries.from_gw, "347", "XKX"),
        (countries.from_gw, "265", None),  # East Germany has no successor code
        (countries.from_iso_numeric, "4", "AFG"),
        (countries.from_iso_numeric, "004", "AFG"),
        (countries.from_iso_numeric, "804.0", "UKR"),
        (countries.from_fips, "UP", "UKR"),  # FIPS, not ISO: UP is Ukraine
        (countries.from_fips, "RB", "SRB"),
        (countries.from_fips, "OS", None),  # oceans
        (countries.from_vdem, "11", "RUS"),
    ],
)
def test_country_codes_map_to_iso3(lookup, code, iso3):
    assert lookup(code) == iso3


def test_wdi_keeps_countries_and_skips_aggregates_and_gaps():
    rows = parse(
        wdi,
        WDI_COLUMNS,
        [
            {
                "indicator": "SP.DYN.IMRT.IN",
                "countryiso3code": "NGA",
                "date": "2020",
                "value": "71.2",
            },
            {
                "indicator": "SP.DYN.IMRT.IN",
                "countryiso3code": "AFE",
                "date": "2020",
                "value": "42",
            },
            {"indicator": "SP.DYN.IMRT.IN", "countryiso3code": "NGA", "date": "2021", "value": ""},
            {"indicator": "SP.DYN.IMRT.IN", "countryiso3code": "NGA", "date": "20x1", "value": "1"},
        ],
    )
    assert values(rows) == {("SP.DYN.IMRT.IN", "NGA", 2020): 71.2}
    assert [r.filtered_out for r in rows] == [False, True, True, False]
    assert "invalid date: '20x1'" in rows[3].reasons


def test_vdem_reads_each_index_and_drops_historical_states():
    rows = parse(
        vdem,
        VDEM_COLUMNS,
        [
            {"country_text_id": "RUS", "country_id": "11", "year": "2020",
             "v2x_polyarchy": "0.26", "v2x_regime": "1"},
            {"country_text_id": "UKR", "country_id": "999", "year": "2020",
             "v2x_polyarchy": "0.48", "v2x_regime": "NA"},
            {"country_text_id": "BAD", "country_id": "349", "year": "1860",
             "v2x_polyarchy": "0.1", "v2x_regime": "0"},
            {"country_text_id": "RUS", "country_id": "11", "year": "2021",
             "v2x_polyarchy": "high", "v2x_regime": "1"},
        ],
    )  # fmt: skip
    assert values(rows) == {
        ("v2x_polyarchy", "RUS", 2020): 0.26,
        ("v2x_regime", "RUS", 2020): 1.0,
        ("v2x_polyarchy", "UKR", 2020): 0.48,  # unknown id falls back to the text id
    }
    assert rows[2].filtered_out
    assert rows[3].reasons == ["invalid v2x_polyarchy: 'high'"]


def test_vdem_file_without_indicators_is_refused():
    with pytest.raises(ValueError, match="none of the indicators"):
        parse(vdem, ["country_text_id", "country_id", "year"], [])


def test_epr_turns_group_periods_into_country_year_totals():
    rows = parse(
        epr,
        EPR_COLUMNS,
        [
            epr_row(),
            epr_row(group="B", size="0.3", status="DISCRIMINATED"),
            epr_row(group="C", size="0.1", status="POWERLESS", **{"from": "2020"}),
            epr_row(group="D", size="0.2", status="ROYALTY"),
            epr_row(gwid="265", statename="German Democratic Republic"),
        ],
    )
    got = values(rows)
    assert got[("excluded_pop_share", "UGA", 2019)] == 0.3
    assert got[("excluded_pop_share", "UGA", 2020)] == 0.4
    assert got[("discriminated_pop_share", "UGA", 2020)] == 0.3
    assert got[("excluded_groups", "UGA", 2020)] == 2
    assert got[("groups_in_power", "UGA", 2020)] == 1
    assert rows[3].reasons == ["unknown status: 'ROYALTY'"]
    assert rows[4].filtered_out


def test_epr_keeps_the_primary_code_when_a_state_is_renumbered():
    # Yugoslavia (345) ends and Serbia (340) starts in 2006; both cover that year.
    rows = parse(
        epr,
        EPR_COLUMNS,
        [
            epr_row(gwid="345", **{"from": "2005", "to": "2006"}, size="0.2", status="POWERLESS"),
            epr_row(gwid="340", **{"from": "2006", "to": "2007"}, size="0.1", status="POWERLESS"),
        ],
    )
    got = values(rows)
    assert got[("excluded_pop_share", "SRB", 2005)] == 0.2
    assert got[("excluded_pop_share", "SRB", 2006)] == 0.1
    assert sum(1 for r in rows for v in r.values if v.year == 2006) == len(epr.INDICATORS)


def test_indicator_load_counts_rows_and_reloads_cleanly(session, tmp_path):
    path = tmp_path / "wdi.csv"
    path.write_text(
        to_csv(
            WDI_COLUMNS,
            [
                {
                    "indicator": "SP.POP.TOTL",
                    "countryiso3code": "UKR",
                    "date": "2021",
                    "value": "43",
                },
                {
                    "indicator": "SP.POP.TOTL",
                    "countryiso3code": "WLD",
                    "date": "2021",
                    "value": "7",
                },
                {"indicator": "SP.POP.TOTL", "countryiso3code": "UKR", "date": "x", "value": "1"},
            ],
        )
    )
    first = ingest_file(session, "wdi", path)
    assert first.status == "succeeded", first.error
    assert (first.rows_read, first.inserted, first.filtered_out, first.rejected) == (3, 1, 1, 1)

    path.write_text(
        to_csv(
            WDI_COLUMNS,
            [{"indicator": "SP.POP.TOTL", "countryiso3code": "UKR", "date": "2021", "value": "41"}],
        )
    )
    second = ingest_file(session, "wdi", path)
    assert (second.inserted, second.updated) == (0, 1)
    assert session.scalar(select(CountryIndicator.value)) == 41

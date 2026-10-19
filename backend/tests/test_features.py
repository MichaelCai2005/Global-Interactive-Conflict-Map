from datetime import date

from sqlalchemy import select

from app.features import build_cell_months, cell_centre
from app.ingest.loader import ingest_file
from app.models import CellMonth, CountryIndicator, Event, IngestRun
from tests.builders import gdelt_row, gdelt_tsv, ucdp_csv, ucdp_row

# Testville (49.99, 36.23) is PRIO-GRID cell 201313; one cell east is 201314.
CELL = 201313


def load_ucdp(session, tmp_path, rows):
    path = tmp_path / "ged.csv"
    path.write_text(ucdp_csv(rows))
    run = ingest_file(session, "ucdp", path)
    assert run.status == "succeeded", run.error


def features(session) -> dict[tuple[int, date], CellMonth]:
    return {(c.gid, c.month): c for c in session.scalars(select(CellMonth))}


def test_events_get_a_grid_cell_and_country_code(session, tmp_path):
    load_ucdp(
        session,
        tmp_path,
        [ucdp_row(country_id="369"), ucdp_row(id="2", where_prec="6", country_id="369")],
    )
    exact, whole_country = session.scalars(select(Event).order_by(Event.id)).all()
    assert (exact.priogrid_gid, exact.country_iso3) == (CELL, "UKR")
    assert whole_country.priogrid_gid is None
    assert cell_centre(CELL) == (49.75, 36.25)


def test_history_looks_only_at_earlier_months(session, tmp_path):
    load_ucdp(
        session,
        tmp_path,
        [
            ucdp_row(id="1", date_start="2021-11-10", date_end="2021-11-10", best="4", low="4", high="4"),
            ucdp_row(id="2", date_start="2022-01-05", date_end="2022-01-05", best="10", low="9", high="12"),
            ucdp_row(id="3", date_start="2022-03-01", date_end="2022-03-01", best="5"),
            # Next door, a cell to the east.
            ucdp_row(id="4", longitude="36.73", date_start="2022-02-01", date_end="2022-02-01", best="7", low="7", high="7"),
        ],
    )  # fmt: skip
    built = build_cell_months(session, date(2022, 1, 1), date(2022, 3, 1))

    rows = features(session)
    assert built == len(rows) == 6  # two cells x three months
    jan, feb, mar = (rows[CELL, date(2022, m, 1)] for m in (1, 2, 3))
    assert (jan.ucdp_events, jan.ucdp_fatalities) == (1, 10)
    assert (jan.ucdp_fatalities_last1m, jan.ucdp_fatalities_last3m) == (0, 4)
    assert jan.months_since_violence == 2
    assert (feb.ucdp_fatalities, feb.ucdp_fatalities_last1m, feb.months_since_violence) == (
        0,
        10,
        1,
    )
    assert feb.neighbour_fatalities_last1m == 0
    assert (mar.ucdp_fatalities, mar.ucdp_fatalities_last3m) == (5, 10)
    assert mar.ucdp_fatalities_last12m == mar.ucdp_fatalities_last36m == 14
    assert (mar.neighbour_fatalities_last1m, mar.neighbour_fatalities_last12m) == (7, 7)
    assert mar.months_since_violence == 2
    assert rows[CELL + 1, date(2022, 1, 1)].months_since_violence is None


def test_rebuilding_replaces_the_months_and_counts_news_signals(session, tmp_path):
    load_ucdp(session, tmp_path, [ucdp_row(country_id="369")])
    path = tmp_path / "g.CSV"
    path.write_text(
        gdelt_tsv(
            [
                gdelt_row(
                    GLOBALEVENTID="1",
                    EventRootCode="14",
                    EventCode="141",
                    NumMentions="3",
                    AvgTone="-2",
                    ActionGeo_CountryCode="UP",
                ),
                gdelt_row(
                    GLOBALEVENTID="2",
                    EventRootCode="13",
                    EventCode="130",
                    NumMentions="1",
                    AvgTone="-6",
                    ActionGeo_Lat="49.9",
                    ActionGeo_CountryCode="UP",
                ),
            ]
        )  # fmt: skip
    )
    assert ingest_file(session, "gdelt", path).status == "succeeded"

    build_cell_months(session, date(2022, 3, 1), date(2022, 3, 1))
    build_cell_months(session, date(2022, 3, 1), date(2022, 3, 1))
    [march] = features(session).values()
    assert (march.gdelt_protests, march.gdelt_threats, march.gdelt_mentions) == (1, 1, 4)
    assert march.gdelt_tone == -3.0  # (3 * -2 + 1 * -6) / 4
    assert march.iso3 == "UKR"


def test_cell_api_attaches_last_years_indicators(client, session, tmp_path):
    load_ucdp(session, tmp_path, [ucdp_row(country_id="369")])
    build_cell_months(session, date(2022, 3, 1), date(2022, 3, 1))
    run = IngestRun(source="wdi", filename="t.csv")
    session.add(run)
    session.flush()
    session.add_all(
        CountryIndicator(
            source="wdi", indicator="SP.POP.TOTL", iso3="UKR", year=year, value=value,
            ingest_run_id=run.id,
        )
        for year, value in [(2020, 44.0), (2021, 43.0), (2022, 38.0)]
    )  # fmt: skip
    session.commit()

    body = client.get("/features/cells", params={"month": "2022-03"}).json()
    [cell] = body["items"]
    assert (body["total"], cell["gid"], cell["ucdp_fatalities"]) == (1, CELL, 5)
    assert (cell["latitude"], cell["longitude"]) == (49.75, 36.25)
    # 2022's value would be look-ahead for a March 2022 forecast.
    assert cell["indicators"] == {"wdi.SP.POP.TOTL": {"value": 43.0, "year": 2021}}

    outside = client.get("/features/cells", params={"month": "2022-03", "bbox": "0,0,10,10"})
    assert outside.json()["total"] == 0
    assert (
        client.get("/features/cells", params={"month": "2022-03", "bbox": "1,2"}).status_code == 422
    )

    series = client.get("/indicators", params={"iso3": "ukr", "start_year": 2021}).json()
    assert [(r["year"], r["value"]) for r in series] == [(2021, 43.0), (2022, 38.0)]
    [info] = client.get("/indicators/catalog").json()
    assert (info["first_year"], info["last_year"], info["countries"]) == (2020, 2022, 1)
    assert info["description"] == "Population, total"

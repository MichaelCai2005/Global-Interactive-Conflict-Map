from sqlalchemy import update

from app.models import Event
from tests.test_ingest import load_sample


def test_map_returns_points_when_few_enough(client, session, tmp_path):
    load_sample(session, tmp_path)
    layer = client.get("/map").json()
    assert (layer["mode"], layer["total"], layer["cell_size"]) == ("points", 4, None)

    features = layer["features"]["features"]
    assert [f["properties"]["date"] for f in features] == sorted(
        f["properties"]["date"] for f in features
    )
    protest = next(f for f in features if f["properties"]["type"] == "protest")
    assert protest["properties"]["violent"] is False
    assert protest["properties"]["day"] == 19043  # 2022-02-20
    ucdp = next(f for f in features if f["properties"]["source"] == "ucdp")
    assert ucdp["geometry"]["type"] == "Point"
    assert set(ucdp["properties"]) == {
        "id", "date", "day", "type", "violent", "deaths", "source", "precision",
    }  # fmt: skip


def test_map_switches_to_grid_cells_above_the_limit(client, session, tmp_path):
    load_sample(session, tmp_path)
    layer = client.get("/map", params={"max_points": 2, "cell": 5}).json()
    assert (layer["mode"], layer["total"], layer["cell_size"]) == ("grid", 4, 5.0)

    cells = sorted(
        (f["properties"] for f in layer["features"]["features"]), key=lambda c: -c["events"]
    )
    assert sum(c["events"] for c in cells) == 4
    # 900001 (49.99N 36.23E) and the protest share a 5 degree cell; 900002 (48.5N 31.2E)
    # and the fight at 10N 10E each have their own.
    assert [(c["events"], c["violent"], c["signals"]) for c in cells] == [
        (2, 1, 1),
        (1, 1, 0),
        (1, 1, 0),
    ]


def test_map_applies_event_filters(client, session, tmp_path):
    load_sample(session, tmp_path)
    layer = client.get("/map", params={"violent": False}).json()
    assert [f["properties"]["type"] for f in layer["features"]["features"]] == ["protest"]
    assert client.get("/map", params={"cell": 0}).status_code == 422


def test_summary_totals_follow_the_filters(client, session, tmp_path):
    load_sample(session, tmp_path)
    assert client.get("/summary").json() == {
        "violent_events": 3,
        "signal_events": 1,
        "fatalities": 10,
    }
    assert client.get("/summary", params={"end": "2022-02-28"}).json() == {
        "violent_events": 0,
        "signal_events": 1,
        "fatalities": 0,
    }


def test_facets_describe_the_data(client, session, tmp_path):
    load_sample(session, tmp_path)
    facets = client.get("/facets").json()
    assert [(s["value"], s["count"]) for s in facets["sources"]] == [("gdelt", 2), ("ucdp", 2)]
    # Each source's own date range, so the map can say how current each one is.
    assert {s["value"]: (s["first_date"], s["last_date"]) for s in facets["sources"]} == {
        "gdelt": ("2022-02-20", "2022-03-01"),
        "ucdp": ("2022-03-01", "2022-03-01"),
    }
    assert {(t["value"], t["is_violent"]) for t in facets["event_types"]} == {
        ("state_based", True),
        ("protest", False),
        ("fight", True),
    }
    assert (facets["first_date"], facets["last_date"]) == ("2022-02-20", "2022-03-01")


def test_countries_rank_busiest_first_with_a_bbox(client, session, tmp_path):
    load_sample(session, tmp_path)
    [testland] = client.get("/countries").json()
    assert testland["country"] == "Testland"
    assert (testland["violent_events"], testland["signal_events"]) == (3, 1)
    min_lon, min_lat, max_lon, max_lat = testland["bbox"]
    assert 10 < min_lon < max_lon < 36.3 and 10 < min_lat < max_lat < 50

    only_signals = client.get("/countries", params={"violent": False}).json()
    assert [(c["country"], c["signal_events"]) for c in only_signals] == [("Testland", 1)]


def test_events_can_be_sorted_by_fatalities(client, session, tmp_path):
    load_sample(session, tmp_path)
    items = client.get("/events", params={"sort": "fatalities"}).json()["items"]
    deaths = [e["fatalities_best"] for e in items if e["fatalities_best"] is not None]
    assert deaths == sorted(deaths, reverse=True)
    assert items[-1]["fatalities_best"] is None


def test_events_can_be_sorted_by_reports(client, session, tmp_path):
    load_sample(session, tmp_path)
    items = client.get("/events", params={"sort": "reports"}).json()["items"]
    reports = [e["report_count"] for e in items]
    assert reports == sorted(reports, reverse=True)


def test_events_accept_several_sources(client, session, tmp_path):
    load_sample(session, tmp_path)
    total = client.get("/events", params={"source": ["ucdp", "gdelt"]}).json()["total"]
    assert total == 4


def test_gdelt_violence_datelined_in_washington_is_hidden(client, session, tmp_path):
    load_sample(session, tmp_path)
    session.execute(update(Event).where(Event.source == "gdelt").values(admin1="USDC"))
    session.flush()
    # The GDELT fight at 10N 10E goes; the GDELT protest and UCDP's events stay.
    assert client.get("/summary").json() == {
        "violent_events": 2,
        "signal_events": 1,
        "fatalities": 10,
    }
    sources = {e["source"] for e in client.get("/events", params={"violent": True}).json()["items"]}
    assert sources == {"ucdp"}

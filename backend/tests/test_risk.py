from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app import risk
from app.models import Event, IngestRun
from app.risk import (
    CountryWeeks,
    death_level,
    neighbours_from_cells,
    score_countries,
    trend_label,
)


@pytest.fixture(autouse=True)
def hand_set_weights(monkeypatch):
    """These tests check how the score is built, so they pin the weights rather than
    follow whatever `python -m app.risk_model fit` last wrote."""
    monkeypatch.setattr(risk, "WEIGHTS", dict(risk.HAND_SET_WEIGHTS))


START = date(2021, 1, 4)  # a Monday
N_WEEKS = 80
WEEKS = [START + timedelta(weeks=i) for i in range(N_WEEKS)]


def weeks_of(
    violent=None, acled=None, deaths=None, gdelt=None, goldstein=None, tone=None
) -> CountryWeeks:
    """Weekly inputs from {week number: value} maps; `violent` is UCDP events."""

    def series(values, default):
        out = [default] * N_WEEKS
        for w, v in (values or {}).items():
            out[w] = v
        return out

    return CountryWeeks(
        violent={"ucdp": series(violent, 0), "acled": series(acled, 0)},
        deaths=series(deaths, 0),
        gdelt_events=series(gdelt, 0),
        goldstein=series(goldstein, None),
        tone=series(tone, None),
    )


def test_deaths_score_on_a_log_scale():
    assert death_level(0) == 0
    assert death_level(100) == pytest.approx(0.5, abs=0.01)
    assert death_level(10_000) == pytest.approx(1)
    assert death_level(1_000_000) == 1


@pytest.mark.parametrize(
    ("scores", "label"),
    [
        ([10, 12, 15, 20, 25, 30, 34, 38, 41, 44, 47, 49], "intensifying"),
        ([49, 47, 44, 41, 38, 34, 30, 25, 20, 15, 12, 10], "diminishing"),
        ([10] * 11 + [70], "new"),
        ([80, 82, 79, 81, 80, 83, 78, 80, 81, 79, 80, 82], "persistent"),
        # A slow decay is a significant trend but too small to report.
        ([30, 29.5, 29, 28.5, 28, 27.5, 27, 26.5, 26, 25.5, 25, 24.5], None),
    ],
)
def test_trend_label(scores, label):
    assert trend_label(scores) == label


def test_neighbours_are_countries_with_events_a_few_cells_apart():
    def gid(row, col):
        return row * 720 + col + 1

    near = neighbours_from_cells(
        [
            ("AAA", gid(100, 100)),
            ("BBB", gid(102, 103)),
            ("CCC", gid(100, 120)),
            # Either side of the antimeridian.
            ("DDD", gid(50, 719)),
            ("EEE", gid(50, 1)),
        ]
    )
    assert near["AAA"] == {"BBB"}
    assert near["BBB"] == {"AAA"}
    assert "CCC" not in near
    assert near["DDD"] == {"EEE"}


def scored(data, neighbours=None, provisional_after=None):
    rows = score_countries(WEEKS, data, neighbours or {}, provisional_after)
    return {(r.iso3, r.week): r for r in rows}


def test_a_quiet_country_that_flares_surges_and_alarms():
    flare = {w: 12 for w in range(60, 64)}
    rows = scored(
        {
            "FLR": weeks_of(violent=flare, deaths=dict.fromkeys(flare, 20)),
            "QUI": weeks_of(),
            "OTH": weeks_of(violent=dict.fromkeys(range(N_WEEKS), 1)),
        }
    )
    before, during = rows[("FLR", WEEKS[59])], rows[("FLR", WEEKS[61])]
    assert before.score == 0
    assert during.surge_z > 2
    assert during.surge_alarm
    assert during.points["surge"] > 0 and during.points["history"] > 0
    assert rows[("QUI", WEEKS[61])].score == 0
    # A steady low level is not a surge.
    assert rows[("OTH", WEEKS[61])].surge == 0
    # The capped surge drains away after a few months of calm.
    assert rows[("FLR", WEEKS[63 + 16])].surge == 0


def test_a_source_starting_coverage_is_not_a_surge():
    steady = dict.fromkeys(range(N_WEEKS), 2)
    # ACLED is loaded from week 40 on and records far more events than UCDP.
    rows = scored(
        {
            "AAA": weeks_of(violent=steady, acled=dict.fromkeys(range(40, N_WEEKS), 30)),
            "BBB": weeks_of(violent=steady, acled=dict.fromkeys(range(40, N_WEEKS), 1)),
        }
    )
    for w in range(40, N_WEEKS):
        assert rows[("AAA", WEEKS[w])].surge == 0
    # ACLED gets a baseline once 26 of its own weeks fall in the window (weeks 40-65).
    covered = [w >= 40 for w in range(N_WEEKS)]
    acled = risk.surge_by_source([30 if w >= 40 else 0 for w in range(N_WEEKS)], covered)
    assert acled[69] is None
    assert acled[70] == pytest.approx((0, 30))


def test_components_without_data_that_week_are_left_out():
    rows = scored({"WAR": weeks_of(deaths={10: 50}), "OTH": weeks_of()})
    war = rows[("WAR", WEEKS[10])]
    # Only History is available (no surge baseline, no neighbours, no GDELT).
    assert war.points["history"] == pytest.approx(100 * war.level["history"])
    assert war.score == war.points["history"]


def test_history_decays_with_a_26_week_half_life():
    rows = scored({"WAR": weeks_of(deaths={10: 1000}), "QUI": weeks_of()})
    assert rows[("WAR", WEEKS[10])].history == pytest.approx(1000)
    assert rows[("WAR", WEEKS[36])].history == pytest.approx(500)


def test_spread_comes_from_neighbours_and_score_is_the_sum_of_points():
    war = dict.fromkeys(range(N_WEEKS), 100)
    rows = scored(
        {"WAR": weeks_of(deaths=war), "NXT": weeks_of(), "FAR": weeks_of()},
        neighbours={"WAR": {"NXT"}, "NXT": {"WAR"}},
    )
    nxt, far = rows[("NXT", WEEKS[70])], rows[("FAR", WEEKS[70])]
    assert nxt.spread > 0 and far.spread == 0
    assert nxt.score == pytest.approx(sum(nxt.points.values()))
    assert 0 < nxt.score <= 100


def test_news_signal_rises_when_coverage_jumps_and_turns_hostile():
    gdelt = dict.fromkeys(range(N_WEEKS), 10)
    gdelt[70] = 60
    gold = {w: -4.0 + (w % 3) * 0.3 for w in range(N_WEEKS)}
    gold[70] = -9.0
    rows = scored(
        {
            "NWS": weeks_of(gdelt=gdelt, goldstein=gold),
            "OTH": weeks_of(gdelt=dict.fromkeys(range(N_WEEKS), 10)),
        }
    )
    hot = rows[("NWS", WEEKS[70])]
    assert hot.share_z > 2 and hot.goldstein_z < -2
    assert hot.points["signal"] > 0


def test_weeks_after_the_last_hand_coded_event_are_provisional():
    rows = scored({"AAA": weeks_of()}, provisional_after=WEEKS[50])
    assert not rows[("AAA", WEEKS[50])].provisional
    assert rows[("AAA", WEEKS[51])].provisional


def add_event(session, run, n, **fields):
    defaults = dict(
        source="ucdp",
        source_event_id=str(n),
        dedupe_key=str(n),
        event_type="state_based",
        is_violent=True,
        country="Testland",
        country_iso3="UKR",
        latitude=49.99,
        longitude=36.23,
        geo_precision="exact",
        report_count=1,
        attributes={},
        ingest_run_id=run.id,
    )
    session.add(Event(**(defaults | fields)))


@pytest.fixture
def scored_db(session):
    run = IngestRun(source="ucdp", filename="test")
    session.add(run)
    session.flush()
    n = 0
    # A low-level conflict for a year, then a sharp escalation in week 60.
    for w in range(N_WEEKS):
        for _ in range(12 if 60 <= w < 63 else 1):
            n += 1
            deaths = 40 if w >= 60 else 1
            add_event(session, run, n, event_date=WEEKS[w], fatalities_best=deaths)
    # A neighbour with a single event, so it has a score row and a border.
    n += 1
    add_event(
        session,
        run,
        n,
        event_date=WEEKS[5],
        fatalities_best=1,
        country="Otherland",
        country_iso3="RUS",
        latitude=50.6,
        longitude=36.6,
    )
    session.commit()
    assert risk.build(session) == 2 * N_WEEKS
    return session


def test_risk_endpoints_explain_the_escalation(client, scored_db):
    week = client.get("/risk", params={"week": str(WEEKS[60] + timedelta(days=3))}).json()
    assert week["week"] == str(WEEKS[60])
    assert week["previous_week"] == str(WEEKS[59])
    ukr = next(r for r in week["regions"] if r["iso3"] == "UKR")
    assert ukr["name"] == "Ukraine"
    assert ukr["change"] > 0
    assert ukr["score"] == pytest.approx(sum(ukr["points"].values()))
    assert week["weights"] == risk.HAND_SET_WEIGHTS
    assert week["weights_fitted"] is False

    risers = client.get("/risk", params={"week": str(WEEKS[60]), "sort": "rise"}).json()
    assert risers["regions"][0]["iso3"] == "UKR"

    series = client.get("/risk/ukr", params={"start": str(WEEKS[58])}).json()
    assert series["neighbours"] == ["RUS"]
    assert [p["week"] for p in series["points"]][:3] == [str(w) for w in WEEKS[58:61]]
    assert series["points"][0]["change"] is not None

    why = client.get(f"/risk/UKR/weeks/{WEEKS[60]}").json()
    assert why["change"] > 0
    assert why["components"][0]["component"] == "surge"
    assert "Surge rose most" in why["summary"]
    assert (
        "12 UCDP violent events against a usual 1.0 a week" in why["components"][0]["explanation"]
    )
    assert len(why["events"]) == 8
    assert why["events"][0]["fatalities_best"] == 40
    assert why["neighbours"][0]["iso3"] == "RUS"


def test_risk_lists_leave_out_what_shows_as_zero(client, scored_db):
    # A death long ago decays to a few billionths of a point but never to zero.
    scored_db.execute(text("UPDATE risk_scores SET score = 1e-9 WHERE iso3 = 'RUS'"))
    scored_db.commit()

    def regions(w, sort):
        return client.get("/risk", params={"week": str(WEEKS[w]), "sort": sort}).json()["regions"]

    for sort in ("score", "rise", "fall"):
        assert "RUS" not in [r["iso3"] for r in regions(70, sort)]

    # Rising lists only countries that rose, falling only those that fell.
    assert regions(60, "fall") == []
    assert regions(70, "rise") == []
    falling = regions(70, "fall")
    assert [r["iso3"] for r in falling] == ["UKR"]
    assert falling[0]["change"] <= -0.5


def test_risk_week_is_clamped_to_the_scored_range(client, scored_db):
    assert client.get("/risk", params={"week": "1990-01-01"}).json()["week"] == str(WEEKS[0])
    assert client.get("/risk").json()["week"] == str(WEEKS[-1])
    assert client.get("/risk/XXX").status_code == 404
    assert client.get("/risk/UKR/weeks/1990-01-01").status_code == 404


def test_risk_without_scores_says_how_to_build_them(client):
    response = client.get("/risk")
    assert response.status_code == 404
    assert "app.risk build" in response.json()["detail"]

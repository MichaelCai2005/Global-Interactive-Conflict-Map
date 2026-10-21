from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app.live import feeds

ADSB = {
    "now": 1792500313002,  # 2026-10-20 12:45:13 UTC
    "ac": [
        {
            "hex": "AE5F11",
            "flight": "KING54  ",
            "r": "14-5864",
            "t": "C30J",
            "alt_baro": 18025,
            "gs": 285.7,
            "track": 196.5,
            "lat": 36.28775,
            "lon": -122.3639,
            "seen_pos": 3.0,
        },
        {
            "hex": "abf0fd",
            "flight": "JANET24 ",
            "t": "B736",
            "alt_baro": "ground",
            "lat": 36.09,
            "lon": -115.17,
            "seen_pos": 6.2,
        },
        {"hex": "nopos", "flight": "GHOST1"},
        {"hex": "stale", "lat": 1.0, "lon": 1.0, "seen_pos": 600},
    ],
}

FIRMS_CSV = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
47.1234,37.5432,330.1,0.4,0.4,2026-10-15,0042,N,VIIRS,n,2.0NRT,290.2,5.3,N
47.2,37.6,345.9,0.4,0.4,2026-10-15,1105,N,VIIRS,h,2.0NRT,300.1,18.9,D
bad,row,,,,2026-10-15,1105,N,VIIRS,h,2.0NRT,,,D
"""


def test_parse_adsb_positions():
    rows = feeds.parse_adsb(ADSB)
    assert [r["external_id"] for r in rows] == ["ae5f11", "abf0fd"]
    king = rows[0]
    assert king["observed_at"] == datetime(2026, 10, 20, 12, 45, 10, tzinfo=UTC)
    assert king["label"] == "KING54 · C30J"
    assert king["attributes"]["altitude_ft"] == 18025
    assert rows[1]["attributes"]["on_ground"] is True


def test_parse_adsb_needs_a_time():
    with pytest.raises(feeds.FeedError):
        feeds.parse_adsb({"ac": []})


def test_parse_firms():
    rows = feeds.parse_firms(FIRMS_CSV, "VIIRS_SNPP_NRT")
    assert len(rows) == 2
    assert rows[0]["observed_at"] == datetime(2026, 10, 15, 0, 42, tzinfo=UTC)
    assert rows[1]["attributes"]["frp"] == "18.9"
    assert rows[0]["kind"] == "fire" and rows[0]["source"] == "firms:viirs_snpp_nrt"


def test_parse_firms_reports_key_problems():
    with pytest.raises(feeds.FeedError, match="Invalid MAP_KEY"):
        feeds.parse_firms("Invalid MAP_KEY.", "VIIRS_SNPP_NRT")


def test_store_skips_repeats(session):
    rows = feeds.parse_adsb(ADSB)
    assert feeds.store(session, rows) == 2
    assert feeds.store(session, rows) == 0
    count = session.scalar(text("SELECT count(*) FROM observations"))
    assert count == 2


def test_truncated_response_is_a_feed_error(monkeypatch):
    import http.client

    class Cut:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            raise http.client.IncompleteRead(b"{", 100)

    monkeypatch.setattr(feeds.urllib.request, "urlopen", lambda request, timeout: Cut())
    with pytest.raises(feeds.FeedError):
        feeds.fetch_adsb_mil()


def test_recorder_survives_a_failed_poll(monkeypatch):
    from app.live import __main__ as cli

    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database restarting")
        raise KeyboardInterrupt  # ends the loop on the second poll

    monkeypatch.setattr(cli.feeds, "fetch_adsb_mil", flaky)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    with pytest.raises(KeyboardInterrupt):
        cli.main(["adsb", "--interval", "30"])
    assert len(calls) == 2

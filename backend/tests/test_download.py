import csv
import urllib.error
from datetime import date

from app.ingest import acled, download
from tests.builders import acled_row


def fake_acled(monkeypatch, pages):
    """Replaces the network with canned responses and records each request's query."""
    seen = []

    def respond(request, attempts=4):
        if request.full_url == download.ACLED_TOKEN_URL:
            return {"access_token": "token"}
        assert request.get_header("Authorization") == "Bearer token"
        assert request.get_header("User-agent") == download.ACLED_USER_AGENT
        seen.append(request.full_url)
        return {"status": 200, "data": pages[len(seen) - 1]}

    monkeypatch.setattr(download, "_request_json", respond)
    monkeypatch.setattr(download, "ACLED_PAGE_SIZE", 2)
    return seen


def test_acled_download_pages_until_a_short_page(monkeypatch, tmp_path):
    rows = [acled_row(event_id_cnty=f"TST{i}") for i in range(5)]
    seen = fake_acled(monkeypatch, [rows[0:2], rows[2:4], rows[4:5]])

    [path] = download.acled_events("e", "p", 2022, 2022, ["Test Land"], tmp_path)

    assert path.name == "acled-test-land-2022.csv"
    assert len(seen) == 3 and "page=3" in seen[2] and "country=Test+Land" in seen[0]
    with path.open(encoding="utf-8", newline="") as f:
        assert [r["event_id_cnty"] for r in csv.DictReader(f)] == [f"TST{i}" for i in range(5)]
    with path.open(encoding="utf-8", newline="") as f:
        assert all(r.event for r in acled.parse(f))


def test_acled_download_keeps_old_years_and_refreshes_recent_ones(monkeypatch, tmp_path):
    folder = tmp_path / "acled"
    folder.mkdir()
    for year in (2020, 2025):
        (folder / f"acled-all-{year}.csv").write_text("stale")
    seen = fake_acled(monkeypatch, [[acled_row()]])

    paths = download.acled_events("e", "p", 2020, 2020, [], tmp_path, today=date(2026, 10, 1))
    assert seen == [] and paths[0].read_text() == "stale"

    download.acled_events("e", "p", 2025, 2025, [], tmp_path, today=date(2026, 10, 1))
    assert len(seen) == 1 and "TST100" in (folder / "acled-all-2025.csv").read_text()


def test_ucdp_candidate_skips_months_not_posted_yet(monkeypatch, tmp_path):
    asked = []

    def fetch(url, dest, attempts=4):
        asked.append(url)
        if url.endswith(("_0_1.csv", "_0_2.csv")):
            return dest
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(download, "fetch", fetch)
    paths = download.ucdp_candidate(2026, 2026, tmp_path)

    assert [p.name for p in paths] == ["GEDEvent_v26_0_1.csv", "GEDEvent_v26_0_2.csv"]
    assert len(asked) == 12
    assert asked[8] == "https://ucdp.uu.se/downloads/candidateged/GEDEvent_v26_0_9.csv"

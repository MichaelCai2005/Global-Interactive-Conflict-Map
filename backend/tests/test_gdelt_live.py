"""GDELT 2.0's 15-minute files: report times, every article behind an event, catching up."""

import io
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.ingest import download, gdelt, loader
from app.ingest.loader import ingest_file, load_gdelt_live, prune_gdelt_ids
from app.models import Event, EventSource, GdeltId, IngestRun
from tests.builders import gdelt_row, gdelt_tsv

ADDED = "20220301101500"


def live_row(**overrides):
    return gdelt_row(61, **{"DATEADDED": ADDED, **overrides})


def mention(event_id, url, *, kind="1", seen="20220301120000", confidence="80", site=""):
    values = dict.fromkeys(gdelt.MENTION_COLUMNS, "")
    values.update(
        GLOBALEVENTID=str(event_id),
        EventTimeDate=ADDED,
        MentionTimeDate=seen,
        MentionType=kind,
        MentionSourceName=site,
        MentionIdentifier=url,
        Confidence=confidence,
    )
    return "\t".join(values.values()) + "\n"


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content)
    return path


def urls(session):
    return sorted(session.scalars(select(EventSource.url)))


def test_report_time_comes_from_dateadded_in_2_0_files_only():
    [live] = gdelt.parse(io.StringIO(gdelt_tsv([live_row()])))
    [daily] = gdelt.parse(io.StringIO(gdelt_tsv([gdelt_row(58)])))
    assert live.event.first_reported_at == datetime(2022, 3, 1, 10, 15, tzinfo=UTC)
    assert daily.event.first_reported_at is None


def test_mentions_keep_web_articles_only():
    text = (
        mention(1, "https://www.example.org/a")
        + mention(1, "BBC Monitoring 123", kind="2")
        + mention("x", "https://example.org/b")
        + "short\trow\n"
    )
    rows = list(gdelt.parse_mentions(io.StringIO(text)))
    assert rows[1:] == [None, None, None]
    assert rows[0] == gdelt.Mention(
        1, "https://www.example.org/a", "example.org", datetime(2022, 3, 1, 12, tzinfo=UTC), 80
    )


def test_every_row_of_a_collapsed_event_keeps_its_article(session, tmp_path):
    run = ingest_file(
        session,
        "gdelt",
        write(
            tmp_path,
            "20220301101500.export.CSV",
            gdelt_tsv(
                [
                    live_row(GLOBALEVENTID="1", SOURCEURL="https://a.example/1"),
                    live_row(GLOBALEVENTID="2", SOURCEURL="https://www.b.example/2"),
                    live_row(GLOBALEVENTID="3", SOURCEURL="https://a.example/1"),
                ]
            ),
        ),
    )
    assert run.status == "succeeded", run.error
    event = session.scalars(select(Event)).one()
    assert event.first_reported_at == datetime(2022, 3, 1, 10, 15, tzinfo=UTC)
    assert sorted(session.scalars(select(GdeltId.global_event_id))) == [1, 2, 3]
    assert urls(session) == ["https://a.example/1", "https://www.b.example/2"]
    assert set(session.scalars(select(EventSource.source_name))) == {"a.example", "b.example"}


def test_mentions_add_articles_to_events_loaded_earlier(session, tmp_path):
    ingest_file(
        session,
        "gdelt",
        write(
            tmp_path, "e.CSV", gdelt_tsv([live_row(GLOBALEVENTID="7", SOURCEURL="https://a.x/1")])
        ),
    )
    text = (
        mention(7, "https://a.x/1")  # the event row's own article
        + mention(7, "https://c.x/3", site="c.x")
        + mention(7, "https://c.x/3")  # same article, another sentence
        + mention(99, "https://d.x/4")  # an event this database doesn't have
    )
    run = ingest_file(session, "gdelt-mentions", write(tmp_path, "m.CSV", text))
    assert run.status == "succeeded", run.error
    assert (run.rows_read, run.inserted, run.merged_in_file) == (4, 1, 3)
    assert urls(session) == ["https://a.x/1", "https://c.x/3"]

    again = ingest_file(session, "gdelt-mentions", write(tmp_path, "m2.CSV", text))
    assert again.inserted == 0


def test_articles_per_event_are_capped(session, tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "MAX_SOURCES_PER_EVENT", 3)
    ingest_file(
        session,
        "gdelt",
        write(
            tmp_path, "e.CSV", gdelt_tsv([live_row(GLOBALEVENTID="7", SOURCEURL="https://a.x/0")])
        ),
    )
    text = "".join(mention(7, f"https://a.x/{i}", seen=f"2022030112{i:02d}00") for i in range(1, 6))
    ingest_file(session, "gdelt-mentions", write(tmp_path, "m.CSV", text))
    # The earliest articles are the ones kept.
    assert urls(session) == ["https://a.x/0", "https://a.x/1", "https://a.x/2"]


def test_a_daily_reload_keeps_the_quarter_hour_report_time(session, tmp_path):
    ingest_file(session, "gdelt", write(tmp_path, "live.CSV", gdelt_tsv([live_row()])))
    ingest_file(session, "gdelt", write(tmp_path, "daily.CSV", gdelt_tsv([gdelt_row(58)])))
    later = live_row(DATEADDED="20220302000000")
    ingest_file(session, "gdelt", write(tmp_path, "later.CSV", gdelt_tsv([later])))
    assert session.scalar(select(Event.first_reported_at)) == datetime(
        2022, 3, 1, 10, 15, tzinfo=UTC
    )


def test_old_gdelt_ids_are_forgotten(session, tmp_path):
    ingest_file(session, "gdelt", write(tmp_path, "e.CSV", gdelt_tsv([live_row()])))
    assert prune_gdelt_ids(session, days=30) == 1
    assert session.scalar(select(func.count()).select_from(GdeltId)) == 0
    assert session.scalar(select(func.count()).select_from(Event)) == 1


def test_lastupdate_names_the_newest_slot():
    listing = (
        "100 abc http://data.gdeltproject.org/gdeltv2/20261024150000.export.CSV.zip\n"
        "200 def http://data.gdeltproject.org/gdeltv2/20261024150000.mentions.CSV.zip\n"
        "300 ghi http://data.gdeltproject.org/gdeltv2/20261024150000.gkg.csv.zip\n"
    )
    newest, md5s = download.parse_lastupdate(listing)
    assert newest == datetime(2026, 10, 24, 15, tzinfo=UTC)
    assert md5s == {"export": "abc", "mentions": "def", "gkg": "ghi"}
    with pytest.raises(ValueError):
        download.parse_lastupdate("")


def test_slots_are_the_newest_quarter_hours_oldest_first():
    newest = datetime(2026, 10, 24, 15, tzinfo=UTC)
    q = timedelta(minutes=15)
    assert download.gdelt_live_slots(newest, 3) == [newest - 2 * q, newest - q, newest]


def test_an_empty_zip_is_retried_then_refused(tmp_path, monkeypatch):
    class Empty(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    calls = []
    monkeypatch.setattr(
        download.urllib.request, "urlopen", lambda url, timeout: calls.append(url) or Empty(b"")
    )
    monkeypatch.setattr(download.time, "sleep", lambda s: None)
    with pytest.raises(download.BadDownload):
        download.fetch("https://x/f.zip", tmp_path / "f.zip", attempts=2)
    assert len(calls) == 2 and not (tmp_path / "f.zip").exists()


def zipped(path, name, content):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name, content)
    return path


def test_live_load_catches_up_and_retries_missing_slots(session, tmp_path, monkeypatch):
    newest = datetime(2022, 3, 1, 10, 30, tzinfo=UTC)
    fetched = []
    missing = {"20220301101500"}

    def files(slot, out_dir, md5s=None):
        stamp = f"{slot:%Y%m%d%H%M%S}"
        fetched.append(stamp)
        if stamp in missing:
            return None  # GDELT hasn't posted this quarter hour (yet)
        row = live_row(GLOBALEVENTID=stamp[-4:], DATEADDED=stamp, SOURCEURL=f"https://n.x/{stamp}")
        return (
            zipped(tmp_path / f"{stamp}.export.CSV.zip", "e.CSV", gdelt_tsv([row])),
            zipped(
                tmp_path / f"{stamp}.mentions.CSV.zip",
                "m.CSV",
                mention(stamp[-4:], f"https://m.x/{stamp}", seen=stamp),
            ),
        )

    monkeypatch.setattr(download, "gdelt_live_files", files)
    assert load_gdelt_live(session, tmp_path, 3, latest=lambda: (newest, {}))
    assert fetched == ["20220301100000", "20220301101500", "20220301103000"]
    assert session.scalar(select(func.count()).select_from(IngestRun)) == 4

    # The next run tries only the slot that was missing, which has arrived since.
    fetched.clear()
    missing.clear()
    assert load_gdelt_live(session, tmp_path, 3, latest=lambda: (newest, {}))
    assert fetched == ["20220301101500"]
    assert session.scalar(select(func.count()).select_from(IngestRun)) == 6
    assert len(urls(session)) == 6


def test_api_lists_articles_and_filters_by_report_time(client, session, tmp_path):
    ingest_file(
        session,
        "gdelt",
        write(
            tmp_path,
            "e.CSV",
            gdelt_tsv(
                [
                    live_row(GLOBALEVENTID="1", SOURCEURL="https://a.x/1"),
                    live_row(GLOBALEVENTID="2", SOURCEURL="https://b.x/2"),
                    live_row(
                        GLOBALEVENTID="3",
                        EventCode="141",
                        EventRootCode="14",
                        DATEADDED="20220302080000",
                    ),
                ]
            ),
        ),
    )
    since = client.get("/events", params={"reported_since": "2022-03-02T00:00:00Z"}).json()
    assert [e["event_type"] for e in since["items"]] == ["protest"]
    reported = datetime.fromisoformat(since["items"][0]["first_reported_at"])
    assert reported == datetime(2022, 3, 2, 8, tzinfo=UTC)

    fight = client.get("/events", params={"event_type": "fight"}).json()["items"][0]
    detail = client.get(f"/events/{fight['id']}").json()
    assert detail["source_count"] == 2
    assert [s["url"] for s in detail["sources"]] == ["https://a.x/1", "https://b.x/2"]

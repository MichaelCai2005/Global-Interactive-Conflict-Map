"""Loads a source file into Postgres: parse, validate, dedupe, upsert, then link across sources."""

import io
import json
import logging
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TextIO

from sqlalchemy import func, literal_column, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ingest import acled, download, epr, gdelt, ucdp, vdem, wdi
from app.ingest.common import IndicatorValue, NormalizedEvent, ParsedIndicatorRow, ParsedRow
from app.models import CountryIndicator, Event, GdeltId, IngestRun, RejectedRecord

log = logging.getLogger(__name__)

PARSERS: dict[str, Callable[[TextIO], Iterator[ParsedRow]]] = {
    ucdp.SOURCE: ucdp.parse,
    acled.SOURCE: acled.parse,
    gdelt.SOURCE: gdelt.parse,
}
# Country-year structural indicators, stored in country_indicators rather than events.
INDICATOR_PARSERS: dict[str, Callable[[TextIO], Iterator[ParsedIndicatorRow]]] = {
    wdi.SOURCE: wdi.parse,
    vdem.SOURCE: vdem.parse,
    epr.SOURCE: epr.parse,
}
INDICATOR_NAMES = {
    wdi.SOURCE: wdi.INDICATORS,
    vdem.SOURCE: vdem.INDICATORS,
    epr.SOURCE: epr.INDICATORS,
}
# GDELT 2.0 Mentions files add articles to GDELT events already loaded.
MENTIONS = "gdelt-mentions"
SOURCES = sorted([*PARSERS, *INDICATOR_PARSERS, MENTIONS])

# When two sources describe the same incident, the lower number is kept as the canonical
# record and the other is marked as its duplicate. Hand-coded datasets beat machine-coded news;
# UCDP beats ACLED because its fatality counts carry low/high bounds and conflict ids.
SOURCE_PRIORITY = {ucdp.SOURCE: 1, acled.SOURCE: 2, gdelt.SOURCE: 3}

BATCH_SIZE = 1000
# Articles kept per event. A big story is mentioned by thousands; the first few dozen are
# enough to read it, and a cap keeps the table from growing with each retelling.
MAX_SOURCES_PER_EVENT = 50


@contextmanager
def open_source_file(path: Path) -> Iterator[TextIO]:
    """Opens a CSV directly or the first data file inside a .zip, as the sources ship them."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if not n.endswith("/")]
            data = [n for n in names if n.lower().endswith((".csv", ".tsv", ".txt"))] or names
            if not data:
                raise ValueError(f"{path.name} is an empty archive")
            with archive.open(data[0]) as raw:
                yield io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
    else:
        with path.open(encoding="utf-8", errors="replace", newline="") as handle:
            yield handle


def collapse_duplicates(events: list[NormalizedEvent]) -> tuple[list[NormalizedEvent], int]:
    """Merges rows that share a dedupe key, keeping the first, the highest report count
    and the earliest report time."""
    kept: dict[str, NormalizedEvent] = {}
    for event in events:
        existing = kept.get(event.dedupe_key)
        if existing is None:
            kept[event.dedupe_key] = event
        else:
            existing.report_count = max(existing.report_count, event.report_count)
            if event.first_reported_at and (
                existing.first_reported_at is None
                or event.first_reported_at < existing.first_reported_at
            ):
                existing.first_reported_at = event.first_reported_at
    return list(kept.values()), len(events) - len(kept)


def ingest_file(
    session: Session, source: str, path: Path, filename: str | None = None
) -> IngestRun:
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}, expected one of {SOURCES}")

    run = IngestRun(source=source, filename=filename or path.name)
    session.add(run)
    session.commit()

    try:
        if source in INDICATOR_PARSERS:
            _load_indicators(session, run, path)
        elif source == MENTIONS:
            _load_mentions(session, run, path)
        else:
            _load_events(session, run, path)
        run.status = "succeeded"
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        log.exception("ingest run %s failed", run.id)
    run.finished_at = func.now()
    session.add(run)
    session.commit()
    session.refresh(run)
    log.info(
        "ingest run %s (%s %s): %s read, %s inserted, %s updated, %s merged, %s rejected, "
        "%s filtered, %s cross-source links",
        run.id, source, run.filename, run.rows_read, run.inserted, run.updated,
        run.merged_in_file, run.rejected, run.filtered_out, run.cross_source_links,
    )  # fmt: skip
    return run


def _rejected(run: IngestRun, row: ParsedRow | ParsedIndicatorRow) -> dict:
    return {
        "ingest_run_id": run.id,
        "source": run.source,
        "row_number": row.row_number,
        "reasons": row.reasons,
        "raw": row.raw,
    }


def _save_rejected(session: Session, run: IngestRun, rejected: list[dict]) -> None:
    run.rejected = len(rejected)
    for start in range(0, len(rejected), BATCH_SIZE):
        session.execute(pg_insert(RejectedRecord), rejected[start : start + BATCH_SIZE])


def _load_events(session: Session, run: IngestRun, path: Path) -> None:
    events: list[NormalizedEvent] = []
    rejected: list[dict] = []
    with open_source_file(path) as stream:
        for row in PARSERS[run.source](stream):
            run.rows_read += 1
            if row.filtered_out:
                run.filtered_out += 1
            elif row.event is None:
                rejected.append(_rejected(run, row))
            else:
                events.append(row.event)

    # Each GDELT row is one article about an event; collapsing keeps only the first URL.
    articles = [
        (e.dedupe_key, int(e.source_event_id), e.source_url, e.first_reported_at)
        for e in events
        if run.source == gdelt.SOURCE and e.source_event_id.isdigit()
    ]
    events, run.merged_in_file = collapse_duplicates(events)
    _save_rejected(session, run, rejected)
    for start in range(0, len(events), BATCH_SIZE):
        inserted = _upsert(session, run.id, events[start : start + BATCH_SIZE])
        run.inserted += inserted
        run.updated += len(events[start : start + BATCH_SIZE]) - inserted
    if articles:
        _save_gdelt_articles(session, articles)
    if run.source == ucdp.SOURCE:
        drop_superseded_ucdp(session, run.id, events)
    run.cross_source_links = link_cross_source(session, run.id)


def release_years(events: list[NormalizedEvent]) -> list[int]:
    """The years a UCDP file covers in full, or none if it is a Candidate file.

    A GED release spans decades with events in every month of each year. A monthly
    Candidate file holds one month plus a few corrections to earlier ones, so it never
    fills two whole years. The columns are the same, so this is how the two are told apart.
    """
    months: dict[int, set[int]] = {}
    for e in events:
        months.setdefault(e.event_date.year, set()).add(e.event_date.month)
    full = sorted(year for year, seen in months.items() if len(seen) == 12)
    return full if len(full) >= 2 else []


def drop_superseded_ucdp(session: Session, run_id: int, events: list[NormalizedEvent]) -> int:
    """Deletes UCDP events in the years a GED release covers that the release left out.

    Monthly Candidate events are provisional. When the yearly GED release covers their
    year, UCDP has dropped some of them and recoded others under new ids (271 of the 1,912
    Candidate events for 2025 are not in GED 26.1), so without this the leftovers would
    be counted alongside their replacements. Every event in the release now carries this
    run's id, so whatever in those years still carries an older one is what it left out.
    """
    years = release_years(events)
    if not years:
        return 0
    deleted = session.execute(
        text("""
            DELETE FROM events
            WHERE source = :source
              AND event_date >= make_date(:first, 1, 1)
              AND event_date < make_date(:last + 1, 1, 1)
              AND extract(year FROM event_date)::int = ANY(:years)
              AND ingest_run_id <> :run_id
        """),
        {
            "source": ucdp.SOURCE,
            "years": years,
            "first": years[0],
            "last": years[-1],
            "run_id": run_id,
        },
    ).rowcount
    log.info(
        "dropped %d UCDP events the release for %s-%s superseded", deleted, years[0], years[-1]
    )
    return deleted


def _load_indicators(session: Session, run: IngestRun, path: Path) -> None:
    """Upserts country-year values; a newer release of a dataset overwrites revised values."""
    values: dict[tuple[str, str, int], IndicatorValue] = {}
    rejected: list[dict] = []
    with open_source_file(path) as stream:
        for row in INDICATOR_PARSERS[run.source](stream):
            run.rows_read += 1
            if row.filtered_out:
                run.filtered_out += 1
            elif row.reasons:
                rejected.append(_rejected(run, row))
            for value in row.values:
                key = (value.indicator, value.iso3, value.year)
                run.merged_in_file += key in values
                values[key] = value

    _save_rejected(session, run, rejected)
    rows = [{**asdict(v), "source": run.source, "ingest_run_id": run.id} for v in values.values()]
    for start in range(0, len(rows), BATCH_SIZE):
        stmt = pg_insert(CountryIndicator).values(rows[start : start + BATCH_SIZE])
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "indicator", "iso3", "year"],
            set_={"value": stmt.excluded.value, "ingest_run_id": stmt.excluded.ingest_run_id},
        ).returning(literal_column("(xmax = 0)"))
        inserted = sum(1 for (was_inserted,) in session.execute(stmt) if was_inserted)
        run.inserted += inserted
        run.updated += len(rows[start : start + BATCH_SIZE]) - inserted


def _upsert(session: Session, run_id: int, events: list[NormalizedEvent]) -> int:
    """Inserts new events and refreshes existing ones; returns how many were new."""
    stmt = pg_insert(Event).values([{**asdict(e), "ingest_run_id": run_id} for e in events])
    if events[0].source == gdelt.SOURCE:
        # A GDELT fingerprint seen again (a later file, or a re-run) is the same incident.
        changes = {
            "report_count": func.greatest(Event.report_count, stmt.excluded.report_count),
            # Fills the code in on events loaded before countries were mapped.
            "country_iso3": func.coalesce(stmt.excluded.country_iso3, Event.country_iso3),
            # LEAST skips NULLs, so a day-only GDELT 1.0 reload keeps a 2.0 report time.
            "first_reported_at": func.least(
                Event.first_reported_at, stmt.excluded.first_reported_at
            ),
        }
    else:
        # Curated sources revise past events between releases, so the newest file wins.
        skip = {"id", "source", "dedupe_key", "created_at", "duplicate_of_id"}
        changes = {
            c.name: stmt.excluded[c.name]
            for c in Event.__table__.columns
            if c.name not in skip and c.computed is None
        }
    changes |= {"ingest_run_id": stmt.excluded.ingest_run_id, "updated_at": func.now()}
    stmt = stmt.on_conflict_do_update(constraint="uq_events_source_key", set_=changes).returning(
        literal_column("(xmax = 0)")
    )
    return sum(1 for (was_inserted,) in session.execute(stmt) if was_inserted)


def _save_gdelt_articles(
    session: Session, articles: list[tuple[str, int, str | None, datetime | None]]
) -> None:
    """Records which event each GLOBALEVENTID went into, and each row's article."""
    keys = sorted({key for key, *_ in articles})
    ids: dict[str, int] = {}
    for start in range(0, len(keys), BATCH_SIZE):
        ids |= dict(
            session.execute(
                text(
                    "SELECT dedupe_key, id FROM events"
                    " WHERE source = :source AND dedupe_key = ANY(:keys)"
                ),
                {"source": gdelt.SOURCE, "keys": keys[start : start + BATCH_SIZE]},
            ).all()
        )
    mapping = [{"global_event_id": g, "event_id": ids[k]} for k, g, _, _ in articles if k in ids]
    for start in range(0, len(mapping), BATCH_SIZE):
        # A GLOBALEVENTID seen again stays with the event it first went into.
        session.execute(
            pg_insert(GdeltId).values(mapping[start : start + BATCH_SIZE]).on_conflict_do_nothing()
        )
    save_articles(
        session,
        [
            gdelt.Mention(g, url, gdelt.site_name(url), seen, None)
            for _, g, url, seen in articles
            if url and url.startswith(("http://", "https://"))
        ],
    )


def save_articles(session: Session, mentions: list[gdelt.Mention]) -> int:
    """Adds articles to the GDELT events their GLOBALEVENTIDs went into; returns how many
    were new. Mentions of ids never loaded (cooperation events, or older than the data)
    are skipped, and so are articles past an event's MAX_SOURCES_PER_EVENT."""
    unique = list({(m.global_event_id, m.url): m for m in mentions}.values())
    added = 0
    for start in range(0, len(unique), BATCH_SIZE):
        rows = [
            {
                "gdelt_id": m.global_event_id,
                "url": m.url,
                "source_name": m.source_name,
                "seen_at": m.seen_at.isoformat() if m.seen_at else None,
                "confidence": m.confidence,
            }
            for m in unique[start : start + BATCH_SIZE]
        ]
        added += session.execute(
            text("""
                WITH incoming AS (
                    SELECT DISTINCT ON (g.event_id, r.url)
                        g.event_id, r.url, r.source_name, r.seen_at, r.confidence
                    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(
                        gdelt_id bigint, url text, source_name text, seen_at timestamptz,
                        confidence smallint)
                    JOIN gdelt_ids g ON g.global_event_id = r.gdelt_id
                    WHERE NOT EXISTS (
                        SELECT 1 FROM event_sources s
                        WHERE s.event_id = g.event_id AND s.url = r.url)
                    ORDER BY g.event_id, r.url, r.seen_at
                ),
                ranked AS (
                    SELECT i.*, row_number() OVER (
                        PARTITION BY i.event_id ORDER BY i.seen_at, i.confidence DESC, i.url
                    ) AS n
                    FROM incoming i
                )
                INSERT INTO event_sources (event_id, url, source_name, first_seen_at, confidence)
                SELECT event_id, url, source_name, seen_at, confidence FROM ranked
                WHERE n + (SELECT count(*) FROM event_sources s WHERE s.event_id = ranked.event_id)
                      <= :cap
                ON CONFLICT (event_id, url) DO NOTHING
            """),
            {"rows": json.dumps(rows), "cap": MAX_SOURCES_PER_EVENT},
        ).rowcount
    return added


def _load_mentions(session: Session, run: IngestRun, path: Path) -> None:
    mentions: list[gdelt.Mention] = []
    with open_source_file(path) as stream:
        for mention in gdelt.parse_mentions(stream):
            run.rows_read += 1
            if mention is None:
                run.filtered_out += 1
            else:
                mentions.append(mention)
    run.inserted = save_articles(session, mentions)
    # The rest mention events this database doesn't hold, or articles it already lists.
    run.merged_in_file = len(mentions) - run.inserted


def _priority_sql(alias: str) -> str:
    cases = " ".join(f"WHEN '{s}' THEN {p}" for s, p in SOURCE_PRIORITY.items())
    return f"(CASE {alias}.source {cases} ELSE 99 END)"


def link_cross_source(session: Session, run_id: int) -> int:
    """Finds violent events from different sources that describe the same incident.

    Two events match when both have a location finer than country level, they are within
    LINK_RADIUS_KM of each other, and their dates are within LINK_DAY_WINDOW days (using the
    full date range for multi-day events). The lower-priority event of the closest match is
    marked as a duplicate of the other. Only pairs touching this run are considered.

    The search starts from this run's events and finds partners through
    ix_events_link_candidates, which indexes location and date range together; the
    `range(...) && ...` conditions exist so that index can be used.
    """
    settings = get_settings()
    params = {
        "run_id": run_id,
        "meters": settings.link_radius_km * 1000,
        "radius_km": settings.link_radius_km,
        "days": settings.link_day_window,
    }
    candidate = "is_violent AND {t}.geo_precision <> 'country'"
    date_range = "daterange({t}.event_date, COALESCE({t}.end_date, {t}.event_date), '[]')"
    inserted = session.execute(
        text(f"""
            WITH run_events AS (
                SELECT * FROM events r
                WHERE r.ingest_run_id = :run_id AND r.{candidate.format(t="r")}
            ),
            pairs AS (
                -- This run's events as duplicates of existing higher-priority events.
                SELECT d.id AS dup_id, c.id AS canon_id, d.event_date AS d_date,
                       c.event_date AS c_start, COALESCE(c.end_date, c.event_date) AS c_end,
                       ST_Distance(d.geog, c.geog) AS meters
                FROM run_events d
                JOIN events c
                  ON c.{candidate.format(t="c")}
                 AND c.source <> d.source
                 AND {date_range.format(t="c")}
                     && daterange(d.event_date - CAST(:days AS integer), d.event_date + CAST(:days AS integer), '[]')
                 AND ST_DWithin(d.geog, c.geog, :meters)
                WHERE {_priority_sql("d")} > {_priority_sql("c")}
                UNION ALL
                -- Existing lower-priority events as duplicates of this run's events.
                SELECT d.id, c.id, d.event_date, c.event_date, COALESCE(c.end_date, c.event_date),
                       ST_Distance(d.geog, c.geog)
                FROM run_events c
                JOIN events d
                  ON d.{candidate.format(t="d")}
                 AND d.source <> c.source
                 AND {date_range.format(t="d")} && daterange(
                     c.event_date - CAST(:days AS integer), COALESCE(c.end_date, c.event_date) + CAST(:days AS integer), '[]')
                 AND d.event_date BETWEEN c.event_date - CAST(:days AS integer)
                                      AND COALESCE(c.end_date, c.event_date) + CAST(:days AS integer)
                 AND ST_DWithin(d.geog, c.geog, :meters)
                WHERE {_priority_sql("d")} > {_priority_sql("c")}
            ),
            best AS (
                SELECT DISTINCT ON (dup_id)
                    dup_id, canon_id, meters / 1000.0 AS km,
                    GREATEST(c_start - d_date, d_date - c_end, 0) AS gap
                FROM pairs
                -- canon_id breaks ties between events at the same place and date, so a
                -- reload picks the same partner and adds no links.
                ORDER BY dup_id, gap, meters, canon_id
            )
            INSERT INTO event_links (event_id, related_event_id, link_type, distance_km, day_gap, score)
            SELECT dup_id, canon_id, 'possible_duplicate', km, gap,
                   round((1 - 0.5 * km / :radius_km - 0.5 * gap / (:days + 1.0))::numeric, 3)
            FROM best
            ON CONFLICT (event_id, related_event_id, link_type) DO NOTHING
        """),
        params,
    ).rowcount
    session.execute(
        text("""
            UPDATE events e SET duplicate_of_id = l.related_event_id
            FROM event_links l
            WHERE l.event_id = e.id AND l.link_type = 'possible_duplicate'
              AND e.duplicate_of_id IS NULL
        """)
    )
    return inserted


def loaded_live_slots(session: Session, slots: list[datetime]) -> set[datetime]:
    """The GDELT 2.0 quarter hours among these whose Mentions file loaded (after their
    Events file, so both are in)."""
    names = [f"{s:%Y%m%d%H%M%S}.mentions.CSV.zip" for s in slots]
    loaded = session.scalars(
        select(IngestRun.filename).where(
            IngestRun.source == MENTIONS,
            IngestRun.status == "succeeded",
            IngestRun.filename.in_(names),
        )
    )
    return {datetime.strptime(n[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC) for n in loaded}


def load_gdelt_live(
    session: Session,
    out_dir: Path,
    limit: int,
    latest: Callable[[], tuple[datetime, dict[str, str]]] = download.gdelt_live_latest,
) -> bool:
    """Loads each of the newest `limit` 15-minute GDELT slots not loaded yet, oldest first.

    GDELT sometimes lists a file before it can be downloaded, or leaves a slot out for
    hours, so a slot that fails or isn't there yet is tried again on every run until it
    loads or drops out of the window; the slots after it load meanwhile. Returns whether
    every slot GDELT has posted loaded.
    """
    newest, md5s = latest()
    window = download.gdelt_live_slots(newest, limit)
    done = loaded_live_slots(session, window)
    pending = [s for s in window if s not in done]
    if not pending:
        log.info("GDELT up to %s is already loaded", f"{newest:%Y-%m-%d %H:%M}")
    ok = True
    for slot in pending:
        try:
            files = download.gdelt_live_files(slot, out_dir, md5s if slot == newest else None)
        except Exception:
            log.exception("could not download GDELT %s", f"{slot:%Y%m%d%H%M%S}")
            ok = False
            continue
        if files is None:
            continue
        export, mentions = files
        # Mentions only find events already loaded, so a failed Events file stops its slot.
        for source, path in ((gdelt.SOURCE, export), (MENTIONS, mentions)):
            if ingest_file(session, source, path).status != "succeeded":
                ok = False
                break
    return ok


def prune_gdelt_ids(session: Session, days: int) -> int:
    """Forgets which event old GLOBALEVENTIDs went into, so their later Mentions are
    skipped. GDELT's mentions of an event mostly arrive within days, and the map holds
    millions of ids. The events and the articles already found stay."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    deleted = session.execute(
        text("""
            DELETE FROM gdelt_ids g USING events e
            WHERE e.id = g.event_id
              AND COALESCE(e.first_reported_at, e.event_date::timestamptz) < :cutoff
        """),
        {"cutoff": cutoff},
    ).rowcount
    session.commit()
    return deleted

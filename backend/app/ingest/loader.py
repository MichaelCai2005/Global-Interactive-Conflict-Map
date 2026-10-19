"""Loads a source file into Postgres: parse, validate, dedupe, upsert, then link across sources."""

import io
import logging
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import TextIO

from sqlalchemy import func, literal_column, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ingest import gdelt, ucdp
from app.ingest.common import NormalizedEvent, ParsedRow
from app.models import Event, IngestRun, RejectedRecord

log = logging.getLogger(__name__)

PARSERS: dict[str, Callable[[TextIO], Iterator[ParsedRow]]] = {
    ucdp.SOURCE: ucdp.parse,
    gdelt.SOURCE: gdelt.parse,
}

# When two sources describe the same incident, the lower number is kept as the canonical
# record and the other is marked as its duplicate. Hand-coded datasets beat machine-coded news.
SOURCE_PRIORITY = {ucdp.SOURCE: 1, gdelt.SOURCE: 3}

BATCH_SIZE = 1000


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
    """Merges rows that share a dedupe key, keeping the first and the highest report count."""
    kept: dict[str, NormalizedEvent] = {}
    for event in events:
        existing = kept.get(event.dedupe_key)
        if existing is None:
            kept[event.dedupe_key] = event
        else:
            existing.report_count = max(existing.report_count, event.report_count)
    return list(kept.values()), len(events) - len(kept)


def ingest_file(
    session: Session, source: str, path: Path, filename: str | None = None
) -> IngestRun:
    if source not in PARSERS:
        raise ValueError(f"unknown source {source!r}, expected one of {sorted(PARSERS)}")

    run = IngestRun(source=source, filename=filename or path.name)
    session.add(run)
    session.commit()

    try:
        events: list[NormalizedEvent] = []
        rejected: list[dict] = []
        with open_source_file(path) as stream:
            for row in PARSERS[source](stream):
                run.rows_read += 1
                if row.filtered_out:
                    run.filtered_out += 1
                elif row.event is None:
                    rejected.append(
                        {
                            "ingest_run_id": run.id,
                            "source": source,
                            "row_number": row.row_number,
                            "reasons": row.reasons,
                            "raw": row.raw,
                        }
                    )
                else:
                    events.append(row.event)

        events, run.merged_in_file = collapse_duplicates(events)
        run.rejected = len(rejected)
        for start in range(0, len(rejected), BATCH_SIZE):
            session.execute(pg_insert(RejectedRecord), rejected[start : start + BATCH_SIZE])
        for start in range(0, len(events), BATCH_SIZE):
            inserted = _upsert(session, run.id, events[start : start + BATCH_SIZE])
            run.inserted += inserted
            run.updated += len(events[start : start + BATCH_SIZE]) - inserted
        run.cross_source_links = link_cross_source(session, run.id)
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


def _upsert(session: Session, run_id: int, events: list[NormalizedEvent]) -> int:
    """Inserts new events and refreshes existing ones; returns how many were new."""
    stmt = pg_insert(Event).values([{**asdict(e), "ingest_run_id": run_id} for e in events])
    if events[0].source == gdelt.SOURCE:
        # A GDELT fingerprint seen again (a later file, or a re-run) is the same incident.
        changes = {"report_count": func.greatest(Event.report_count, stmt.excluded.report_count)}
    else:
        # Curated sources revise past events between releases, so the newest file wins.
        skip = {"id", "source", "dedupe_key", "created_at", "duplicate_of_id"}
        changes = {
            c.name: stmt.excluded[c.name] for c in Event.__table__.columns if c.name not in skip
        }
    changes |= {"ingest_run_id": stmt.excluded.ingest_run_id, "updated_at": func.now()}
    stmt = stmt.on_conflict_do_update(constraint="uq_events_source_key", set_=changes).returning(
        literal_column("(xmax = 0)")
    )
    return sum(1 for (was_inserted,) in session.execute(stmt) if was_inserted)


def _priority_sql(alias: str) -> str:
    cases = " ".join(f"WHEN '{s}' THEN {p}" for s, p in SOURCE_PRIORITY.items())
    return f"(CASE {alias}.source {cases} ELSE 99 END)"


def link_cross_source(session: Session, run_id: int) -> int:
    """Finds violent events from different sources that describe the same incident.

    Two events match when both have a location finer than country level, they are within
    LINK_RADIUS_KM of each other, and their dates are within LINK_DAY_WINDOW days (using the
    full date range for multi-day events). The lower-priority event of the closest match is
    marked as a duplicate of the other. Only pairs touching this run are considered.
    """
    settings = get_settings()
    params = {
        "run_id": run_id,
        "meters": settings.link_radius_km * 1000,
        "radius_km": settings.link_radius_km,
        "days": settings.link_day_window,
    }
    inserted = session.execute(
        text(f"""
            INSERT INTO event_links (event_id, related_event_id, link_type, distance_km, day_gap, score)
            SELECT dup_id, canon_id, 'possible_duplicate', km, gap,
                   round((1 - 0.5 * km / :radius_km - 0.5 * gap / (:days + 1.0))::numeric, 3)
            FROM (
                SELECT DISTINCT ON (d.id)
                    d.id AS dup_id,
                    c.id AS canon_id,
                    ST_Distance(d.geog, c.geog) / 1000.0 AS km,
                    GREATEST(c.event_date - d.event_date,
                             d.event_date - COALESCE(c.end_date, c.event_date), 0) AS gap
                FROM events d
                JOIN events c
                  ON c.source <> d.source
                 AND c.is_violent
                 AND c.geo_precision <> 'country'
                 AND d.event_date BETWEEN c.event_date - CAST(:days AS integer)
                                      AND COALESCE(c.end_date, c.event_date) + CAST(:days AS integer)
                 AND ST_DWithin(d.geog, c.geog, :meters)
                WHERE d.is_violent
                  AND d.geo_precision <> 'country'
                  AND {_priority_sql("d")} > {_priority_sql("c")}
                  AND (d.ingest_run_id = :run_id OR c.ingest_run_id = :run_id)
                ORDER BY d.id, gap, km
            ) best
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

"""The rules that suggest links, and the queries behind them.

A link is only suggested when it can name a concrete reason a person can check:

| rule           | from -> to         | reason                                                   |
| -------------- | ------------------ | -------------------------------------------------------- |
| mentions       | article -> place,  | the article names it (with the quote)                    |
|                | actor              |                                                          |
| reports        | article -> claim   | the article says this happened (with the quote)          |
| coded_from     | article -> event   | GDELT coded the event from this very article             |
| near           | place/claim/event  | within R km and D days                                   |
|                | -> event/fire/     |                                                          |
|                | flight             |                                                          |
| same_actor     | actor -> event     | the event's source names the actor                       |
| same_incident  | event -> event     | two sources report one incident (from ingest matching)   |
| co_reported    | event -> event     | GDELT coded both events from the same news report        |
| user           | any -> any         | an analyst drew it                                       |

Confidence is how strongly a link ties the item to the story, from 0 to 1. It is a
plain formula of distance, time and match quality, written next to each rule so it can be
explained, not a trained probability.
"""

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.boards.names import place_label

EVENT_TYPE_LABELS = {
    "explosion_remote_violence": "Shelling, strike or explosion",
    "battle": "Battle",
    "strategic_development": "Strategic development",
    "violence_against_civilians": "Violence against civilians",
    "protest": "Protest",
    "riot": "Riot",
    "fight": "Fighting reported",
    "coercion": "Coercion reported",
    "threat": "Threat reported",
    "assault": "Assault reported",
    "reduce_relations": "Relations reduced",
    "force_posture": "Force posture change",
    "mass_violence": "Mass violence reported",
    "state_based": "State-based armed conflict",
    "one_sided": "One-sided violence",
    "non_state": "Non-state armed conflict",
}

SOURCE_NAMES = {"ucdp": "UCDP GED", "acled": "ACLED", "gdelt": "GDELT"}


def utc_day(moment: datetime) -> date:
    """The UTC calendar day of a stored time. The database hands times back in its own
    time zone, where midnight UTC can still be the previous evening."""
    return moment.astimezone(UTC).date()


def proximity(distance_km: float, radius_km: float) -> float:
    return max(0.0, 1.0 - distance_km / radius_km)


def recency(days_apart: float, window_days: float) -> float:
    """1 on the same day, falling to 0.3 at the edge of the window."""
    return max(0.3, 1.0 - 0.7 * abs(days_apart) / max(window_days, 1))


def near_confidence(distance_km: float, radius_km: float, days: float, window: float) -> float:
    # 0.2 for something at the edge of both windows, 0.9 for the same spot on the same day.
    return round(
        0.2 + 0.7 * math.sqrt(proximity(distance_km, radius_km)) * recency(days, window), 2
    )


def actor_confidence(days: float, window: float) -> float:
    # The name match itself is exact (the source names the actor); time sets how close
    # the event is to this story.
    return round(0.45 + 0.4 * recency(days, window), 2)


def history_confidence(days_before: float, deaths: int) -> float:
    # Background, not part of this story's events: 0.3 to 0.55, higher when recent or deadly.
    recent = max(0.0, 1.0 - abs(days_before) / (3 * 365))
    return round(0.3 + 0.15 * recent + 0.1 * min(1.0, deaths / 20), 2)


def when(days: float) -> str:
    """'3 days before', 'the same day as', 'about 4 months before'."""
    whole = round(days)
    side = "before" if whole < 0 else "after"
    span = abs(whole)
    if span == 0:
        return "the same day as"
    if span >= 730:
        return f"about {round(span / 365)} years {side}"
    if span >= 60:
        return f"about {round(span / 30.4)} months {side}"
    return f"{span} {'day' if span == 1 else 'days'} {side}"


def distance_text(km: float) -> str:
    return "at the same spot" if km < 1 else f"{km:.0f} km away"


@dataclass
class EventRow:
    id: int
    source: str
    event_date: date
    event_type: str
    is_violent: bool
    country: str | None
    country_iso3: str | None
    location_name: str | None
    latitude: float
    longitude: float
    geo_precision: str
    actor1: str | None
    actor2: str | None
    fatalities_best: int | None
    report_count: int
    source_url: str | None
    attributes: dict[str, Any]
    distance_km: float | None = None

    @property
    def place(self) -> str:
        """'Kyiv' for UCDP's 'Kyiv city' and GDELT's 'Kyiv, Kyyiv, Misto, Ukraine'."""
        name = (self.location_name or self.country or "unknown place").split(",")[0]
        return place_label(name)

    @property
    def label(self) -> str:
        return f"{EVENT_TYPE_LABELS.get(self.event_type, self.event_type)} in {self.place}"

    def detail(self) -> str:
        actors = " vs ".join(a for a in (self.actor1, self.actor2) if a)
        parts = [f"{self.event_date.isoformat()} · {SOURCE_NAMES.get(self.source, self.source)}"]
        if actors:
            parts.append(actors)
        if self.fatalities_best:
            parts.append(f"{self.fatalities_best} reported deaths")
        if self.source == "gdelt":
            parts.append(f"machine-coded from {self.report_count} news report(s), unverified")
        notes = self.attributes.get("notes") or self.attributes.get("where_description")
        if notes:
            parts.append(str(notes)[:600])
        return "\n".join(parts)


EVENT_COLUMNS = """
    e.id, e.source, e.event_date, e.event_type, e.is_violent, e.country, e.country_iso3,
    e.location_name, e.latitude, e.longitude, e.geo_precision, e.actor1, e.actor2,
    e.fatalities_best, e.report_count, e.source_url, e.attributes
"""


def _rows(result) -> list[EventRow]:
    return [EventRow(**r._mapping) for r in result]


def events_near(
    db: Session,
    lat: float,
    lon: float,
    radius_km: float,
    start: date,
    end: date,
    limit: int = 1500,
    sources: tuple[str, ...] = ("ucdp", "acled", "gdelt"),
) -> list[EventRow]:
    """Events within a radius and date range, curated sources and deadly events first.

    GDELT rows count only when violent: its threat, coercion and diplomacy codes pile up
    on every capital a story mentions and say little about what happened there.
    """
    return _rows(
        db.execute(
            text(f"""
                SELECT {EVENT_COLUMNS},
                       ST_Distance(e.geog, ST_MakePoint(:lon, :lat)::geography) / 1000 AS distance_km
                FROM events e
                WHERE ST_DWithin(e.geog, ST_MakePoint(:lon, :lat)::geography, :radius)
                  AND e.event_date BETWEEN :start AND :end
                  AND e.duplicate_of_id IS NULL
                  AND e.geo_precision <> 'country'
                  AND e.source = ANY(:sources)
                  AND (e.source <> 'gdelt' OR e.is_violent)
                ORDER BY (e.source = 'gdelt'), e.fatalities_best DESC NULLS LAST,
                         e.report_count DESC, e.event_date DESC
                LIMIT :limit
            """),
            {
                "lat": lat,
                "lon": lon,
                "radius": radius_km * 1000,
                "start": start,
                "end": end,
                "limit": limit,
                "sources": list(sources),
            },
        )
    )


def events_by_actor(
    db: Session,
    actor_keys: list[str],
    start: date,
    end: date,
    gdelt_codes: list[str] | None = None,
    limit: int = 1500,
) -> list[EventRow]:
    """Events whose source names one of these actors.

    UCDP and ACLED name actors in words. GDELT codes them (CAMEO): "RUS" for Russia and
    "RUSMIL" for its military, so state forces also match violent GDELT events by code.
    """
    if not actor_keys and not gdelt_codes:
        return []
    rows = _rows(
        db.execute(
            text(f"""
                SELECT {EVENT_COLUMNS}, NULL::float AS distance_km
                FROM events e
                WHERE (board_actor_key(e.actor1) = ANY(:keys)
                       OR board_actor_key(e.actor2) = ANY(:keys))
                  AND e.event_date BETWEEN :start AND :end
                  AND e.duplicate_of_id IS NULL
                  AND (e.source <> 'gdelt' OR e.is_violent)
                ORDER BY (e.source = 'gdelt'), e.event_date DESC
                LIMIT :limit
            """),
            {"keys": actor_keys, "start": start, "end": end, "limit": limit},
        )
    )
    if gdelt_codes:
        rows += _rows(
            db.execute(
                text(f"""
                    SELECT {EVENT_COLUMNS}, NULL::float AS distance_km
                    FROM events e
                    WHERE e.source = 'gdelt' AND e.is_violent
                      AND (e.attributes->>'actor1_code' = ANY(:codes)
                           OR e.attributes->>'actor2_code' = ANY(:codes))
                      AND e.event_date BETWEEN :start AND :end
                      AND e.duplicate_of_id IS NULL
                    ORDER BY e.report_count DESC, e.event_date DESC
                    LIMIT :limit
                """),
                {"codes": gdelt_codes, "start": start, "end": end, "limit": limit},
            )
        )
    return rows


def events_from_url(db: Session, url: str) -> list[EventRow]:
    """Events GDELT coded from this article. GDELT stores the URL as it crawled it."""
    variants = {url, url.rstrip("/"), url.rstrip("/") + "/"}
    for scheme in ("http://", "https://"):
        for v in list(variants):
            if v.startswith(("http://", "https://")):
                variants.add(scheme + v.split("://", 1)[1])
    return _rows(
        db.execute(
            text(f"""
                SELECT {EVENT_COLUMNS}, NULL::float AS distance_km FROM events e
                WHERE e.source_url = ANY(:urls) AND e.duplicate_of_id IS NULL
                ORDER BY e.event_date DESC LIMIT 50
            """),
            {"urls": sorted(variants)},
        )
    )


def events_by_id(db: Session, ids: list[int]) -> list[EventRow]:
    if not ids:
        return []
    return _rows(
        db.execute(
            text(
                f"SELECT {EVENT_COLUMNS}, NULL::float AS distance_km FROM events e "
                "WHERE e.id = ANY(:ids)"
            ),
            {"ids": ids},
        )
    )


def incident_links(db: Session, event_ids: list[int]) -> list[tuple[int, int, float, float, int]]:
    """Pairs among these events that ingest matched as one incident in two sources."""
    if len(event_ids) < 2:
        return []
    rows = db.execute(
        text("""
            SELECT event_id, related_event_id, score, distance_km, day_gap FROM event_links
            WHERE event_id = ANY(:ids) AND related_event_id = ANY(:ids)
        """),
        {"ids": event_ids},
    )
    return [tuple(r) for r in rows]


def duplicates_of(db: Session, event_ids: list[int]) -> list[tuple[int, int]]:
    """(kept event, duplicate) pairs, so a board shows the other source's report too."""
    if not event_ids:
        return []
    rows = db.execute(
        text("""
            SELECT duplicate_of_id, id FROM events
            WHERE duplicate_of_id = ANY(:ids) LIMIT 200
        """),
        {"ids": event_ids},
    )
    return [tuple(r) for r in rows]


def rank_events(
    rows: list[EventRow], anchor: date, window_days: int, limit: int, gdelt_limit: int = 2
) -> list[EventRow]:
    """Pick a readable handful: close, recent, deadly; few machine-coded GDELT rows.

    GDELT codes one news story into many near-identical rows, so at most one row per day,
    type and place is kept.
    """

    def score(r: EventRow) -> float:
        near = 1.0 if r.distance_km is None else 1.0 / (1.0 + r.distance_km / 10)
        days = abs((r.event_date - anchor).days)
        fresh = 1.0 - min(days, window_days) / (window_days + 1)
        deadly = min(1.0, (r.fatalities_best or 0) / 10)
        curated = 0.15 if r.source != "gdelt" else 0.0
        reports = min(0.1, (r.report_count or 0) / 100) if r.source == "gdelt" else 0.0
        return 0.35 * near + 0.3 * fresh + 0.2 * deadly + curated + reports

    chosen: list[EventRow] = []
    seen_gdelt: set[tuple] = set()
    gdelt = 0
    for r in sorted(rows, key=score, reverse=True):
        if r.source == "gdelt":
            signature = (r.event_date, r.event_type, round(r.latitude, 2), round(r.longitude, 2))
            if gdelt >= gdelt_limit or signature in seen_gdelt:
                continue
            seen_gdelt.add(signature)
            gdelt += 1
        chosen.append(r)
        if len(chosen) >= limit:
            break
    return chosen


@dataclass
class Track:
    """One aircraft's or ship's positions near a place: a line on the board."""

    source: str
    kind: str
    external_id: str
    label: str
    points: list[tuple[float, float, datetime]]
    closest_km: float
    attributes: dict[str, Any]

    @property
    def start(self) -> datetime:
        return self.points[0][2]

    @property
    def end(self) -> datetime:
        return self.points[-1][2]


def observations_near(
    db: Session,
    kind: str,
    lat: float,
    lon: float,
    radius_km: float,
    start: datetime,
    end: datetime,
    limit: int = 20,
) -> list[Track]:
    """Recorded flights, fires or ships within a radius and time range, one track each."""
    rows = db.execute(
        text("""
            SELECT source, external_id, observed_at, latitude, longitude, label, attributes,
                   ST_Distance(geog, ST_MakePoint(:lon, :lat)::geography) / 1000 AS km
            FROM observations
            WHERE kind = :kind AND observed_at BETWEEN :start AND :end
              AND ST_DWithin(geog, ST_MakePoint(:lon, :lat)::geography, :radius)
            ORDER BY external_id, observed_at
            LIMIT 20000
        """),
        {
            "kind": kind,
            "lat": lat,
            "lon": lon,
            "radius": radius_km * 1000,
            "start": start,
            "end": end,
        },
    ).all()
    tracks: dict[tuple[str, str], Track] = {}
    for r in rows:
        track = tracks.get((r.source, r.external_id))
        if track is None:
            track = tracks[(r.source, r.external_id)] = Track(
                source=r.source,
                kind=kind,
                external_id=r.external_id,
                label=r.label or r.external_id,
                points=[],
                closest_km=r.km,
                attributes=dict(r.attributes or {}),
            )
        track.points.append((r.longitude, r.latitude, r.observed_at.astimezone(UTC)))
        track.closest_km = min(track.closest_km, r.km)
    return sorted(tracks.values(), key=lambda t: t.closest_km)[:limit]


def window(anchor: date, lookback_days: int, lookahead_days: int) -> tuple[date, date]:
    return anchor - timedelta(days=lookback_days), anchor + timedelta(days=lookahead_days)

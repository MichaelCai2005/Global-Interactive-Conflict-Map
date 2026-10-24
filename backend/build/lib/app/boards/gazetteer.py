"""Find places and actors named in an article among the names the event sources use.

The events table is the gazetteer: half a million events with coordinates, so a town
that has seen conflict is almost always in it under the name the sources use. Matching
there, instead of an outside geocoder, also says how much history each place has.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.boards.names import GENERIC_ACTORS, actor_aliases, country_words, place_key


@dataclass
class Place:
    key: str
    name: str
    iso3: str | None
    country: str | None
    latitude: float
    longitude: float
    events: int
    # Other places in the gazetteer with the same name, e.g. the many Ukrainian villages
    # called Novoselivka. The board says so instead of hiding the guess.
    alternatives: int = 0
    sources: list[str] = field(default_factory=list)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


# Places with the same name less than this far apart are one place: sources disagree on
# a town's coordinates by a few kilometres.
SAME_PLACE_KM = 30.0


def lookup_places(db: Session, names: Iterable[str]) -> dict[str, list[Place]]:
    """Every gazetteer place for each name, biggest first, keyed by place key."""
    keys = sorted({k for k in (place_key(n) for n in names) if k and len(k) >= 3})
    if not keys:
        return {}
    rows = db.execute(
        text("""
            SELECT board_place_key(location_name) AS key,
                   country_iso3 AS iso3,
                   mode() WITHIN GROUP (ORDER BY country) AS country,
                   mode() WITHIN GROUP (ORDER BY split_part(location_name, ',', 1)) AS name,
                   floor(latitude) AS lat_cell, floor(longitude) AS lon_cell,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY latitude) AS latitude,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY longitude) AS longitude,
                   count(*) AS events,
                   array_agg(DISTINCT source) AS sources
            FROM events
            WHERE board_place_key(location_name) = ANY(:keys)
              AND geo_precision <> 'country'
              AND duplicate_of_id IS NULL
            GROUP BY 1, 2, 5, 6
        """),
        {"keys": keys},
    ).all()
    found: dict[str, list[Place]] = {}
    for r in sorted(rows, key=lambda r: -r.events):
        places = found.setdefault(r.key, [])
        same = next(
            (
                p
                for p in places
                if p.iso3 == r.iso3
                and haversine_km(p.latitude, p.longitude, r.latitude, r.longitude) < SAME_PLACE_KM
            ),
            None,
        )
        if same:
            same.events += r.events
            same.sources = sorted(set(same.sources) | set(r.sources))
            continue
        places.append(
            Place(
                key=r.key,
                name=_display_name(r.name),
                iso3=r.iso3,
                country=r.country,
                latitude=float(r.latitude),
                longitude=float(r.longitude),
                events=r.events,
                sources=sorted(r.sources),
            )
        )
    for places in found.values():
        places.sort(key=lambda p: -p.events)
        for p in places:
            p.alternatives = len(places) - 1
    return found


def _display_name(name: str) -> str:
    key = place_key(name) or name
    # Keep the source's capitalisation, minus UCDP's "town"/"city" suffix.
    return name[: len(key)] if name.lower().startswith(key) else name


def choose_place(
    candidates: list[Place], countries: list[str], near: tuple[float, float] | None = None
) -> Place | None:
    """Pick the place an article most likely means.

    Prefer the countries the article names. Among several there, prefer the one nearest
    the article's other places, then the one with the most events.
    """
    if not candidates:
        return None
    in_country = [p for p in candidates if p.iso3 in countries] if countries else candidates
    if not in_country:
        return None
    if near and len(in_country) > 1:
        return min(in_country, key=lambda p: haversine_km(p.latitude, p.longitude, *near))
    return in_country[0]


@dataclass
class Actor:
    """An actor as the event sources name it, with the phrases an article may use instead."""

    name: str
    events: int
    aliases: list[str]


def candidate_actors(
    db: Session, countries: list[str], since: date, limit: int = 400
) -> list[Actor]:
    """The most active named actors in these countries since a date.

    Names come from UCDP and ACLED, whose analysts name armed groups consistently. GDELT
    codes places and roles as actors ("KYIV", "POLICE"), so its names are not candidates,
    but its events still match an actor through the shared lower-case key ("HAMAS" and
    "Hamas"). Country names are left out: they would match everything.
    """
    if not countries:
        return []
    rows = db.execute(
        text("""
            SELECT name, count(*) AS events FROM (
                SELECT actor1 AS name FROM events
                WHERE country_iso3 = ANY(:countries) AND event_date >= :since
                  AND source IN ('ucdp', 'acled') AND actor1 IS NOT NULL
                UNION ALL
                SELECT actor2 FROM events
                WHERE country_iso3 = ANY(:countries) AND event_date >= :since
                  AND source IN ('ucdp', 'acled') AND actor2 IS NOT NULL
            ) named
            GROUP BY name
            ORDER BY events DESC
            LIMIT :limit
        """),
        {"countries": countries, "since": since, "limit": limit * 3},
    ).all()
    actors: list[Actor] = []
    countries_lower = country_words()
    for r in rows:
        lowered = r.name.strip().lower()
        if lowered in GENERIC_ACTORS or lowered in countries_lower:
            continue
        aliases = actor_aliases(r.name)
        if aliases:
            actors.append(Actor(name=r.name, events=r.events, aliases=aliases))
        if len(actors) >= limit:
            break
    return actors

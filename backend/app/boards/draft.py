"""Build a draft board from an article, and grow a board from any of its nodes.

Everything the rules add is a suggestion. Only the article itself starts accepted; an
analyst accepts or rejects the rest before it goes into a briefing.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.boards import gazetteer, rules
from app.boards.articles import Article
from app.boards.extract import ExtractedActor, Extraction
from app.boards.geocode import geocode
from app.boards.models import Board, BoardLink, BoardNode
from app.boards.names import (
    GENERIC_ACTORS,
    actor_key,
    country_names,
    country_words,
    fold,
    gdelt_codes,
    normalized_url,
)

log = logging.getLogger(__name__)


@dataclass
class RuleSettings:
    lookback_days: int = 60
    lookahead_days: int = 3
    place_radius_km: float = 25.0
    claim_radius_km: float = 15.0
    claim_days: int = 2
    events_per_place: int = 6
    events_per_actor: int = 5
    max_events: int = 60
    # same_actor only looks this far from the story's places, so a Ukraine story does not
    # pull in the same army's events in Syria.
    actor_region_km: float = 400.0
    flight_radius_km: float = 75.0
    flight_hours: int = 24
    fire_radius_km: float = 10.0
    fire_days: int = 2
    expand_radius_km: float = 15.0
    expand_days: int = 14
    # "How we got here": the deadliest earlier UCDP/ACLED events at each place, from
    # before the lookback window back this many years.
    history_years: int = 3
    history_per_place: int = 3
    history_places: int = 6


def at_midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=UTC)


def iso3_for(country: str | None) -> str | None:
    if not country:
        return None
    names = {k.lower(): v for k, v in country_names().items()}
    return names.get(country.strip().lower()) or (
        country.upper() if len(country) == 3 and country.isalpha() else None
    )


def parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class BoardBuilder:
    """Adds nodes and links to a board without duplicates."""

    def __init__(self, db: Session, board: Board, settings: RuleSettings | None = None):
        self.db = db
        self.board = board
        self.settings = settings or RuleSettings()
        self.nodes: dict[str, BoardNode] = {n.key: n for n in board.nodes}
        self.link_keys = {(k.from_node_id, k.to_node_id, k.rule) for k in board.links}
        self._pending_links: list[tuple[BoardNode, BoardNode, dict[str, Any]]] = []

    # --- primitives ---------------------------------------------------------------

    def node(self, key: str, **fields: Any) -> BoardNode:
        existing = self.nodes.get(key)
        if existing is not None:
            return existing
        node = BoardNode(board_id=self.board.id, key=key, **fields)
        node.attributes = node.attributes or {}
        self.board.nodes.append(node)
        self.nodes[key] = node
        return node

    def link(
        self,
        a: BoardNode,
        b: BoardNode,
        rule: str,
        reason: str,
        confidence: float,
        evidence: dict[str, Any] | None = None,
        created_by: str = "rule",
    ) -> None:
        if a is b:
            return
        self._pending_links.append(
            (
                a,
                b,
                {
                    "rule": rule,
                    "reason": reason,
                    "confidence": max(0.0, min(1.0, confidence)),
                    "evidence": evidence or {},
                    "created_by": created_by,
                },
            )
        )

    def flush(self) -> None:
        """Write pending links once their nodes have ids."""
        self.db.flush()
        for a, b, fields in self._pending_links:
            key = (a.id, b.id, fields["rule"])
            if key in self.link_keys or (b.id, a.id, fields["rule"]) in self.link_keys:
                continue
            self.link_keys.add(key)
            self.board.links.append(
                BoardLink(board_id=self.board.id, from_node_id=a.id, to_node_id=b.id, **fields)
            )
        self._pending_links.clear()
        self.db.flush()

    def event_count(self) -> int:
        return sum(1 for n in self.nodes.values() if n.kind == "event")

    # --- typed nodes --------------------------------------------------------------

    def event_node(self, row: rules.EventRow) -> BoardNode:
        return self.node(
            f"event:{row.id}",
            kind="event",
            label=row.label,
            detail=row.detail(),
            event_id=row.id,
            latitude=row.latitude,
            longitude=row.longitude,
            geo_basis="exact" if row.geo_precision == "exact" else "approximate",
            time_start=at_midnight(row.event_date),
            source_name=rules.SOURCE_NAMES.get(row.source, row.source),
            source_url=row.source_url,
            created_by="rule",
            attributes={
                "source": row.source,
                "event_type": row.event_type,
                "violent": row.is_violent,
                "deaths": row.fatalities_best or 0,
                "actors": [a for a in (row.actor1, row.actor2) if a],
                "country": row.country,
            },
        )

    def track_node(self, track: rules.Track) -> BoardNode:
        start, end = track.start, track.end
        points = [[round(lon, 5), round(lat, 5)] for lon, lat, _ in track.points]
        last_lon, last_lat = points[-1]
        geometry = (
            {"type": "LineString", "coordinates": points}
            if len(points) >= 2
            else {"type": "Point", "coordinates": points[0]}
        )
        names = {"flight": "Flight", "fire": "Fire detection", "vessel": "Vessel"}
        return self.node(
            f"{track.kind}:{track.source}:{track.external_id}:{start:%Y%m%d}",
            kind=track.kind,
            label=f"{names.get(track.kind, track.kind)} {track.label}",
            detail=_track_detail(track),
            latitude=last_lat,
            longitude=last_lon,
            geometry=geometry,
            geo_basis="exact",
            time_start=start,
            time_end=end,
            source_name=track.source,
            created_by="rule",
            attributes={"external_id": track.external_id, **track.attributes},
        )


def _track_detail(track: rules.Track) -> str:
    a = track.attributes
    parts = [f"{track.start:%Y-%m-%d %H:%M} to {track.end:%H:%M} UTC · {track.source}"]
    for label, key in (
        ("Type", "type"),
        ("Registration", "registration"),
        ("Operator", "operator"),
        ("Confidence", "confidence"),
        ("Fire power (MW)", "frp"),
    ):
        if a.get(key):
            parts.append(f"{label}: {a[key]}")
    parts.append(f"{len(track.points)} recorded position(s); closest {track.closest_km:.0f} km")
    return "\n".join(parts)


# --- From an article ----------------------------------------------------------------


def build_from_article(
    db: Session,
    board: Board,
    article: Article,
    extraction: Extraction,
    anchor: date,
    settings: RuleSettings | None = None,
    article_key: str = "article",
) -> Board:
    """Add an article and everything the rules link to it. A topic board calls this once
    per article with its own key; places, actors and events they share are merged."""
    b = BoardBuilder(db, board, settings)
    s = b.settings
    start, end = rules.window(anchor, s.lookback_days, s.lookahead_days)
    countries = [c for c in (iso3_for(c) for c in extraction.countries) if c]
    focus = [c for c in (iso3_for(c) for c in extraction.focus_countries) if c] or countries[:2]
    body = f"{article.title or ''}\n{article.text}"
    by_ai = "ai" if board.extractor == "claude" else "rule"

    article_node = b.node(
        article_key,
        kind="article",
        label=article.title or extraction.title or "Article",
        detail=_article_detail(article),
        time_start=at_midnight(anchor),
        source_name=article.site,
        source_url=article.url,
        retrieved_at=datetime.now(UTC),
        status="accepted",
        created_by="user",
        attributes={"countries": countries, "extractor": board.extractor},
    )

    # Places: the gazetteer first, then OpenStreetMap for places with no conflict history.
    place_nodes: dict[str, BoardNode] = {}
    found = gazetteer.lookup_places(db, [p.name for p in extraction.places])
    resolved: list[tuple[Any, gazetteer.Place | None, Any]] = []
    for p in extraction.places:
        key = gazetteer.place_key(p.name)
        wanted = [c for c in [iso3_for(p.country), *countries] if c]
        resolved.append((p, gazetteer.choose_place(found.get(key, []), wanted), wanted))
    unique = [g for _, g, _ in resolved if g and g.alternatives == 0]
    centre = _centre([(g.latitude, g.longitude) for g in unique]) if unique else None
    for p, place, wanted in resolved:
        if place is not None and place.alternatives and centre:
            place = gazetteer.choose_place(found[place.key], wanted, near=centre)
        node = _place_node(b, p, place, wanted, by_ai)
        if node is None:
            continue
        # Datelines and summit venues ("reported from Lisbon") stay on the board, but only
        # places in the story's main countries pull in events around them.
        iso3 = place.iso3 if place else (wanted[0] if wanted else None)
        node.attributes = {**node.attributes, "focus": not focus or iso3 in focus}
        place_nodes[fold(p.name)] = node
        reason = _mention_reason(p, place, node)
        if not node.attributes["focus"]:
            reason["reason"] += "; outside the story's main countries"
            reason["confidence"] = min(reason["confidence"], 0.5)
        b.link(article_node, node, "mentions", **reason)

    places = list(dict.fromkeys(place_nodes.values()))
    focus_places = [p for p in places if p.attributes.get("focus")]
    _locate_article(db, article_node, focus_places or places, body, countries)

    # Claims: what the article says happened, placed where it says.
    claim_nodes = []
    for i, c in enumerate(extraction.claims):
        place = place_nodes.get(fold(c.place)) if c.place else None
        if place is None:
            continue
        day = parse_day(c.date) or anchor
        node = b.node(
            f"claim:{article_key}:{i}",
            kind="claim",
            label=c.summary,
            detail=f"The article reports this {'on ' + day.isoformat() if c.date else ''}"
            f" in {place.label}.".replace("  ", " "),
            latitude=place.latitude,
            longitude=place.longitude,
            geo_basis="derived",
            time_start=at_midnight(day),
            source_name=article.site,
            source_url=article.url,
            quote=c.quote,
            created_by="ai",
            attributes={"actors": c.actors, "date_stated": c.date is not None},
        )
        claim_nodes.append(node)
        b.link(
            article_node,
            node,
            "reports",
            "The article reports this happened",
            0.9,
            {"quote": c.quote},
        )

    # Actors.
    actor_nodes = _actor_nodes(b, extraction.actors, countries, anchor, article_node, by_ai)

    # Events GDELT coded from this very article.
    if article.url:
        for row in rules.events_from_url(db, article.url)[:10]:
            node = b.event_node(row)
            b.link(
                article_node,
                node,
                "coded_from",
                "GDELT machine-coded this event from this article",
                0.95,
                {"url": row.source_url},
            )

    # Events near the places the article names.
    for place in focus_places:
        if b.event_count() >= s.max_events:
            break
        _link_near_events(
            b,
            place,
            anchor,
            s.place_radius_km,
            start,
            end,
            s.lookback_days,
            s.events_per_place,
            "the article's date",
        )

    # How we got here: the deadliest earlier events at the story's places.
    # Only for the first few places, so a long article's board stays about its story.
    for place in focus_places[: s.history_places]:
        _link_history(b, place, anchor)

    # Events that may be the incident a claim describes.
    for claim in claim_nodes:
        day = rules.utc_day(claim.time_start)
        _link_near_events(
            b,
            claim,
            day,
            s.claim_radius_km,
            day - timedelta(days=s.claim_days),
            day + timedelta(days=s.claim_days),
            s.claim_days,
            3,
            "the reported date",
            rule="near",
            framing="possibly the same incident: ",
        )

    # Events by the actors the article names, near the story.
    region = [(p.latitude, p.longitude) for p in focus_places] or (
        [(article_node.latitude, article_node.longitude)]
        if article_node.latitude is not None
        else []
    )
    for actor in actor_nodes:
        _link_actor_events(b, actor, anchor, start, end, region)

    _link_between_events(b)
    _link_observations(b, focus_places + claim_nodes, anchor)
    _place_actors(b, actor_nodes, article_node)
    b.flush()
    return board


def _article_detail(article: Article) -> str:
    parts = []
    if article.published:
        parts.append(f"Published {article.published.isoformat()}")
    if article.site:
        parts.append(article.site)
    if article.text:
        parts.append(article.text[:500] + ("…" if len(article.text) > 500 else ""))
    return "\n".join(parts)


def _centre(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


SAME_SPOT_KM = 5.0


def _same_spot(b: BoardBuilder, lat: float, lon: float) -> BoardNode | None:
    return next(
        (
            n
            for n in b.nodes.values()
            if n.kind == "place"
            and n.latitude is not None
            and gazetteer.haversine_km(n.latitude, n.longitude, lat, lon) < SAME_SPOT_KM
        ),
        None,
    )


def _place_node(
    b: BoardBuilder, p, place: gazetteer.Place | None, wanted, by_ai
) -> BoardNode | None:
    if place is not None:
        if same := _same_spot(b, place.latitude, place.longitude):
            same.attributes = {**same.attributes, "also_written": p.name}
            return same
        return b.node(
            f"place:{place.iso3 or 'xx'}:{place.key}:{place.latitude:.2f}:{place.longitude:.2f}",
            kind="place",
            label=place.name,
            detail=f"{place.country or ''} · {place.events} events in the data "
            f"({', '.join(rules.SOURCE_NAMES.get(s, s) for s in place.sources)})".strip(" ·"),
            latitude=place.latitude,
            longitude=place.longitude,
            geo_basis="gazetteer",
            quote=p.quote,
            created_by=by_ai,
            attributes={
                "iso3": place.iso3,
                "events": place.events,
                "alternatives": place.alternatives,
                "as_written": p.name,
            },
        )
    country = p.country or (wanted[0] if wanted else None)
    found = geocode(p.name, country)
    if found is None:
        log.info("could not place %r", p.name)
        return None
    if same := _same_spot(b, found.latitude, found.longitude):
        return same
    return b.node(
        f"place:osm:{fold(p.name)}:{found.latitude:.2f}:{found.longitude:.2f}",
        kind="place",
        label=p.name,
        detail=f"{found.display_name}\nNo conflict history in the loaded data.",
        latitude=found.latitude,
        longitude=found.longitude,
        geo_basis="geocoded",
        quote=p.quote,
        created_by=by_ai,
        attributes={"geocoder": "OpenStreetMap Nominatim", "as_written": p.name},
    )


def _mention_reason(p, place: gazetteer.Place | None, node: BoardNode) -> dict[str, Any]:
    evidence = {"quote": p.quote, "as_written": p.name}
    if place is None:
        return {
            "reason": f"The article names {p.name}; located by OpenStreetMap search",
            "confidence": 0.7,
            "evidence": evidence,
        }
    if place.alternatives:
        evidence["alternatives"] = place.alternatives
        return {
            "reason": f"The article names {p.name}. {place.alternatives} other place(s) share "
            f"this name; this one ({place.country}) is nearest the story's other places",
            "confidence": 0.6,
            "evidence": evidence,
        }
    return {"reason": f"The article names {p.name}", "confidence": 0.9, "evidence": evidence}


def _locate_article(
    db: Session, node: BoardNode, places: list[BoardNode], body: str, countries: list[str]
) -> None:
    """Put the article at the first place it names (its dateline), else its main country."""
    if places:
        folded = fold(body)

        def first_mention(place: BoardNode) -> int:
            at = folded.find(fold(place.attributes.get("as_written", place.label)))
            return at if at >= 0 else len(folded)

        best = min(places, key=first_mention)
        node.latitude, node.longitude, node.geo_basis = best.latitude, best.longitude, "derived"
        return
    if countries:
        row = db.execute(
            text("SELECT latitude, longitude FROM risk_countries WHERE iso3 = :iso3"),
            {"iso3": countries[0]},
        ).first()
        if row is None or row.latitude is None:
            row = db.execute(
                text(
                    "SELECT avg(latitude) AS latitude, avg(longitude) AS longitude FROM events "
                    "WHERE country_iso3 = :iso3 AND geo_precision <> 'country'"
                ),
                {"iso3": countries[0]},
            ).first()
        if row is not None and row.latitude is not None:
            node.latitude, node.longitude = row.latitude, row.longitude
            node.geo_basis = "country"


def _singular(phrase: str) -> str:
    """'houthi rebels' -> 'houthi rebel', so plurals match; short words are left alone."""
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in phrase.split())


def resolve_actor(name: str, candidates: list[gazetteer.Actor]) -> list[str]:
    """Event-source actor names that an article's actor name refers to.

    An alias must be the name or a whole phrase within it, ignoring plurals. Nothing
    fuzzier: "Belarusian state forces" is one letter-run away from "Russian state
    forces" and means another army.
    """
    wanted = _singular(actor_key(fold(name).strip()) or "")
    matches = []
    for c in candidates:
        for alias in c.aliases:
            a = _singular(fold(alias))
            if a == wanted or re.search(rf"(?<![\w-]){re.escape(a)}(?![\w-])", wanted):
                matches.append(c.name)
                break
    return matches


def _actor_nodes(
    b: BoardBuilder,
    actors: list[ExtractedActor],
    countries: list[str],
    anchor: date,
    article_node: BoardNode,
    by_ai: str,
) -> list[BoardNode]:
    candidates = gazetteer.candidate_actors(b.db, countries[:3], anchor - timedelta(days=5 * 365))
    nodes = []
    for a in actors:
        key = actor_key(fold(a.name))
        if not key or key in GENERIC_ACTORS or key in country_words():
            continue
        db_names = resolve_actor(a.name, candidates)
        keys = sorted({actor_key(n) for n in db_names} | {key})
        codes = sorted({c for n in db_names for c in gdelt_codes(n)})
        node = b.node(
            f"actor:{key}",
            kind="actor",
            label=a.name,
            detail=("Matches " + "; ".join(db_names))
            if db_names
            else "No events in the loaded data name this actor.",
            geo_basis="derived",
            quote=a.quote,
            created_by=by_ai,
            attributes={
                "db_names": db_names,
                "db_keys": keys,
                "gdelt_codes": codes,
                "kind": a.kind,
            },
        )
        nodes.append(node)
        reason = f"The article names {a.name}"
        if db_names:
            reason += f" (in the event data as {db_names[0]}"
            reason += f" and {len(db_names) - 1} other name(s))" if len(db_names) > 1 else ")"
        b.link(
            article_node,
            node,
            "mentions",
            reason,
            0.85 if db_names else 0.7,
            {"quote": a.quote, "as_written": a.name, "db_names": db_names},
        )
    return nodes


def _link_near_events(
    b: BoardBuilder,
    origin: BoardNode,
    anchor: date,
    radius_km: float,
    start: date,
    end: date,
    window_days: int,
    limit: int,
    anchor_text: str,
    rule: str = "near",
    framing: str = "",
) -> None:
    if origin.latitude is None:
        return
    rows = rules.events_near(b.db, origin.latitude, origin.longitude, radius_km, start, end)
    room = max(0, b.settings.max_events - b.event_count())
    for row in rules.rank_events(rows, anchor, window_days, min(limit, room)):
        node = b.event_node(row)
        days = (row.event_date - anchor).days
        b.link(
            origin,
            node,
            rule,
            f"{framing}{row.label}, {rules.distance_text(row.distance_km)}, "
            f"{rules.when(days)} {anchor_text}",
            rules.near_confidence(row.distance_km, radius_km, days, window_days),
            {
                "distance_km": round(row.distance_km, 1),
                "days": days,
                "radius_km": radius_km,
                "window_days": window_days,
            },
        )


def _link_history(b: BoardBuilder, place: BoardNode, anchor: date) -> None:
    """Earlier violence at a place from UCDP and ACLED, before the lookback window."""
    s = b.settings
    if place.latitude is None:
        return
    end = anchor - timedelta(days=s.lookback_days + 1)
    start = end - timedelta(days=365 * s.history_years)
    rows = rules.events_near(
        b.db,
        place.latitude,
        place.longitude,
        s.place_radius_km,
        start,
        end,
        limit=300,
        sources=("ucdp", "acled"),
    )
    # Deadliest first, then most recent; the board wants the turning points.
    rows.sort(key=lambda r: (-(r.fatalities_best or 0), -(r.event_date.toordinal())))
    for row in rows[: s.history_per_place]:
        node = b.event_node(row)
        node.attributes = {**node.attributes, "history": True}
        days = (row.event_date - anchor).days
        b.link(
            place,
            node,
            "history",
            f"Earlier violence here: {row.label}, {rules.distance_text(row.distance_km)}, "
            f"{rules.when(days)} the article"
            + (f", {row.fatalities_best} reported deaths" if row.fatalities_best else ""),
            rules.history_confidence(days, row.fatalities_best or 0),
            {"distance_km": round(row.distance_km, 1), "days": days},
        )


def _link_actor_events(
    b: BoardBuilder,
    actor: BoardNode,
    anchor: date,
    start: date,
    end: date,
    region: list[tuple[float, float]],
) -> None:
    s = b.settings
    keys = actor.attributes.get("db_keys") or []
    codes = actor.attributes.get("gdelt_codes") or []
    rows = rules.events_by_actor(b.db, keys, start, end, gdelt_codes=codes)
    if region:
        for r in rows:
            r.distance_km = min(
                gazetteer.haversine_km(r.latitude, r.longitude, lat, lon) for lat, lon in region
            )
        rows = [r for r in rows if r.distance_km <= s.actor_region_km]
    room = max(0, s.max_events - b.event_count())
    for row in rules.rank_events(rows, anchor, s.lookback_days, min(s.events_per_actor, room)):
        node = b.event_node(row)
        days = (row.event_date - anchor).days
        named = next((a for a in (row.actor1, row.actor2) if a and actor_key(a) in keys), None)
        if named is None:
            # Matched by GDELT code, not by name.
            code = next(
                c
                for c in (row.attributes.get("actor1_code"), row.attributes.get("actor2_code"))
                if c in codes
            )
            how = f"GDELT codes an actor in this event as {code}"
            evidence = {"gdelt_code": code, "days": days}
        else:
            how = f"{rules.SOURCE_NAMES.get(row.source, row.source)} names {named} in this event"
            evidence = {"named_as": named, "days": days}
        b.link(
            actor,
            node,
            "same_actor",
            f"{how}, {rules.when(days)} the article's date",
            rules.actor_confidence(days, s.lookback_days),
            evidence,
        )


def _link_between_events(b: BoardBuilder) -> None:
    b.db.flush()
    events = {n.event_id: n for n in b.nodes.values() if n.kind == "event" and n.event_id}
    ids = list(events)
    for event_id, related_id, score, km, gap in rules.incident_links(b.db, ids):
        a, c = events[event_id], events[related_id]
        b.link(
            a,
            c,
            "same_incident",
            f"{a.source_name} and {c.source_name} report one incident "
            f"({km:.0f} km apart, {gap} day(s) apart)",
            float(score),
            {"distance_km": km, "day_gap": gap},
        )
    by_url: dict[str, list[BoardNode]] = {}
    for n in events.values():
        if n.attributes.get("source") == "gdelt" and n.source_url:
            by_url.setdefault(normalized_url(n.source_url) or n.source_url, []).append(n)
    for group in by_url.values():
        for a, c in zip(group, group[1:], strict=False):
            b.link(
                a,
                c,
                "co_reported",
                "GDELT coded both events from the same news report",
                0.6,
                {"url": a.source_url},
            )


def _link_observations(b: BoardBuilder, origins: list[BoardNode], anchor: date) -> None:
    """Recorded flights and fires near the story's places and violent events."""
    s = b.settings
    centre = at_midnight(anchor) + timedelta(hours=12)
    for origin in origins[:6]:
        if origin.latitude is None:
            continue
        around = origin.time_start + timedelta(hours=12) if origin.time_start else centre
        flights = rules.observations_near(
            b.db,
            "flight",
            origin.latitude,
            origin.longitude,
            s.flight_radius_km,
            around - timedelta(hours=s.flight_hours),
            around + timedelta(hours=s.flight_hours),
            limit=5,
        )
        for t in flights:
            node = b.track_node(t)
            hours = (t.start - around).total_seconds() / 3600
            b.link(
                origin,
                node,
                "near",
                f"Recorded within {t.closest_km:.0f} km of {origin.label}, "
                f"{abs(hours):.0f} h {'before' if hours < 0 else 'after'} midday that day",
                rules.near_confidence(
                    t.closest_km, s.flight_radius_km, hours / 24, s.flight_hours / 24
                ),
                {"distance_km": round(t.closest_km, 1), "hours": round(hours, 1)},
            )
    violent = [n for n in b.nodes.values() if n.kind == "event" and n.attributes.get("violent")][
        :30
    ]
    for origin in [*origins[:6], *violent]:
        if origin.latitude is None:
            continue
        day = rules.utc_day(origin.time_start) if origin.time_start else anchor
        fires = rules.observations_near(
            b.db,
            "fire",
            origin.latitude,
            origin.longitude,
            s.fire_radius_km,
            at_midnight(day - timedelta(days=s.fire_days)),
            at_midnight(day + timedelta(days=s.fire_days + 1)),
            limit=3,
        )
        for t in fires:
            node = b.track_node(t)
            days = (rules.utc_day(t.start) - day).days
            b.link(
                origin,
                node,
                "near",
                f"Satellite fire detection {rules.distance_text(t.closest_km)}, "
                f"{rules.when(days)} {origin.label}",
                rules.near_confidence(t.closest_km, s.fire_radius_km, days, s.fire_days),
                {"distance_km": round(t.closest_km, 1), "days": days},
            )


def _place_actors(b: BoardBuilder, actors: list[BoardNode], article_node: BoardNode) -> None:
    """Draw an actor at the middle of its events on the board, else beside the article."""
    for actor in actors:
        # Links are still pending here: they are written once every node has an id.
        linked = [c for a, c, f in b._pending_links if a is actor and f["rule"] == "same_actor"]
        points = [(n.latitude, n.longitude) for n in linked if n.latitude is not None]
        if points:
            actor.latitude, actor.longitude = _centre(points)
        elif article_node.latitude is not None:
            actor.latitude, actor.longitude = article_node.latitude, article_node.longitude


# --- Growing a board from one node ------------------------------------------------


def expand_node(
    db: Session, board: Board, node: BoardNode, settings: RuleSettings | None = None
) -> list[BoardNode]:
    """Suggest more connections around one node. Returns the nodes that are new."""
    b = BoardBuilder(db, board, settings)
    s = b.settings
    before = set(b.nodes)
    s.max_events = b.event_count() + 12
    anchor = (
        rules.utc_day(node.time_start)
        if node.time_start
        else board.anchor_date or datetime.now(UTC).date()
    )
    if node.kind in ("event", "claim", "place", "flight", "fire", "vessel", "note"):
        days = s.expand_days if node.kind in ("event", "claim") else s.lookback_days
        start, end = anchor - timedelta(days=days), anchor + timedelta(days=days)
        _link_near_events(
            b, node, anchor, s.expand_radius_km, start, end, days, 6, f"this {node.kind}"
        )
    if node.kind == "event" and node.event_id:
        _expand_event_actors(b, node)
        for _kept, duplicate in rules.duplicates_of(db, [node.event_id]):
            for row in rules.events_by_id(db, [duplicate]):
                other = b.event_node(row)
                b.link(
                    node,
                    other,
                    "same_incident",
                    f"{other.source_name} reports the same incident",
                    0.8,
                )
    if node.kind == "actor":
        # An analyst expanding a group wants its record, not only the last weeks: look
        # back as far as the history rule does (the curated sources lag by months).
        start, end = rules.window(anchor, 365 * s.history_years, s.lookahead_days)
        region = [
            (n.latitude, n.longitude)
            for n in b.nodes.values()
            if n.kind == "place" and n.latitude is not None
        ]
        s.events_per_actor = 8
        _link_actor_events(b, node, anchor, start, end, region)
    _link_between_events(b)
    if node.kind in ("event", "claim", "place"):
        _link_observations(b, [node], anchor)
    b.flush()
    return [n for k, n in b.nodes.items() if k not in before]


def _expand_event_actors(b: BoardBuilder, node: BoardNode) -> None:
    """Link an event to the actors its source names, adding actor nodes when new."""
    for name in node.attributes.get("actors", []):
        key = actor_key(name)
        if not key or key in GENERIC_ACTORS or key in country_words():
            continue
        actor = next(
            (
                n
                for n in b.nodes.values()
                if n.kind == "actor" and key in (n.attributes.get("db_keys") or [])
            ),
            None,
        )
        if actor is None:
            actor = b.node(
                f"actor:{key}",
                kind="actor",
                label=name,
                detail=f"Named by {node.source_name} in {node.label}",
                latitude=node.latitude,
                longitude=node.longitude,
                geo_basis="derived",
                created_by="rule",
                attributes={"db_names": [name], "db_keys": [key], "kind": "other"},
            )
        b.link(
            actor,
            node,
            "same_actor",
            f"{node.source_name} names {name} in this event",
            0.85,
            {"named_as": name},
        )


def board_nodes(db: Session, board_id: int) -> list[BoardNode]:
    return list(db.scalars(select(BoardNode).where(BoardNode.board_id == board_id)))

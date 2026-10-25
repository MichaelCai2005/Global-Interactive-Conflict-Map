"""ACLED (Armed Conflict Location & Event Data) CSVs.

Each row is one event of political violence, a demonstration, or a strategic development
(troop movements, arrests, territory changing hands), hand-coded weekly from news and local
partners. It sits between UCDP and GDELT: curated like UCDP, but it also records
non-lethal events like protests and riots, which makes it a good source of the signals that
come before violence. Files come from `ingest download acled` (the API) or the ACLED export
tool; both use the same column names.
Codebook: https://acleddata.com/knowledge-base/codebook/
"""

import csv
from collections.abc import Iterator
from datetime import date, datetime
from typing import TextIO

from app import conflict_type, countries
from app.ingest.common import (
    FieldErrors,
    NormalizedEvent,
    ParsedRow,
    clean_text,
    normalize_country,
    parse_float,
    parse_int,
    validate_event,
)

SOURCE = "acled"

REQUIRED_COLUMNS = {
    "event_id_cnty",
    "event_date",
    "event_type",
    "latitude",
    "longitude",
    "geo_precision",
    "country",
    "fatalities",
}

EVENT_TYPES = {
    "Battles": "battle",
    "Explosions/Remote violence": "explosion_remote_violence",
    "Violence against civilians": "violence_against_civilians",
    "Riots": "riot",
    "Protests": "protest",
    "Strategic developments": "strategic_development",
}
# Riots, protests and strategic developments are kept as signals, like GDELT's non-violent
# roots, so only organized violence is matched against UCDP.
VIOLENT_TYPES = {"Battles", "Explosions/Remote violence", "Violence against civilians"}

# geo_precision: 1 the named town, 2 part of a region with the nearest town used,
# 3 a larger region with its capital or centroid used.
GEO_PRECISION = {1: "exact", 2: "admin", 3: "admin"}

ATTRIBUTE_COLUMNS = (
    "sub_event_type",
    "disorder_type",
    "interaction",
    "inter1",
    "inter2",
    "assoc_actor_1",
    "assoc_actor_2",
    "civilian_targeting",
    "admin2",
    "admin3",
    "region",
    "iso",
    "time_precision",
    "source_scale",
    "tags",
    "notes",
    "source",
    "timestamp",
)


def parse(stream: TextIO) -> Iterator[ParsedRow]:
    reader = csv.DictReader(stream)
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"not an ACLED file, missing columns: {sorted(missing)}")
    for row_number, raw in enumerate(reader, start=2):
        yield parse_row(row_number, raw)


def parse_acled_date(value: str | None) -> date | None:
    """Accepts the API's '2022-02-24' and the export tool's '24 February 2022'."""
    value = clean_text(value)
    if value is None:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return datetime.strptime(value, "%d %B %Y").date()


def parse_row(row_number: int, raw: dict[str, str]) -> ParsedRow:
    errors = FieldErrors()
    event_id = errors.require(clean_text(raw.get("event_id_cnty")), "event_id_cnty")
    event_date = errors.require(
        errors.take(parse_acled_date, raw.get("event_date"), "event_date"), "event_date"
    )
    lat = errors.require(errors.take(parse_float, raw.get("latitude"), "latitude"), "latitude")
    lon = errors.require(errors.take(parse_float, raw.get("longitude"), "longitude"), "longitude")

    event_type = clean_text(raw.get("event_type"))
    if event_type is None:
        errors.append("missing event_type")
    elif event_type not in EVENT_TYPES:
        errors.append(f"unknown event_type: {event_type!r}")

    precision = errors.take(parse_int, raw.get("geo_precision"), "geo_precision")
    if precision is not None and precision not in GEO_PRECISION:
        errors.append(f"unknown geo_precision: {precision}")

    fatalities = errors.take(parse_int, raw.get("fatalities"), "fatalities")

    if errors:
        return ParsedRow(row_number, raw, reasons=list(errors))

    sources = clean_text(raw.get("source"))
    event = NormalizedEvent(
        source=SOURCE,
        source_event_id=event_id,
        dedupe_key=event_id,
        event_date=event_date,
        event_type=EVENT_TYPES[event_type],
        is_violent=event_type in VIOLENT_TYPES,
        conflict_type=conflict_type.classify_acled(
            EVENT_TYPES[event_type], clean_text(raw.get("inter1")), clean_text(raw.get("inter2"))
        )
        if event_type in VIOLENT_TYPES
        else None,
        latitude=lat,
        longitude=lon,
        geo_precision=GEO_PRECISION.get(precision, "exact"),
        country=normalize_country(raw.get("country")),
        country_iso3=countries.from_iso_numeric(raw.get("iso")),
        admin1=clean_text(raw.get("admin1")),
        location_name=clean_text(raw.get("location")),
        actor1=clean_text(raw.get("actor1")),
        actor2=clean_text(raw.get("actor2")),
        # ACLED gives one conservative count, not a range.
        fatalities_best=fatalities,
        # `source` lists the outlets an event was coded from, separated by semicolons.
        report_count=len([s for s in sources.split(";") if s.strip()]) if sources else 1,
        attributes={k: v for k in ATTRIBUTE_COLUMNS if (v := clean_text(raw.get(k)))},
    )
    reasons = validate_event(event)
    if reasons:
        return ParsedRow(row_number, raw, reasons=reasons)
    return ParsedRow(row_number, raw, event=event)

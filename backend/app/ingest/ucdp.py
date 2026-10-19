"""UCDP Georeferenced Event Dataset (GED) and UCDP Candidate CSVs.

Both share the same columns. Each row is one violent event that killed at least one
person, coded by Uppsala University from news and NGO reports.
Codebook: https://ucdp.uu.se/downloads/
"""

import csv
from collections.abc import Iterator
from typing import TextIO

from app.ingest.common import (
    FieldErrors,
    NormalizedEvent,
    ParsedRow,
    clean_text,
    normalize_country,
    parse_float,
    parse_int,
    parse_iso_date,
    validate_event,
)

SOURCE = "ucdp"

REQUIRED_COLUMNS = {
    "id",
    "type_of_violence",
    "date_start",
    "latitude",
    "longitude",
    "where_prec",
    "country",
    "best",
}

VIOLENCE_TYPES = {1: "state_based", 2: "non_state", 3: "one_sided"}

# where_prec: 1 exact place, 2 within 25 km, 3 second-order admin area, 4 first-order
# admin area, 5 part of a country, 6 whole country, 7 international waters or airspace.
WHERE_PRECISION = {1: "exact", 2: "exact", 3: "admin", 4: "admin", 5: "admin", 6: "country"}


def parse(stream: TextIO) -> Iterator[ParsedRow]:
    reader = csv.DictReader(stream)
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"not a UCDP GED file, missing columns: {sorted(missing)}")
    for row_number, raw in enumerate(reader, start=2):
        yield parse_row(row_number, raw)


def parse_row(row_number: int, raw: dict[str, str]) -> ParsedRow:
    errors = FieldErrors()
    event_id = errors.require(clean_text(raw.get("id")), "id")
    start = errors.require(
        errors.take(parse_iso_date, raw.get("date_start"), "date_start"), "date_start"
    )
    end = errors.take(parse_iso_date, raw.get("date_end"), "date_end")
    lat = errors.require(errors.take(parse_float, raw.get("latitude"), "latitude"), "latitude")
    lon = errors.require(errors.take(parse_float, raw.get("longitude"), "longitude"), "longitude")

    violence = errors.take(parse_int, raw.get("type_of_violence"), "type_of_violence")
    if violence is not None and violence not in VIOLENCE_TYPES:
        errors.append(f"unknown type_of_violence: {violence}")

    where_prec = errors.take(parse_int, raw.get("where_prec"), "where_prec")
    if where_prec == 7:
        errors.append("event at sea or in airspace (where_prec 7) has no land location")
    elif where_prec is not None and where_prec not in WHERE_PRECISION:
        errors.append(f"unknown where_prec: {where_prec}")

    best = errors.take(parse_int, raw.get("best"), "best")
    low = errors.take(parse_int, raw.get("low"), "low")
    high = errors.take(parse_int, raw.get("high"), "high")

    if errors:
        return ParsedRow(row_number, raw, reasons=list(errors))

    event = NormalizedEvent(
        source=SOURCE,
        source_event_id=event_id,
        dedupe_key=event_id,
        event_date=start,
        end_date=end,
        event_type=VIOLENCE_TYPES.get(violence, "unknown"),
        is_violent=True,
        latitude=lat,
        longitude=lon,
        geo_precision=WHERE_PRECISION.get(where_prec, "exact"),
        country=normalize_country(raw.get("country")),
        admin1=clean_text(raw.get("adm_1")),
        location_name=clean_text(raw.get("where_coordinates")),
        actor1=clean_text(raw.get("side_a")),
        actor2=clean_text(raw.get("side_b")),
        fatalities_best=best,
        fatalities_low=low,
        fatalities_high=high,
        # Informational only, so a malformed count falls back to 1 instead of rejecting.
        report_count=_lenient_int(raw.get("number_of_sources")) or 1,
        conflict_id=clean_text(raw.get("conflict_new_id")),
        attributes={
            k: v
            for k in ("conflict_name", "dyad_name", "where_description", "source_headline")
            if (v := clean_text(raw.get(k)))
        },
    )
    reasons = validate_event(event)
    if reasons:
        return ParsedRow(row_number, raw, reasons=reasons)
    return ParsedRow(row_number, raw, event=event)


def _lenient_int(value: str | None) -> int | None:
    try:
        return parse_int(value)
    except ValueError:
        return None

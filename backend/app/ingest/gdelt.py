"""GDELT event exports (tab-separated, no header row).

GDELT machine-codes world news into CAMEO events. It covers far more than violence,
including protests, threats and troop movements, which is what makes it useful as an
early signal ahead of the violence UCDP records. It is also noisy: the same incident shows
up once per article, so rows are collapsed by fingerprint before loading.

Three layouts exist and are told apart by column count:
  57 columns: GDELT 1.0 historical backfiles (1979 to March 2013)
  58 columns: GDELT 1.0 daily files (April 2013 onward), adds SOURCEURL
  61 columns: GDELT 2.0 15-minute files (2015 onward), adds ADM2 codes
Codebook: http://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf
"""

import csv
import sys
from collections.abc import Iterator
from typing import TextIO

from app.ingest.common import (
    FieldErrors,
    NormalizedEvent,
    ParsedRow,
    clean_text,
    normalize_country,
    parse_compact_date,
    parse_float,
    parse_int,
    validate_event,
)

SOURCE = "gdelt"

_ACTOR = [
    "Code", "Name", "CountryCode", "KnownGroupCode", "EthnicCode", "Religion1Code",
    "Religion2Code", "Type1Code", "Type2Code", "Type3Code",
]  # fmt: skip
_EVENT = [
    "IsRootEvent", "EventCode", "EventBaseCode", "EventRootCode", "QuadClass",
    "GoldsteinScale", "NumMentions", "NumSources", "NumArticles", "AvgTone",
]  # fmt: skip


def _geo(prefix: str, with_adm2: bool) -> list[str]:
    fields = ["Type", "FullName", "CountryCode", "ADM1Code"]
    fields += ["ADM2Code"] if with_adm2 else []
    fields += ["Lat", "Long", "FeatureID"]
    return [f"{prefix}Geo_{f}" for f in fields]


def _columns(with_adm2: bool) -> list[str]:
    return (
        ["GLOBALEVENTID", "SQLDATE", "MonthYear", "Year", "FractionDate"]
        + [f"Actor1{f}" for f in _ACTOR]
        + [f"Actor2{f}" for f in _ACTOR]
        + _EVENT
        + _geo("Actor1", with_adm2)
        + _geo("Actor2", with_adm2)
        + _geo("Action", with_adm2)
        + ["DATEADDED"]
    )


LAYOUTS = {
    57: _columns(with_adm2=False),
    58: _columns(with_adm2=False) + ["SOURCEURL"],
    61: _columns(with_adm2=True) + ["SOURCEURL"],
}

# CAMEO root codes 13-20 are the conflictual half of the scale. Codes 01-12 (statements,
# appeals, cooperation, aid) are dropped as out of scope, not rejected.
ROOT_EVENT_TYPES = {
    "13": "threat",
    "14": "protest",
    "15": "force_posture",
    "16": "reduce_relations",
    "17": "coercion",
    "18": "assault",
    "19": "fight",
    "20": "mass_violence",
}
VIOLENT_ROOTS = {"18", "19", "20"}

# ActionGeo_Type: 1 country, 2 US state, 3 US city, 4 world city, 5 world state (ADM1).
GEO_TYPE_PRECISION = {1: "country", 2: "admin", 3: "exact", 4: "exact", 5: "admin"}


def parse(stream: TextIO) -> Iterator[ParsedRow]:
    csv.field_size_limit(sys.maxsize)
    reader = csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
    for row_number, values in enumerate(reader, start=1):
        if not values or values == [""]:
            continue
        columns = LAYOUTS.get(len(values))
        if columns is None:
            yield ParsedRow(
                row_number,
                {"values": "\t".join(values)},
                reasons=[
                    f"unexpected column count {len(values)}, expected one of {sorted(LAYOUTS)}"
                ],
            )
            continue
        yield parse_row(row_number, dict(zip(columns, values, strict=True)))


def parse_row(row_number: int, raw: dict[str, str]) -> ParsedRow:
    root = clean_text(raw.get("EventRootCode"))
    if root is not None and root.zfill(2) not in ROOT_EVENT_TYPES:
        return ParsedRow(row_number, raw, filtered_out=True)

    errors = FieldErrors()
    event_id = errors.require(clean_text(raw.get("GLOBALEVENTID")), "GLOBALEVENTID")
    errors.require(root, "EventRootCode")
    event_date = errors.require(
        errors.take(parse_compact_date, raw.get("SQLDATE"), "SQLDATE"), "SQLDATE"
    )
    geo_type = errors.take(parse_int, raw.get("ActionGeo_Type"), "ActionGeo_Type")
    if not geo_type:
        errors.append("no action location (ActionGeo_Type 0 or empty)")
    elif geo_type not in GEO_TYPE_PRECISION:
        errors.append(f"unknown ActionGeo_Type: {geo_type}")
    lat = errors.require(
        errors.take(parse_float, raw.get("ActionGeo_Lat"), "ActionGeo_Lat"), "ActionGeo_Lat"
    )
    lon = errors.require(
        errors.take(parse_float, raw.get("ActionGeo_Long"), "ActionGeo_Long"), "ActionGeo_Long"
    )
    mentions = errors.take(parse_int, raw.get("NumMentions"), "NumMentions")
    tone = errors.take(parse_float, raw.get("AvgTone"), "AvgTone")
    goldstein = errors.take(parse_float, raw.get("GoldsteinScale"), "GoldsteinScale")

    if errors:
        return ParsedRow(row_number, raw, reasons=list(errors))

    root = root.zfill(2)
    event_code = clean_text(raw.get("EventCode")) or root
    actor1_code = clean_text(raw.get("Actor1Code")) or ""
    actor2_code = clean_text(raw.get("Actor2Code")) or ""
    place = clean_text(raw.get("ActionGeo_FullName"))
    # Many articles about one incident produce many rows that differ only in id and counts.
    fingerprint = "|".join(
        [event_date.isoformat(), event_code, actor1_code, actor2_code, f"{lat:.3f}", f"{lon:.3f}"]
    )

    event = NormalizedEvent(
        source=SOURCE,
        source_event_id=event_id,
        dedupe_key=fingerprint,
        event_date=event_date,
        event_type=ROOT_EVENT_TYPES[root],
        is_violent=root in VIOLENT_ROOTS,
        latitude=lat,
        longitude=lon,
        geo_precision=GEO_TYPE_PRECISION[geo_type],
        # FullName reads "City, Region, Country"; the last part is the country name.
        country=normalize_country(place.rsplit(",", 1)[-1]) if place else None,
        admin1=clean_text(raw.get("ActionGeo_ADM1Code")),
        location_name=place,
        actor1=clean_text(raw.get("Actor1Name")),
        actor2=clean_text(raw.get("Actor2Name")),
        report_count=max(mentions or 1, 1),
        tone=tone,
        source_url=clean_text(raw.get("SOURCEURL")),
        attributes={
            "cameo_code": event_code,
            "quad_class": clean_text(raw.get("QuadClass")),
            "goldstein": goldstein,
            "actor1_code": actor1_code or None,
            "actor2_code": actor2_code or None,
            "num_sources": clean_text(raw.get("NumSources")),
        },
    )
    reasons = validate_event(event)
    if reasons:
        return ParsedRow(row_number, raw, reasons=reasons)
    return ParsedRow(row_number, raw, event=event)

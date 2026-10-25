"""Shared event shape, field parsers and validation rules used by every source parser."""

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

GEO_PRECISIONS = ("exact", "admin", "country")
EARLIEST_DATE = date(1946, 1, 1)


@dataclass
class NormalizedEvent:
    source: str
    source_event_id: str
    dedupe_key: str
    event_date: date
    event_type: str
    is_violent: bool
    latitude: float
    longitude: float
    geo_precision: str
    end_date: date | None = None
    country: str | None = None
    # ISO 3166 alpha-3, mapped from the source's own country code (see app.countries).
    country_iso3: str | None = None
    admin1: str | None = None
    location_name: str | None = None
    actor1: str | None = None
    actor2: str | None = None
    fatalities_best: int | None = None
    fatalities_low: int | None = None
    fatalities_high: int | None = None
    report_count: int = 1
    tone: float | None = None
    source_url: str | None = None
    conflict_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    first_reported_at: datetime | None = None
    conflict_type: str | None = None


@dataclass
class ParsedRow:
    row_number: int
    raw: dict[str, str]
    event: NormalizedEvent | None = None
    reasons: list[str] = field(default_factory=list)
    # True when the row is valid but out of scope (e.g. GDELT cooperation events).
    filtered_out: bool = False


@dataclass
class IndicatorValue:
    """One country-year value of a structural indicator."""

    indicator: str
    iso3: str
    year: int
    value: float


@dataclass
class ParsedIndicatorRow:
    """The indicator counterpart of ParsedRow. One source row can carry several values
    (a V-Dem row holds every index for a country-year) or none (an EPR group's share is
    added into its country's totals, which travel on the country's first row)."""

    row_number: int
    raw: dict[str, str]
    values: list[IndicatorValue] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    # True when the row is valid but out of scope (regional aggregates, historical states).
    filtered_out: bool = False


class FieldErrors(list[str]):
    """Collects every problem with a row instead of stopping at the first one."""

    def take(self, parser, value: str | None, name: str):
        try:
            return parser(value)
        except (ValueError, TypeError):
            self.append(f"invalid {name}: {value!r}")
            return None

    def require(self, value, name: str):
        if value is None:
            self.append(f"missing {name}")
        return value


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


def parse_float(value: str | None) -> float | None:
    value = clean_text(value)
    return None if value is None else float(value)


def parse_int(value: str | None) -> int | None:
    value = clean_text(value)
    if value is None:
        return None
    number = float(value)
    if not number.is_integer():
        raise ValueError(value)
    return int(number)


def parse_iso_date(value: str | None) -> date | None:
    """Accepts '2022-03-01' and the '2022-03-01 00:00:00.000' form UCDP sometimes uses."""
    value = clean_text(value)
    return None if value is None else date.fromisoformat(value[:10])


def parse_compact_date(value: str | None) -> date | None:
    """GDELT's YYYYMMDD."""
    value = clean_text(value)
    return None if value is None else datetime.strptime(value, "%Y%m%d").date()


def parse_compact_timestamp(value: str | None) -> datetime | None:
    """GDELT 2.0's YYYYMMDDHHMMSS, in UTC. GDELT 1.0's day-only YYYYMMDD gives None."""
    value = clean_text(value)
    if value is None or len(value) != 14:
        return None
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)


_PARENTHETICAL = re.compile(r"\s*\(.*?\)")


def normalize_country(name: str | None) -> str | None:
    """Brings country names from different sources closer together.

    UCDP appends former names in parentheses ("Russia (Soviet Union)"); GDELT does not.
    """
    name = clean_text(name)
    if name is None:
        return None
    return clean_text(_PARENTHETICAL.sub("", name))


def validate_event(event: NormalizedEvent, today: date | None = None) -> list[str]:
    """Checks every source must pass, after source-specific parsing."""
    today = today or date.today()
    reasons = []
    if not -90 <= event.latitude <= 90:
        reasons.append(f"latitude out of range: {event.latitude}")
    if not -180 <= event.longitude <= 180:
        reasons.append(f"longitude out of range: {event.longitude}")
    if event.latitude == 0 and event.longitude == 0:
        reasons.append("coordinates are 0,0 (missing location written as zeros)")
    if event.event_date < EARLIEST_DATE:
        reasons.append(f"date before {EARLIEST_DATE}: {event.event_date}")
    # One day of slack for time zones between the source and this server.
    if event.event_date > today + timedelta(days=1):
        reasons.append(f"date in the future: {event.event_date}")
    if event.end_date and event.end_date < event.event_date:
        reasons.append(f"end date {event.end_date} before start date {event.event_date}")
    if event.geo_precision not in GEO_PRECISIONS:
        reasons.append(f"unknown location precision: {event.geo_precision}")
    deaths = [event.fatalities_low, event.fatalities_best, event.fatalities_high]
    if any(d is not None and d < 0 for d in deaths):
        reasons.append("negative fatality count")
    elif None not in deaths and not deaths[0] <= deaths[1] <= deaths[2]:
        reasons.append(f"fatalities not ordered low <= best <= high: {deaths}")
    return reasons

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_event_id: str
    event_date: date
    end_date: date | None
    event_type: str
    is_violent: bool
    country: str | None
    admin1: str | None
    location_name: str | None
    latitude: float
    longitude: float
    geo_precision: str
    actor1: str | None
    actor2: str | None
    fatalities_best: int | None
    fatalities_low: int | None
    fatalities_high: int | None
    report_count: int
    tone: float | None
    source_url: str | None
    conflict_id: str | None
    duplicate_of_id: int | None
    attributes: dict[str, Any]


class EventPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[EventOut]


class LinkedEvent(BaseModel):
    link_type: str
    distance_km: float
    day_gap: int
    score: float
    event: EventOut


class EventDetail(EventOut):
    duplicates: list[LinkedEvent]
    duplicate_of: LinkedEvent | None


class TimelineBucket(BaseModel):
    period: date
    violent_events: int
    signal_events: int
    fatalities: int


class Timeline(BaseModel):
    interval: Literal["day", "week", "month"]
    buckets: list[TimelineBucket]


class IngestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    filename: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    rows_read: int
    filtered_out: int
    rejected: int
    merged_in_file: int
    inserted: int
    updated: int
    cross_source_links: int
    error: str | None


class RejectedRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    row_number: int
    reasons: list[str]
    raw: dict[str, Any]

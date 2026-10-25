from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    country_iso3: str | None
    admin1: str | None
    location_name: str | None
    latitude: float
    longitude: float
    geo_precision: str
    priogrid_gid: int | None
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
    # When GDELT first published it; empty for UCDP and ACLED.
    first_reported_at: datetime | None


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


class EventSourceOut(BaseModel):
    """A news article that reported the event, or one of its duplicates."""

    model_config = ConfigDict(from_attributes=True)

    url: str
    source_name: str | None
    first_seen_at: datetime | None
    confidence: int | None


class EventDetail(EventOut):
    duplicates: list[LinkedEvent]
    duplicate_of: LinkedEvent | None
    # Articles found for this event and the events marked as its duplicates, oldest first.
    sources: list[EventSourceOut]
    source_count: int


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


class Facet(BaseModel):
    value: str
    count: int


class EventTypeFacet(Facet):
    is_violent: bool


class SourceFacet(Facet):
    # How current each source is: UCDP's monthly files lag weeks behind GDELT's daily ones.
    first_date: date | None
    last_date: date | None


class Facets(BaseModel):
    """What the data contains, for building filter controls."""

    sources: list[SourceFacet]
    event_types: list[EventTypeFacet]
    countries: list[Facet]
    first_date: date | None
    last_date: date | None


class CountrySummary(BaseModel):
    country: str
    violent_events: int
    signal_events: int
    fatalities: int
    # Where most of the country's events are (5th to 95th percentile), so a map can zoom
    # to it without being stretched by a few outlying points.
    bbox: tuple[float, float, float, float]


class MapLayer(BaseModel):
    """Events for the map: single points when there are few enough, otherwise grid cells."""

    mode: Literal["points", "grid"]
    total: int
    cell_size: float | None
    # A GeoJSON FeatureCollection, so map libraries can draw it directly.
    features: dict[str, Any]


class Summary(BaseModel):
    violent_events: int
    signal_events: int
    fatalities: int


Status = Literal["open", "in_progress", "done"]
Priority = Literal["low", "normal", "high"]


class WatchItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str | None = Field(None, max_length=128)
    bbox: str | None = Field(None, description="min_lon,min_lat,max_lon,max_lat")
    notes: str = ""

    @model_validator(mode="after")
    def check(self):
        if self.country is None and self.bbox is None:
            raise ValueError("a watch item needs a country or a bbox")
        if self.bbox is not None:
            parse_bbox(self.bbox)
        return self


class WatchItemPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    notes: str | None = None


class WatchItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    country: str | None
    bbox: str | None
    notes: str
    created_at: datetime


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str = ""
    status: Status = "open"
    priority: Priority = "normal"
    event_id: int | None = None
    watch_item_id: int | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    notes: str | None = None
    status: Status | None = None
    priority: Priority | None = None


class TaskEvent(BaseModel):
    """Enough about a task's event to label it without another request."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_date: date
    event_type: str
    country: str | None
    location_name: str | None
    latitude: float
    longitude: float


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    notes: str
    status: Status
    priority: Priority
    event_id: int | None
    watch_item_id: int | None
    event: TaskEvent | None
    created_at: datetime
    updated_at: datetime


def parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox.split(","))
    except ValueError:
        raise ValueError("bbox must be four numbers: min_lon,min_lat,max_lon,max_lat") from None
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError("bbox minimums must not exceed maximums")
    return min_lon, min_lat, max_lon, max_lat


class IndicatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    indicator: str
    iso3: str
    year: int
    value: float


class IndicatorInfo(BaseModel):
    source: str
    indicator: str
    description: str | None
    countries: int
    first_year: int
    last_year: int


class IndicatorPoint(BaseModel):
    value: float
    year: int


class CellMonthOut(BaseModel):
    """One PRIO-GRID cell in one month: what happened there and what came before."""

    model_config = ConfigDict(from_attributes=True)

    gid: int
    month: date
    iso3: str | None
    latitude: float
    longitude: float
    ucdp_events: int
    ucdp_fatalities: int
    violent_events: int
    acled_events: int
    acled_fatalities: int
    acled_protests: int
    acled_riots: int
    gdelt_threats: int
    gdelt_protests: int
    gdelt_force_posture: int
    gdelt_coercion: int
    gdelt_violence: int
    gdelt_mentions: int
    gdelt_tone: float | None
    ucdp_fatalities_last1m: int
    ucdp_fatalities_last3m: int
    ucdp_fatalities_last12m: int
    ucdp_fatalities_last36m: int
    months_since_violence: int | None
    neighbour_fatalities_last1m: int
    neighbour_fatalities_last12m: int
    gdelt_protests_last3m: int
    gdelt_threats_last3m: int
    # The cell's country's structural indicators ("vdem.v2x_polyarchy"...), each from the
    # latest year before this month's year, so a model never sees the year it predicts.
    indicators: dict[str, IndicatorPoint] = {}


class CellMonthPage(BaseModel):
    month: date
    total: int
    limit: int
    offset: int
    items: list[CellMonthOut]


class RiskPoints(BaseModel):
    """Points each component adds to a risk score; they sum to the score."""

    history: float
    surge: float
    spread: float
    signal: float


class RiskRegion(BaseModel):
    iso3: str
    name: str
    latitude: float | None
    longitude: float | None
    score: float
    change: float | None = Field(description="Score change since the previous week")
    points: RiskPoints
    trend: str | None = Field(
        description="new, intensifying, diminishing or persistent over the last 12 weeks"
    )
    surge_alarm: bool
    provisional: bool


class RiskWeek(BaseModel):
    week: date
    previous_week: date | None
    first_week: date
    last_week: date
    provisional: bool = Field(description="UCDP and ACLED do not wholly cover this week yet")
    regions: list[RiskRegion]
    weights: RiskPoints = Field(
        description="Most points each component can add, before parts with no data that week "
        "are left out and the rest scaled to 100"
    )
    weights_fitted: bool = Field(
        description="Weights fitted to the next four weeks' deaths by `python -m app.risk_model "
        "fit` (Signal excepted), rather than the hand-set starting point"
    )


class RiskPoint(BaseModel):
    week: date
    score: float
    change: float | None
    points: RiskPoints
    trend: str | None
    surge_alarm: bool
    provisional: bool
    violent_events: int
    deaths: int
    gdelt_events: int


class RiskSeries(BaseModel):
    iso3: str
    name: str
    neighbours: list[str]
    points: list[RiskPoint]


class RiskComponentChange(BaseModel):
    component: Literal["history", "surge", "spread", "signal"]
    points: float
    previous_points: float | None
    change: float | None
    explanation: str


class RiskNeighbour(BaseModel):
    iso3: str
    name: str
    score: float
    history: float


class RiskExplanation(BaseModel):
    """Why a country scored what it did in one week, and what changed since the week before."""

    iso3: str
    name: str
    week: date
    previous_week: date | None
    score: float
    previous_score: float | None
    change: float | None
    trend: str | None
    surge_alarm: bool
    provisional: bool
    summary: str
    components: list[RiskComponentChange] = Field(description="Biggest change first")
    events: list[EventOut] = Field(description="The week's deadliest and most reported events")
    neighbours: list[RiskNeighbour] = Field(
        description="Neighbours by decayed deaths, highest first"
    )

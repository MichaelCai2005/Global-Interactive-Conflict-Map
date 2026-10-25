from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session, aliased

from app.db import get_db
from app.models import Event, EventLink, EventSource
from app.schemas import (
    EventDetail,
    EventOut,
    EventPage,
    EventSourceOut,
    LinkedEvent,
    Timeline,
    TimelineBucket,
    parse_bbox,
)

router = APIRouter(tags=["events"])


class EventFilters(BaseModel):
    source: list[str] | None = None
    country: str | None = Field(None, description="Exact country name, case-insensitive")
    event_type: list[str] | None = None
    violent: bool | None = Field(None, description="true for violence, false for signals")
    conflict_id: str | None = None
    start: date | None = None
    end: date | None = None
    bbox: str | None = Field(None, description="min_lon,min_lat,max_lon,max_lat")
    reported_since: datetime | None = Field(
        None,
        description="Only events GDELT first published at or after this time (UCDP and"
        " ACLED have none)",
    )
    include_duplicates: bool = Field(
        False, description="Also return events already reported by a higher-priority source"
    )

    @model_validator(mode="after")
    def check(self):
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must be on or before end")
        if self.bbox is not None:
            self.bounds()
        return self

    def bounds(self) -> tuple[float, float, float, float] | None:
        return None if self.bbox is None else parse_bbox(self.bbox)

    def apply(self, query: Select) -> Select:
        if self.source:
            query = query.where(Event.source.in_(self.source))
        if self.country:
            query = query.where(func.lower(Event.country) == self.country.lower())
        if self.event_type:
            query = query.where(Event.event_type.in_(self.event_type))
        if self.violent is not None:
            query = query.where(Event.is_violent.is_(self.violent))
        if self.conflict_id:
            query = query.where(Event.conflict_id == self.conflict_id)
        if self.start:
            query = query.where(Event.event_date >= self.start)
        if self.end:
            query = query.where(Event.event_date <= self.end)
        if self.reported_since:
            query = query.where(Event.first_reported_at >= self.reported_since)
        if bounds := self.bounds():
            min_lon, min_lat, max_lon, max_lat = bounds
            query = query.where(
                Event.longitude.between(min_lon, max_lon), Event.latitude.between(min_lat, max_lat)
            )
        if not self.include_duplicates:
            query = query.where(Event.duplicate_of_id.is_(None))
        # GDELT "violence" from articles about something else, ordinary crime, or a story
        # placed at its Washington dateline; see app.ingest.gdelt_screen.
        return query.where(Event.screened_out.is_(None))


# FastAPI reads a query model only when it is the endpoint's sole query parameter, so each
# endpoint's extra parameters live on a subclass.
class EventQuery(EventFilters):
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
    sort: Literal["date", "fatalities", "reports"] = Field(
        "date", description="Newest, deadliest or most reported first"
    )


class TimelineQuery(EventFilters):
    interval: Literal["day", "week", "month"] = "week"


Db = Annotated[Session, Depends(get_db)]


@router.get("/events", response_model=EventPage)
def list_events(params: Annotated[EventQuery, Query()], db: Db):
    query = params.apply(select(Event))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    order = [Event.event_date.desc(), Event.id]
    if params.sort == "fatalities":
        order.insert(0, Event.fatalities_best.desc().nulls_last())
    elif params.sort == "reports":
        order.insert(0, Event.report_count.desc())
    rows = db.scalars(query.order_by(*order).limit(params.limit).offset(params.offset))
    return EventPage(total=total, limit=params.limit, offset=params.offset, items=list(rows))


@router.get("/events/{event_id}", response_model=EventDetail)
def get_event(event_id: int, db: Db):
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(404, "event not found")

    other = aliased(Event)
    duplicates = db.execute(
        select(EventLink, other)
        .join(other, other.id == EventLink.event_id)
        .where(EventLink.related_event_id == event_id)
        .order_by(EventLink.score.desc())
    ).all()
    canonical = db.execute(
        select(EventLink, other)
        .join(other, other.id == EventLink.related_event_id)
        .where(EventLink.event_id == event_id)
        .order_by(EventLink.score.desc())
        .limit(1)
    ).first()

    def linked(link: EventLink, linked_event: Event) -> LinkedEvent:
        return LinkedEvent(
            link_type=link.link_type,
            distance_km=link.distance_km,
            day_gap=link.day_gap,
            score=link.score,
            event=EventOut.model_validate(linked_event),
        )

    reporting = [event_id, *(e.id for _, e in duplicates)]
    sources = db.scalars(
        select(EventSource)
        .where(EventSource.event_id.in_(reporting))
        .order_by(EventSource.first_seen_at.nulls_last(), EventSource.id)
        .limit(SOURCES_SHOWN)
    ).all()
    source_count = db.scalar(
        select(func.count(func.distinct(EventSource.url))).where(
            EventSource.event_id.in_(reporting)
        )
    )
    return EventDetail(
        **EventOut.model_validate(event).model_dump(),
        duplicates=[linked(link, e) for link, e in duplicates],
        duplicate_of=linked(*canonical) if canonical else None,
        sources=_unique_urls(sources),
        source_count=source_count or 0,
    )


# A UCDP event can have dozens of GDELT duplicates, each with up to 50 articles.
SOURCES_SHOWN = 200


def _unique_urls(sources: list[EventSource]) -> list[EventSourceOut]:
    """One entry per article, though several duplicates may list it."""
    seen: dict[str, EventSourceOut] = {}
    for s in sources:
        seen.setdefault(s.url, EventSourceOut.model_validate(s))
    return list(seen.values())


@router.get("/timeline", response_model=Timeline)
def timeline(params: Annotated[TimelineQuery, Query()], db: Db):
    """Violent events, non-violent signals and deaths per period, to see how a conflict builds."""
    period = func.date_trunc(params.interval, Event.event_date).cast(Event.event_date.type)
    query = params.apply(
        select(
            period.label("period"),
            func.count().filter(Event.is_violent).label("violent_events"),
            func.count().filter(Event.is_violent.is_(False)).label("signal_events"),
            func.coalesce(
                func.sum(case((Event.is_violent, Event.fatalities_best), else_=0)), 0
            ).label("fatalities"),
        )
    ).group_by(period)
    rows = db.execute(query.order_by(period)).all()
    return Timeline(
        interval=params.interval, buckets=[TimelineBucket(**row._mapping) for row in rows]
    )

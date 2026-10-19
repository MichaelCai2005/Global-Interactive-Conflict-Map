from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import Float, case, func, select
from sqlalchemy.orm import Session

from app.api.events import EventFilters
from app.db import get_db
from app.models import Event
from app.schemas import CountrySummary, EventTypeFacet, Facet, Facets, MapLayer, Summary

router = APIRouter(tags=["map"])
Db = Annotated[Session, Depends(get_db)]

EPOCH = date(1970, 1, 1).toordinal()


class MapQuery(EventFilters):
    max_points: int = Field(
        15_000, ge=1, le=50_000, description="Above this many events, return grid cells instead"
    )
    cell: float = Field(1.0, gt=0, le=10, description="Grid cell size in degrees")


@router.get("/map", response_model=MapLayer)
def map_layer(params: Annotated[MapQuery, Query()], db: Db):
    """Events as GeoJSON points, or counted into grid cells when there are too many to draw."""
    total = db.scalar(params.apply(select(func.count()).select_from(Event)))
    if total <= params.max_points:
        rows = db.execute(
            params.apply(
                select(
                    Event.id,
                    Event.longitude,
                    Event.latitude,
                    Event.event_date,
                    Event.event_type,
                    Event.is_violent,
                    Event.fatalities_best,
                    Event.source,
                    Event.geo_precision,
                )
            ).order_by(Event.event_date, Event.id)
        )
        features = [
            point(
                r.longitude,
                r.latitude,
                id=r.id,
                date=r.event_date.isoformat(),
                # Days since 1970-01-01, so map styles can fade events by age.
                day=r.event_date.toordinal() - EPOCH,
                type=r.event_type,
                violent=r.is_violent,
                deaths=r.fatalities_best or 0,
                source=r.source,
                precision=r.geo_precision,
            )
            for r in rows
        ]
        return MapLayer(mode="points", total=total, cell_size=None, features=collection(features))

    col = func.floor(Event.longitude / params.cell)
    row = func.floor(Event.latitude / params.cell)
    cells = db.execute(
        params.apply(
            select(
                # Each cell sits at the average position of its events rather than the cell
                # centre, so the grid does not show through as a lattice.
                func.avg(Event.longitude).label("lon"),
                func.avg(Event.latitude).label("lat"),
                func.count().label("events"),
                func.count().filter(Event.is_violent).label("violent"),
                func.coalesce(
                    func.sum(case((Event.is_violent, Event.fatalities_best), else_=0)), 0
                ).label("deaths"),
            )
        ).group_by(col, row)
    )
    features = [
        point(
            c.lon,
            c.lat,
            events=c.events,
            violent=c.violent,
            signals=c.events - c.violent,
            deaths=c.deaths,
        )
        for c in cells
    ]
    return MapLayer(mode="grid", total=total, cell_size=params.cell, features=collection(features))


def point(lon: float, lat: float, **properties) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        "properties": properties,
    }


def collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


@router.get("/summary", response_model=Summary)
def summary(params: Annotated[EventFilters, Query()], db: Db):
    """Totals under the filters, e.g. to compare one time window with the one before it."""
    row = db.execute(
        params.apply(
            select(
                func.count().filter(Event.is_violent).label("violent_events"),
                func.count().filter(Event.is_violent.is_(False)).label("signal_events"),
                func.coalesce(
                    func.sum(case((Event.is_violent, Event.fatalities_best), else_=0)), 0
                ).label("fatalities"),
            )
        )
    ).one()
    return Summary(**row._mapping)


@router.get("/facets", response_model=Facets)
def facets(db: Db):
    """Sources, event types and countries in the data, with counts, for filter controls."""
    canonical = Event.duplicate_of_id.is_(None)

    def counts(*columns):
        return db.execute(
            select(*columns, func.count())
            .where(canonical, columns[0].is_not(None))
            .group_by(*columns)
            .order_by(func.count().desc(), columns[0])
        ).all()

    first, last = db.execute(
        select(func.min(Event.event_date), func.max(Event.event_date)).where(canonical)
    ).one()
    return Facets(
        sources=[Facet(value=v, count=n) for v, n in counts(Event.source)],
        event_types=[
            EventTypeFacet(value=v, is_violent=violent, count=n)
            for v, violent, n in counts(Event.event_type, Event.is_violent)
        ],
        countries=[Facet(value=v, count=n) for v, n in counts(Event.country)],
        first_date=first,
        last_date=last,
    )


class CountryQuery(EventFilters):
    limit: int = Field(25, ge=1, le=300)


@router.get("/countries", response_model=list[CountrySummary])
def countries(params: Annotated[CountryQuery, Query()], db: Db):
    """Countries with the most events under the filters, busiest first."""

    def pct(fraction: float, column):
        return func.percentile_cont(fraction).within_group(column).cast(Float)

    rows = db.execute(
        params.apply(
            select(
                Event.country,
                func.count().filter(Event.is_violent).label("violent_events"),
                func.count().filter(Event.is_violent.is_(False)).label("signal_events"),
                func.coalesce(
                    func.sum(case((Event.is_violent, Event.fatalities_best), else_=0)), 0
                ).label("fatalities"),
                pct(0.05, Event.longitude).label("min_lon"),
                pct(0.05, Event.latitude).label("min_lat"),
                pct(0.95, Event.longitude).label("max_lon"),
                pct(0.95, Event.latitude).label("max_lat"),
            ).where(Event.country.is_not(None))
        )
        .group_by(Event.country)
        .order_by(func.count().desc(), Event.country)
        .limit(params.limit)
    ).all()
    return [
        CountrySummary(
            country=r.country,
            violent_events=r.violent_events,
            signal_events=r.signal_events,
            fatalities=r.fatalities,
            bbox=(r.min_lon, r.min_lat, r.max_lon, r.max_lat),
        )
        for r in rows
    ]

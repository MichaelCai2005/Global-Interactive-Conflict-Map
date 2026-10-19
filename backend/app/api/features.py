from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.features import cell_centre
from app.ingest.loader import INDICATOR_NAMES
from app.models import CellMonth, CountryIndicator
from app.schemas import (
    CellMonthOut,
    CellMonthPage,
    IndicatorInfo,
    IndicatorOut,
    IndicatorPoint,
    parse_bbox,
)

router = APIRouter(tags=["features"])
Db = Annotated[Session, Depends(get_db)]

# Cell centres from PRIO-GRID ids: 720 cells to a row, numbered from (-180, -90).
CELL_LAT = ((CellMonth.gid - 1) // 720) * 0.5 - 89.75
CELL_LON = ((CellMonth.gid - 1) % 720) * 0.5 - 179.75


class CellQuery(BaseModel):
    month: date = Field(description="Any day in the month, or YYYY-MM")
    iso3: str | None = Field(None, min_length=3, max_length=3)
    bbox: str | None = Field(None, description="min_lon,min_lat,max_lon,max_lat")
    limit: int = Field(5000, ge=1, le=50_000)
    offset: int = Field(0, ge=0)

    @field_validator("month", mode="before")
    @classmethod
    def month_start(cls, value):
        if isinstance(value, str) and len(value) == 7:
            value += "-01"
        return value

    @field_validator("bbox")
    @classmethod
    def check_bbox(cls, value):
        if value is not None:
            parse_bbox(value)
        return value


@router.get("/features/cells", response_model=CellMonthPage)
def cell_months(params: Annotated[CellQuery, Query()], db: Db):
    """Cell-month features for one month, with each cell's country indicators attached.

    Built by `python -m app.ingest build-features`; cells with no rows had no events then
    or in the 36 months before.
    """
    month = params.month.replace(day=1)
    query = select(CellMonth).where(CellMonth.month == month)
    if params.iso3:
        query = query.where(CellMonth.iso3 == params.iso3.upper())
    if params.bbox:
        min_lon, min_lat, max_lon, max_lat = parse_bbox(params.bbox)
        query = query.where(CELL_LON.between(min_lon, max_lon), CELL_LAT.between(min_lat, max_lat))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    cells = db.scalars(
        query.order_by(CellMonth.gid).limit(params.limit).offset(params.offset)
    ).all()

    indicators = _latest_indicators(db, {c.iso3 for c in cells if c.iso3}, month.year - 1)
    items = []
    for cell in cells:
        latitude, longitude = cell_centre(cell.gid)
        values = {c.name: getattr(cell, c.name) for c in CellMonth.__table__.columns}
        items.append(
            CellMonthOut(
                **values,
                latitude=latitude,
                longitude=longitude,
                indicators=indicators.get(cell.iso3, {}),
            )
        )
    return CellMonthPage(
        month=month, total=total, limit=params.limit, offset=params.offset, items=items
    )


def _latest_indicators(
    db: Session, iso3s: set[str], up_to_year: int
) -> dict[str, dict[str, IndicatorPoint]]:
    """Each country's most recent value of every indicator, from up_to_year or before."""
    if not iso3s:
        return {}
    rows = db.execute(
        text("""
            SELECT DISTINCT ON (iso3, source, indicator) iso3, source, indicator, year, value
            FROM country_indicators
            WHERE iso3 = ANY(:iso3s) AND year <= :year
            ORDER BY iso3, source, indicator, year DESC
        """),
        {"iso3s": sorted(iso3s), "year": up_to_year},
    )
    result: dict[str, dict[str, IndicatorPoint]] = {}
    for iso3, source, indicator, year, value in rows:
        result.setdefault(iso3, {})[f"{source}.{indicator}"] = IndicatorPoint(
            value=value, year=year
        )
    return result


@router.get("/indicators", response_model=list[IndicatorOut])
def indicators(
    db: Db,
    iso3: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    source: str | None = None,
    indicator: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    limit: Annotated[int, Query(ge=1, le=10_000)] = 1000,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Country-year structural indicators from WDI, V-Dem and EPR."""
    if start_year and end_year and start_year > end_year:
        raise HTTPException(422, "start_year must be on or before end_year")
    query = select(CountryIndicator)
    if iso3:
        query = query.where(CountryIndicator.iso3 == iso3.upper())
    if source:
        query = query.where(CountryIndicator.source == source)
    if indicator:
        query = query.where(CountryIndicator.indicator == indicator)
    if start_year:
        query = query.where(CountryIndicator.year >= start_year)
    if end_year:
        query = query.where(CountryIndicator.year <= end_year)
    order = (
        CountryIndicator.iso3,
        CountryIndicator.source,
        CountryIndicator.indicator,
        CountryIndicator.year,
    )
    return db.scalars(query.order_by(*order).limit(limit).offset(offset)).all()


@router.get("/indicators/catalog", response_model=list[IndicatorInfo])
def indicator_catalog(db: Db):
    """Which indicators are loaded, what they measure, and the years they cover."""
    rows = db.execute(
        select(
            CountryIndicator.source,
            CountryIndicator.indicator,
            func.count(func.distinct(CountryIndicator.iso3)),
            func.min(CountryIndicator.year),
            func.max(CountryIndicator.year),
        )
        .group_by(CountryIndicator.source, CountryIndicator.indicator)
        .order_by(CountryIndicator.source, CountryIndicator.indicator)
    ).all()
    return [
        IndicatorInfo(
            source=source,
            indicator=indicator,
            description=INDICATOR_NAMES.get(source, {}).get(indicator),
            countries=countries,
            first_year=first,
            last_year=last,
        )
        for source, indicator, countries, first, last in rows
    ]

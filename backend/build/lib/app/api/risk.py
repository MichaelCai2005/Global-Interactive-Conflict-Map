from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app import risk as scoring
from app.db import get_db
from app.models import Event, RiskCountry, RiskScore
from app.risk import CUSUM_ALARM, FULL_HISTORY, HALF_LIFE_WEEKS, monday
from app.schemas import (
    EventOut,
    RiskComponentChange,
    RiskExplanation,
    RiskNeighbour,
    RiskPoint,
    RiskPoints,
    RiskRegion,
    RiskSeries,
    RiskWeek,
)

router = APIRouter(tags=["risk"])
Db = Annotated[Session, Depends(get_db)]

LABELS = {"history": "History", "surge": "Surge", "spread": "Spread", "signal": "Signal"}


def points(s: RiskScore) -> RiskPoints:
    return RiskPoints(
        history=s.points_history,
        surge=s.points_surge,
        spread=s.points_spread,
        signal=s.points_signal,
    )


def week_range(db: Session) -> tuple[date, date]:
    first, last = db.execute(select(func.min(RiskScore.week), func.max(RiskScore.week))).one()
    if first is None:
        raise HTTPException(404, "no risk scores yet; run `python -m app.risk build`")
    return first, last


def get_country(db: Session, iso3: str) -> RiskCountry:
    country = db.get(RiskCountry, iso3.upper())
    if country is None:
        raise HTTPException(404, "country has no risk scores")
    return country


@router.get("/risk", response_model=RiskWeek)
def risk_week(
    db: Db,
    week: Annotated[
        date | None, Query(description="Any day in the week; the latest week when left out")
    ] = None,
    sort: Annotated[
        Literal["score", "rise", "fall"], Query(description="Highest score, biggest rise or fall")
    ] = "score",
    limit: Annotated[int, Query(ge=1, le=300)] = 300,
):
    """Every country with a non-zero score in one week, for colouring the map at a point on the timeline."""
    first, last = week_range(db)
    current = min(max(monday(week), first), last) if week else last
    previous = current - timedelta(weeks=1) if current > first else None
    prev = aliased(RiskScore)
    change = RiskScore.score - prev.score
    order = {
        "score": [RiskScore.score.desc()],
        "rise": [change.desc().nulls_last(), RiskScore.score.desc()],
        "fall": [change.asc().nulls_last(), RiskScore.score.desc()],
    }[sort]
    rows = db.execute(
        select(RiskScore, RiskCountry, prev.score)
        .join(RiskCountry, RiskCountry.iso3 == RiskScore.iso3)
        .outerjoin(prev, (prev.iso3 == RiskScore.iso3) & (prev.week == previous))
        .where(RiskScore.week == current, (RiskScore.score > 0) | (prev.score > 0))
        .order_by(*order, RiskScore.iso3)
        .limit(limit)
    ).all()
    regions = [
        RiskRegion(
            iso3=c.iso3,
            name=c.name,
            latitude=c.latitude,
            longitude=c.longitude,
            score=s.score,
            change=None if prev_score is None else s.score - prev_score,
            points=points(s),
            trend=s.trend,
            surge_alarm=s.surge_alarm,
            provisional=s.provisional,
        )
        for s, c, prev_score in rows
    ]
    provisional = db.scalar(select(RiskScore.provisional).where(RiskScore.week == current).limit(1))
    return RiskWeek(
        week=current,
        previous_week=previous,
        first_week=first,
        last_week=last,
        provisional=bool(provisional),
        regions=regions,
        weights=RiskPoints(**scoring.WEIGHTS),
        weights_fitted=scoring.WEIGHTS != scoring.HAND_SET_WEIGHTS,
    )


@router.get("/risk/{iso3}", response_model=RiskSeries)
def risk_series(iso3: str, db: Db, start: date | None = None, end: date | None = None):
    """One country's weekly score and its four components, for a chart under the timeline."""
    country = get_country(db, iso3)
    query = select(RiskScore).where(RiskScore.iso3 == country.iso3).order_by(RiskScore.week)
    if start:
        # One week earlier, so the first week returned still has a change.
        query = query.where(RiskScore.week >= monday(start) - timedelta(weeks=1))
    if end:
        query = query.where(RiskScore.week <= end)
    scores = list(db.scalars(query))
    series = [
        RiskPoint(
            week=s.week,
            score=s.score,
            change=s.score - before.score if before else None,
            points=points(s),
            trend=s.trend,
            surge_alarm=s.surge_alarm,
            provisional=s.provisional,
            violent_events=s.violent_events,
            deaths=s.deaths,
            gdelt_events=s.gdelt_events,
        )
        for before, s in zip([None, *scores[:-1]], scores, strict=True)
    ]
    if start:
        series = [p for p in series if p.week >= monday(start)]
    return RiskSeries(
        iso3=country.iso3, name=country.name, neighbours=country.neighbours, points=series
    )


@router.get("/risk/{iso3}/weeks/{week}", response_model=RiskExplanation)
def explain_week(iso3: str, week: date, db: Db):
    """Why a country scored what it did in one week: each component's change and the events behind it."""
    country = get_country(db, iso3)
    current = monday(week)
    now = db.get(RiskScore, (country.iso3, current))
    if now is None:
        raise HTTPException(404, "no risk score for that week")
    previous_week = current - timedelta(weeks=1)
    before = db.get(RiskScore, (country.iso3, previous_week))

    neighbours = db.execute(
        select(RiskScore, RiskCountry.name)
        .join(RiskCountry, RiskCountry.iso3 == RiskScore.iso3)
        .where(RiskScore.iso3.in_(country.neighbours), RiskScore.week == current)
        .order_by(RiskScore.history.desc())
        .limit(5)
    ).all()
    near = [
        RiskNeighbour(iso3=s.iso3, name=n, score=s.score, history=s.history) for s, n in neighbours
    ]

    now_points, before_points = points(now), points(before) if before else None
    components = [
        RiskComponentChange(
            component=name,
            points=getattr(now_points, name),
            previous_points=getattr(before_points, name) if before_points else None,
            change=getattr(now_points, name) - getattr(before_points, name)
            if before_points
            else None,
            explanation=explain(name, now, near),
        )
        for name in LABELS
    ]
    components.sort(key=lambda c: abs(c.change or 0), reverse=True)

    events = db.scalars(
        select(Event)
        .where(
            Event.country_iso3 == country.iso3,
            Event.event_date.between(current, current + timedelta(days=6)),
            Event.duplicate_of_id.is_(None),
        )
        .order_by(
            Event.is_violent.desc(),
            Event.fatalities_best.desc().nulls_last(),
            Event.report_count.desc(),
            Event.id,
        )
        .limit(8)
    )
    change = now.score - before.score if before else None
    return RiskExplanation(
        iso3=country.iso3,
        name=country.name,
        week=current,
        previous_week=previous_week if before else None,
        score=now.score,
        previous_score=before.score if before else None,
        change=change,
        trend=now.trend,
        surge_alarm=now.surge_alarm,
        provisional=now.provisional,
        summary=summarise(now, change, components),
        components=components,
        events=[EventOut.model_validate(e) for e in events],
        neighbours=near,
    )


def summarise(now: RiskScore, change: float | None, components: list[RiskComponentChange]) -> str:
    text = f"Score {now.score:.0f}"
    if change is not None:
        text += f" ({change:+.0f} on the week before)"
        top = components[0]
        if top.change is not None and abs(top.change) >= 1:
            verb = "rose" if top.change > 0 else "fell"
            text += f". {LABELS[top.component]} {verb} most ({top.change:+.0f} points): "
            text += top.explanation[0].lower() + top.explanation[1:]
        else:
            text += ". No component moved by a point or more"
    if not text.endswith("."):
        text += "."
    if now.trend:
        text += f" Trend over 12 weeks: {now.trend}."
    if now.provisional:
        text += (
            " Provisional: UCDP and ACLED do not cover this week yet, so History only decays"
            " and Surge is left out."
        )
    return text


def explain(name: str, s: RiskScore, near: list[RiskNeighbour]) -> str:
    if name == "history":
        return (
            f"{s.deaths:,} deaths this week; {s.history:,.0f} after decay with a "
            f"{HALF_LIFE_WEEKS}-week half-life ({FULL_HISTORY:,.0f} scores in full)."
        )
    if name == "surge":
        if s.surge_z is None:
            return "No source covers this week with a year of history behind it."
        text = (
            f"{s.surge_events:,} {s.surge_source.upper()} violent events against a usual "
            f"{s.surge_baseline:.1f} a week "
            f"(z = {s.surge_z:+.1f}); accumulated excess {s.surge:.1f}"
        )
        alarm = "above" if s.surge_alarm else "below"
        return text + f", {alarm} the alarm level of {CUSUM_ALARM:.0f}."
    if name == "spread":
        if not near:
            return "No neighbouring countries with recorded events."
        top = near[0]
        return (
            f"Neighbours average {s.spread:,.0f} decayed deaths, led by {top.name} "
            f"({top.history:,.0f})."
        )
    parts = [
        f"{label} z = {z:+.1f}"
        for label, z in (
            ("share of world conflict news", s.share_z),
            ("Goldstein", s.goldstein_z),
            ("tone", s.tone_z),
        )
        if z is not None
    ]
    if not parts:
        return "Too little GDELT coverage for a baseline."
    return (
        "GDELT " + ", ".join(parts) + " against this country's usual level "
        "(a lower Goldstein score or tone is more hostile)."
    )

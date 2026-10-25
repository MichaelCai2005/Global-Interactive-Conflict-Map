from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import risk as scoring
from app.db import get_db
from app.models import Event, RiskCountry, RiskScore
from app.risk import COMPONENTS, CUSUM_ALARM, FULL_HISTORY, HALF_LIFE_WEEKS, monday
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
# Scores show as whole points, so less than half a point is no score and no change. History
# halves every 26 weeks but never reaches zero, so a country with one death decades ago
# still scores a few billionths of a point.
MIN_POINTS = 0.5


def points(s: RiskScore) -> RiskPoints:
    return RiskPoints(
        history=s.points_history,
        surge=s.points_surge,
        spread=s.points_spread,
        signal=s.points_signal,
    )


def points_before(before: RiskScore, then: frozenset[str], now: frozenset[str]) -> RiskPoints:
    """The week before's points, scored from this week's parts when the two weeks' differ."""
    if then == now:
        return points(before)
    return RiskPoints(**scoring.points_for(scoring.levels(before), now))


def score_before(before: RiskScore, then: frozenset[str], now: frozenset[str]) -> float:
    """The week before's score, to compare with this week's like with like."""
    return before.score if then == now else scoring.score_for(scoring.levels(before), now)


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
    """Every country with a score in one week, for colouring the map at a point on the timeline.

    Rising and falling keep only the countries whose score rose or fell, in the newest week
    UCDP and ACLED wholly cover at the latest: after it deaths are missing, so scores only fade.
    """
    first, last = week_range(db)
    current = min(max(monday(week), first), last) if week else last
    if sort != "score":
        covered = db.scalar(select(func.max(RiskScore.week)).where(~RiskScore.provisional))
        current = min(current, covered or current)
    previous = current - timedelta(weeks=1) if current > first else None
    rows = db.execute(
        select(RiskScore, RiskCountry)
        .join(RiskCountry, RiskCountry.iso3 == RiskScore.iso3)
        .where(RiskScore.week == current)
    ).all()
    before = {}
    if previous:
        before = {
            s.iso3: s for s in db.scalars(select(RiskScore).where(RiskScore.week == previous))
        }
    parts = scoring.parts_by_week(db, previous or current, current)

    regions = []
    for s, c in rows:
        then = before.get(s.iso3)
        prev_score = score_before(then, parts[then.week], parts[current]) if then else None
        if s.score < MIN_POINTS and (prev_score is None or prev_score < MIN_POINTS):
            continue
        change = None if prev_score is None else s.score - prev_score
        if sort != "score" and (change is None or abs(change) < MIN_POINTS):
            continue
        if (sort == "rise" and change < 0) or (sort == "fall" and change > 0):
            continue
        regions.append(
            RiskRegion(
                iso3=c.iso3,
                name=c.name,
                latitude=c.latitude,
                longitude=c.longitude,
                score=s.score,
                change=change,
                points=points(s),
                trend=s.trend,
                surge_alarm=s.surge_alarm,
                provisional=s.provisional,
            )
        )
    regions.sort(
        key={
            "score": lambda r: (-r.score, r.iso3),
            "rise": lambda r: (-r.change, -r.score, r.iso3),
            "fall": lambda r: (r.change, -r.score, r.iso3),
        }[sort]
    )
    return RiskWeek(
        week=current,
        previous_week=previous,
        first_week=first,
        last_week=last,
        provisional=any(s.provisional for s, _ in rows),
        regions=regions[:limit],
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
    parts = scoring.parts_by_week(db, scores[0].week, scores[-1].week) if scores else {}
    series = [
        RiskPoint(
            week=s.week,
            score=s.score,
            change=s.score - score_before(before, parts[before.week], parts[s.week])
            if before
            else None,
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

    parts = scoring.parts_by_week(db, previous_week, current)
    then = parts.get(previous_week, frozenset())
    now_points = points(now)
    before_points = points_before(before, then, parts[current]) if before else None
    components = []
    for name in LABELS:
        # A part left out this week has no change to show.
        was = getattr(before_points, name) if before_points and name in parts[current] else None
        components.append(
            RiskComponentChange(
                component=name,
                points=getattr(now_points, name),
                previous_points=was,
                change=None if was is None else getattr(now_points, name) - was,
                explanation=explain(name, now, near),
            )
        )
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
    previous_score = score_before(before, then, parts[current]) if before else None
    change = now.score - previous_score if previous_score is not None else None
    return RiskExplanation(
        iso3=country.iso3,
        name=country.name,
        week=current,
        previous_week=previous_week if before else None,
        score=now.score,
        previous_score=previous_score,
        change=change,
        trend=now.trend,
        surge_alarm=now.surge_alarm,
        provisional=now.provisional,
        summary=summarise(now, change, components, then if before else None, parts[current]),
        components=components,
        events=[EventOut.model_validate(e) for e in events],
        neighbours=near,
    )


def summarise(
    now: RiskScore,
    change: float | None,
    components: list[RiskComponentChange],
    then: frozenset[str] | None,
    parts: frozenset[str],
) -> str:
    text = f"Score {now.score:.0f}"
    if change is not None:
        # A change that rounds to zero reads 0, never -0.
        text += f" ({change:+.0f} on the week before" if round(change) else " (0 on the week before"
        if then is not None and then != parts:
            rescored = [f"without {LABELS[n]}" for n in COMPONENTS if n in then - parts]
            rescored += [f"with {LABELS[n]}" for n in COMPONENTS if n in parts - then]
            text += f", both scored {' and '.join(rescored)}"
        text += ")"
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
        text += " Provisional: UCDP and ACLED have not coded all of this week yet, so deaths are missing"
        text += "." if "surge" in parts else " and Surge is left out."
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

"""Weekly conflict risk scores per country, built from the events table.

Each country gets four components every week, following "Scoring Conflict Risk Over Time"
(section 6):

  History  How violent lately? Deaths with a 26-week half-life, so old wars fade.
  Surge    Is this week abnormal here? Rolling z-score of log(1 + violent events) against
           weeks t-56..t-5, accumulated by a CUSUM so slow escalation adds up. Each source
           is compared only with its own earlier weeks, and only over weeks it covers, so
           loading ACLED for one year does not look like a war starting; the larger z counts.
  Spread   Are neighbours heating up? Mean History of neighbouring countries.
  Signal   Is the news turning? GDELT share of world conflict news, Goldstein score and
           tone, each as a z-score against the country's own baseline.

Each component becomes a level from 0 to 1 on a fixed scale: History and Spread on a log
scale where 10,000 decayed deaths is full (about 270 deaths a week sustained), Surge as the
CUSUM over its cap (the alarm is half), Signal as its z-score over 3. The score is the
weighted sum of levels, 0-100: History 40, Surge, Spread and Signal 20 each. A component
no country has a value for that week (Signal before GDELT has a baseline, Surge after
UCDP's last release) is left out and the rest are scaled up to fill 100.

Where this departs from the doc, and why:
  - Fixed scales, not percentiles across countries. With percentiles a country's score moves
    when something happens elsewhere, so a change on the timeline could not be traced to
    its own events; and ranks lose magnitude, scoring 10 deaths a week near 1,000.
  - A weighted sum, not a geometric mean. Surge and Signal are zero most weeks (a war at a
    steady level does not surge, and GDELT is loaded in patches), and a geometric mean then
    scores an ongoing war near zero. The doc names the arithmetic form as the alternative.
  - History weighs double, so how violent a place is counts more than whether it is
    changing. The doc's next step, fitting weights to next month's violence, replaces these.

History and Surge count UCDP and ACLED only: hand-coded sources are the outcome, GDELT
the leading signal. Duplicates already linked to a higher-priority source are skipped.
Weeks after the last hand-coded event are marked provisional, because UCDP is released
months late.

Run with `python -m app.risk build`. It rebuilds risk_countries and risk_scores.
"""

import argparse
import logging
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.countries import all_countries

log = logging.getLogger(__name__)

OUTCOME_SOURCES = ("ucdp", "acled")
HALF_LIFE_WEEKS = 26
# The surge baseline is the 52 weeks ending 4 weeks before this one, so a surge that has
# been building for a few weeks does not raise its own baseline.
BASELINE_GAP = 4
BASELINE_WEEKS = 52
MIN_BASELINE_WEEKS = 26
MIN_SIGNAL_WEEKS = 8
# Added to the baseline spread of log counts, so one event after a silent year is notable
# (z about 2.8) without being treated as a war.
SURGE_EPS = 0.25
# k = 1 looks for shifts of about 2 standard deviations. The textbook k = 0.5 let ordinary
# week-to-week noise in sparse counts pile up: on UCDP 2010-2024 it kept 2.2% of
# country-weeks in alarm (Colombia and Kenya for months at a time), against 0.7% with k = 1.
CUSUM_K = 1.0
CUSUM_ALARM = 4.0
# Without a ceiling, years of war build a sum that takes years of calm to drain; from the cap
# a surge drains away over two to four calm months.
CUSUM_CAP = 2 * CUSUM_ALARM
# Two countries are neighbours when they have events within this many PRIO-GRID cells
# (0.5 degrees each, so 3 cells is about 165 km at the equator) of each other.
NEIGHBOUR_CELLS = 3
GRID_COLUMNS = 720
TREND_WEEKS = 12
HIGH_SCORE = 50.0
TREND_MIN_CHANGE = 10.0
WEIGHTS = {"history": 40.0, "surge": 20.0, "spread": 20.0, "signal": 20.0}
COMPONENTS = tuple(WEIGHTS)
FULL_HISTORY = 10_000.0
FULL_SIGNAL = 3.0


@dataclass
class CountryWeeks:
    """Weekly inputs for one country, indexed by week number from the first week."""

    violent: dict[str, list[int]]  # by outcome source
    deaths: list[int]
    gdelt_events: list[int]
    goldstein: list[float | None]
    tone: list[float | None]


@dataclass
class ScoreRow:
    iso3: str
    week: date
    violent_events: int
    deaths: int
    gdelt_events: int
    history: float
    surge_source: str | None
    surge_events: int | None
    surge_baseline: float | None
    surge_z: float | None
    surge: float
    spread: float
    share_z: float | None
    goldstein_z: float | None
    tone_z: float | None
    signal: float
    level: dict[str, float] = field(default_factory=dict)  # 0-1 per component
    points: dict[str, float] = field(default_factory=dict)  # what each adds to the score
    score: float = 0.0
    trend: str | None = None
    surge_alarm: bool = False
    provisional: bool = False


class _Window:
    """Mean and spread of the values in a sliding baseline window, skipping missing ones."""

    def __init__(self, values: Sequence[float | None]):
        self.n = [0]
        self.s = [0.0]
        self.s2 = [0.0]
        for v in values:
            ok = v is not None
            self.n.append(self.n[-1] + ok)
            self.s.append(self.s[-1] + (v if ok else 0.0))
            self.s2.append(self.s2[-1] + (v * v if ok else 0.0))

    def stats(self, w: int) -> tuple[int, float, float]:
        """Count, mean and standard deviation over weeks w-56..w-5."""
        hi = max(w - BASELINE_GAP, 0)
        lo = max(hi - BASELINE_WEEKS, 0)
        n = self.n[hi] - self.n[lo]
        if n == 0:
            return 0, 0.0, 0.0
        mean = (self.s[hi] - self.s[lo]) / n
        var = (self.s2[hi] - self.s2[lo]) / n - mean * mean
        return n, mean, math.sqrt(max(var, 0.0))


def _z(value: float | None, window: _Window, w: int, floor: float) -> float | None:
    if value is None:
        return None
    n, mean, sd = window.stats(w)
    if n < MIN_SIGNAL_WEEKS:
        return None
    return (value - mean) / max(sd, floor)


def death_level(decayed_deaths: float) -> float:
    """0-1 on a log scale: 1 decayed death is 0.08, 100 is 0.5, 10,000 or more is 1."""
    return min(math.log10(1 + max(decayed_deaths, 0.0)) / math.log10(1 + FULL_HISTORY), 1.0)


def levels(r: ScoreRow) -> dict[str, float]:
    return {
        "history": death_level(r.history),
        "surge": min(r.surge / CUSUM_CAP, 1.0),
        "spread": death_level(r.spread),
        "signal": min(r.signal / FULL_SIGNAL, 1.0),
    }


def mann_kendall_z(series: Sequence[float]) -> float:
    """Mann-Kendall trend statistic as a z-score (no tie correction)."""
    n = len(series)
    s = sum(
        (series[j] > series[i]) - (series[j] < series[i]) for i in range(n) for j in range(i + 1, n)
    )
    if s == 0:
        return 0.0
    var = n * (n - 1) * (2 * n + 5) / 18
    return (s - 1 if s > 0 else s + 1) / math.sqrt(var)


def trend_label(scores: Sequence[float]) -> str | None:
    """Emerging-hot-spot style tag from the last TREND_WEEKS scores, newest last."""
    if not scores:
        return None
    current, earlier = scores[-1], scores[:-1]
    if current >= HIGH_SCORE and earlier and max(earlier) < HIGH_SCORE:
        return "new"
    if len(scores) >= 6:
        k = min(4, len(scores) // 2)
        change = sum(scores[-k:]) / k - sum(scores[:k]) / k
        z = mann_kendall_z(scores)
        if z > 1.96 and change >= TREND_MIN_CHANGE:
            return "intensifying"
        if z < -1.96 and change <= -TREND_MIN_CHANGE:
            return "diminishing"
    if sum(s >= HIGH_SCORE for s in scores) >= 0.75 * TREND_WEEKS:
        return "persistent"
    return None


def neighbours_from_cells(cells: Iterable[tuple[str, int]]) -> dict[str, set[str]]:
    """Countries whose event cells come within NEIGHBOUR_CELLS of each other."""
    by_cell: dict[tuple[int, int], set[str]] = defaultdict(set)
    for iso3, gid in cells:
        row, col = divmod(gid - 1, GRID_COLUMNS)
        by_cell[(row, col)].add(iso3)
    out: dict[str, set[str]] = defaultdict(set)
    r = NEIGHBOUR_CELLS
    for (row, col), here in by_cell.items():
        for dr in range(-r, r + 1):
            for dc in range(-r, r + 1):
                there = by_cell.get((row + dr, (col + dc) % GRID_COLUMNS))
                for a in here if there else ():
                    if others := there - {a}:
                        out[a] |= others
    return out


def surge_by_source(
    counts: Sequence[int], covered: Sequence[bool]
) -> list[tuple[float, float] | None]:
    """(z, baseline mean count) per week for one source, None where it has no baseline."""
    logs = [math.log1p(c) if ok else None for c, ok in zip(counts, covered, strict=True)]
    window = _Window(logs)
    out: list[tuple[float, float] | None] = []
    for w, x in enumerate(logs):
        n, mean, sd = window.stats(w)
        if x is None or n < MIN_BASELINE_WEEKS:
            out.append(None)
        else:
            out.append(((x - mean) / (sd + SURGE_EPS), math.expm1(mean)))
    return out


def score_countries(
    weeks: Sequence[date],
    data: dict[str, CountryWeeks],
    neighbours: dict[str, set[str]],
    provisional_after: date | None,
) -> list[ScoreRow]:
    """Every country's components, percentiles, score and trend for every week."""
    countries = sorted(data)
    n_weeks = len(weeks)
    decay = 2 ** (-1 / HALF_LIFE_WEEKS)
    world_gdelt = [sum(data[c].gdelt_events[w] for c in countries) for w in range(n_weeks)]
    # A source covers a week when it has any violent event anywhere that week.
    covered = {
        src: [any(data[c].violent[src][w] for c in countries) for w in range(n_weeks)]
        for src in OUTCOME_SOURCES
    }

    rows: dict[str, list[ScoreRow]] = {}
    for c in countries:
        d = data[c]
        surges = {src: surge_by_source(d.violent[src], covered[src]) for src in OUTCOME_SOURCES}
        share = [
            d.gdelt_events[w] / world_gdelt[w] if world_gdelt[w] else None for w in range(n_weeks)
        ]
        share_window, gold_window, tone_window = (
            _Window(share),
            _Window(d.goldstein),
            _Window(d.tone),
        )

        history = cusum = 0.0
        out = []
        for w in range(n_weeks):
            history = d.deaths[w] + decay * history
            known = [(z[0], z[1], src) for src in OUTCOME_SOURCES if (z := surges[src][w])]
            if known:
                surge_z, baseline, surge_source = max(known)
                cusum = min(max(0.0, cusum + surge_z - CUSUM_K), CUSUM_CAP)
            else:
                surge_z = baseline = surge_source = None
                cusum = 0.0
            share_z = _z(share[w], share_window, w, floor=1e-4)
            goldstein_z = _z(d.goldstein[w], gold_window, w, floor=0.5)
            tone_z = _z(d.tone[w], tone_window, w, floor=0.5)
            # Lower Goldstein and tone mean more hostile coverage, so they count negated.
            zs = [share_z] + [-z if z is not None else None for z in (goldstein_z, tone_z)]
            zs = [z for z in zs if z is not None]
            out.append(
                ScoreRow(
                    iso3=c,
                    week=weeks[w],
                    violent_events=sum(d.violent[src][w] for src in OUTCOME_SOURCES),
                    deaths=d.deaths[w],
                    gdelt_events=d.gdelt_events[w],
                    history=history,
                    surge_source=surge_source,
                    surge_events=d.violent[surge_source][w] if surge_source else None,
                    surge_baseline=baseline,
                    surge_z=surge_z,
                    surge=cusum,
                    spread=0.0,
                    share_z=share_z,
                    goldstein_z=goldstein_z,
                    tone_z=tone_z,
                    signal=max(sum(zs) / len(zs), 0.0) if zs else 0.0,
                    surge_alarm=cusum > CUSUM_ALARM,
                    provisional=provisional_after is not None and weeks[w] > provisional_after,
                )
            )
        rows[c] = out

    for w in range(n_weeks):
        for c in countries:
            near = [rows[o][w].history for o in neighbours.get(c, ()) if o in rows]
            rows[c][w].spread = sum(near) / len(near) if near else 0.0
        week_rows = [rows[c][w] for c in countries]
        available = {
            "history": True,
            "surge": any(r.surge_z is not None for r in week_rows),
            "spread": bool(neighbours),
            "signal": any(
                z is not None for r in week_rows for z in (r.share_z, r.goldstein_z, r.tone_z)
            ),
        }
        scale = 100.0 / sum(WEIGHTS[name] for name in COMPONENTS if available[name])
        for r in week_rows:
            r.level = levels(r)
            r.points = {
                name: scale * WEIGHTS[name] * r.level[name] if available[name] else 0.0
                for name in COMPONENTS
            }
            r.score = min(sum(r.points.values()), 100.0)

    for c in countries:
        scores = [r.score for r in rows[c]]
        for w, r in enumerate(rows[c]):
            r.trend = trend_label(scores[max(0, w - TREND_WEEKS + 1) : w + 1])
    return [r for c in countries for r in rows[c]]


WEEKLY_SQL = """
SELECT country_iso3 AS iso3,
       date_trunc('week', event_date)::date AS week,
       count(*) FILTER (WHERE is_violent AND source = 'ucdp') AS violent_ucdp,
       count(*) FILTER (WHERE is_violent AND source = 'acled') AS violent_acled,
       coalesce(sum(fatalities_best) FILTER (WHERE is_violent AND source = ANY(:outcome)), 0) AS deaths,
       count(*) FILTER (WHERE source = 'gdelt') AS gdelt_events,
       sum(report_count * (attributes->>'goldstein')::float)
           FILTER (WHERE source = 'gdelt' AND attributes->>'goldstein' IS NOT NULL)
         / nullif(sum(report_count)
           FILTER (WHERE source = 'gdelt' AND attributes->>'goldstein' IS NOT NULL), 0) AS goldstein,
       avg(tone) FILTER (WHERE source = 'gdelt') AS tone
FROM events
WHERE duplicate_of_id IS NULL AND country_iso3 IS NOT NULL
GROUP BY 1, 2
"""

CELLS_SQL = """
SELECT DISTINCT country_iso3, priogrid_gid FROM events
WHERE country_iso3 IS NOT NULL AND priogrid_gid IS NOT NULL
"""

# Countries are drawn at the average position of their located events.
CENTROIDS_SQL = """
SELECT country_iso3, avg(latitude), avg(longitude), max(country) FROM events
WHERE country_iso3 IS NOT NULL AND geo_precision <> 'country'
GROUP BY 1
"""

SCORE_COLUMNS = (
    "iso3", "week", "violent_events", "deaths", "gdelt_events", "history", "surge_source",
    "surge_events", "surge_baseline", "surge_z", "surge", "spread", "share_z", "goldstein_z",
    "tone_z", "signal", "points_history", "points_surge", "points_spread", "points_signal",
    "score", "trend", "surge_alarm", "provisional",
)  # fmt: skip


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def load_inputs(db: Session) -> tuple[list[date], dict[str, CountryWeeks], date | None]:
    raw = db.execute(text(WEEKLY_SQL), {"outcome": list(OUTCOME_SOURCES)}).all()
    if not raw:
        return [], {}, None
    first, last = min(r.week for r in raw), max(r.week for r in raw)
    weeks = [first + timedelta(weeks=i) for i in range((last - first).days // 7 + 1)]
    n = len(weeks)
    data: dict[str, CountryWeeks] = {}
    for r in raw:
        d = data.get(r.iso3)
        if d is None:
            violent = {src: [0] * n for src in OUTCOME_SOURCES}
            d = data[r.iso3] = CountryWeeks(violent, [0] * n, [0] * n, [None] * n, [None] * n)
        w = (r.week - first).days // 7
        d.violent["ucdp"][w], d.violent["acled"][w] = r.violent_ucdp, r.violent_acled
        d.deaths[w], d.gdelt_events[w] = r.deaths, r.gdelt_events
        d.goldstein[w], d.tone[w] = r.goldstein, r.tone
    last_outcome = db.scalar(
        text("SELECT max(event_date) FROM events WHERE source = ANY(:outcome)"),
        {"outcome": list(OUTCOME_SOURCES)},
    )
    return weeks, data, monday(last_outcome) if last_outcome else None


def build(db: Session) -> int:
    """Rebuild risk_countries and risk_scores from the events table. Returns rows written."""
    started = datetime.now()
    weeks, data, provisional_after = load_inputs(db)
    neighbours = neighbours_from_cells(db.execute(text(CELLS_SQL)))
    rows = score_countries(weeks, data, neighbours, provisional_after)

    names = {iso3: c.name for iso3, c in all_countries().items()}
    centroids = {r[0]: r for r in db.execute(text(CENTROIDS_SQL))}
    db.execute(text("TRUNCATE risk_scores, risk_countries"))
    db.execute(
        text(
            "INSERT INTO risk_countries (iso3, name, latitude, longitude, neighbours) "
            "VALUES (:iso3, :name, :lat, :lon, :neighbours)"
        ),
        [
            {
                "iso3": c,
                "name": names.get(c) or (centroids[c][3] if c in centroids else c),
                "lat": centroids[c][1] if c in centroids else None,
                "lon": centroids[c][2] if c in centroids else None,
                "neighbours": sorted(neighbours.get(c, ())),
            }
            for c in data
        ],
    )
    raw = db.connection().connection.driver_connection
    with raw.cursor() as cur, cur.copy(f"COPY risk_scores ({', '.join(SCORE_COLUMNS)}) FROM STDIN") as copy:  # fmt: skip
        for r in rows:
            copy.write_row(
                (
                    r.iso3, r.week, r.violent_events, r.deaths, r.gdelt_events, r.history,
                    r.surge_source, r.surge_events, r.surge_baseline, r.surge_z, r.surge,
                    r.spread, r.share_z, r.goldstein_z, r.tone_z, r.signal,
                    r.points["history"], r.points["surge"], r.points["spread"],
                    r.points["signal"], r.score, r.trend, r.surge_alarm, r.provisional,
                )
            )  # fmt: skip
    db.commit()
    log.info(
        "risk scores: %d countries x %d weeks = %d rows in %.1fs",
        len(data),
        len(weeks),
        len(rows),
        (datetime.now() - started).total_seconds(),
    )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.risk")
    parser.add_argument("command", choices=["build"])
    parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from app.db import session_factory

    with session_factory()() as db:
        build(db)


if __name__ == "__main__":
    main()

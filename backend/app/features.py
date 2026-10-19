"""Builds cell_month_features: event counts and conflict history per PRIO-GRID cell and month.

This is the common unit forecasting models work on. Each row says what happened in one
0.5 degree cell in one month (UCDP deaths, ACLED events, GDELT signals) and what came
before it there and next door. History columns (*_last{N}m, months_since_violence) only
look at earlier months, so they can be used to predict the month's own outcome without
look-ahead.

Rows exist for every month of the requested range in every cell that had at least one
event in that range or the 36 months before it; a missing cell-month means no events and
no recent history, i.e. all zeros. Rebuilding a range replaces its rows, so run it again
after loading new events. Per-source counts include events another source also reported
(cross-source duplicates); violent_events counts each incident once.
"""

import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

LOOKBACK_MONTHS = 36

# Neighbours are the eight surrounding cells; columns wrap around the antimeridian, rows stop
# at the poles. PRIO-GRID numbers cells row by row, 720 to a row, starting at 1.
_NEIGHBOUR_OFFSETS = "(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)"

_BUILD_SQL = f"""
WITH bounds AS (
    SELECT CAST(:first_month AS date) AS first_month,
           CAST(:last_month AS date) AS last_month,
           CAST(CAST(:first_month AS date) - interval '{LOOKBACK_MONTHS} months' AS date) AS lookback
),
monthly AS (
    SELECT e.priogrid_gid AS gid,
           CAST(date_trunc('month', e.event_date) AS date) AS month,
           count(*) FILTER (WHERE source = 'ucdp') AS ucdp_events,
           coalesce(sum(fatalities_best) FILTER (WHERE source = 'ucdp'), 0) AS ucdp_fatalities,
           count(*) FILTER (WHERE is_violent AND duplicate_of_id IS NULL) AS violent_events,
           count(*) FILTER (WHERE source = 'acled') AS acled_events,
           coalesce(sum(fatalities_best) FILTER (WHERE source = 'acled'), 0) AS acled_fatalities,
           count(*) FILTER (WHERE source = 'acled' AND event_type = 'protest') AS acled_protests,
           count(*) FILTER (WHERE source = 'acled' AND event_type = 'riot') AS acled_riots,
           count(*) FILTER (WHERE source = 'gdelt' AND event_type = 'threat') AS gdelt_threats,
           count(*) FILTER (WHERE source = 'gdelt' AND event_type = 'protest') AS gdelt_protests,
           count(*) FILTER (WHERE source = 'gdelt' AND event_type = 'force_posture')
               AS gdelt_force_posture,
           count(*) FILTER (WHERE source = 'gdelt'
                            AND event_type IN ('reduce_relations', 'coercion')) AS gdelt_coercion,
           count(*) FILTER (WHERE source = 'gdelt'
                            AND event_type IN ('assault', 'fight', 'mass_violence')) AS gdelt_violence,
           coalesce(sum(report_count) FILTER (WHERE source = 'gdelt'), 0) AS gdelt_mentions,
           -- Weighted by mentions, so widely reported events set the month's tone.
           sum(tone * report_count) FILTER (WHERE source = 'gdelt' AND tone IS NOT NULL)
               / nullif(sum(report_count) FILTER (WHERE source = 'gdelt' AND tone IS NOT NULL), 0)
               AS gdelt_tone
    FROM events e, bounds b
    WHERE e.priogrid_gid IS NOT NULL
      AND e.event_date >= b.lookback
      AND e.event_date < b.last_month + interval '1 month'
    GROUP BY 1, 2
),
cells AS (SELECT DISTINCT gid FROM monthly),
months AS (
    SELECT CAST(m AS date) AS month
    FROM bounds b, generate_series(b.lookback, b.last_month, interval '1 month') AS m
),
dense AS (
    SELECT c.gid, m.month,
           coalesce(x.ucdp_events, 0) AS ucdp_events,
           coalesce(x.ucdp_fatalities, 0) AS ucdp_fatalities,
           coalesce(x.violent_events, 0) AS violent_events,
           coalesce(x.acled_events, 0) AS acled_events,
           coalesce(x.acled_fatalities, 0) AS acled_fatalities,
           coalesce(x.acled_protests, 0) AS acled_protests,
           coalesce(x.acled_riots, 0) AS acled_riots,
           coalesce(x.gdelt_threats, 0) AS gdelt_threats,
           coalesce(x.gdelt_protests, 0) AS gdelt_protests,
           coalesce(x.gdelt_force_posture, 0) AS gdelt_force_posture,
           coalesce(x.gdelt_coercion, 0) AS gdelt_coercion,
           coalesce(x.gdelt_violence, 0) AS gdelt_violence,
           coalesce(x.gdelt_mentions, 0) AS gdelt_mentions,
           x.gdelt_tone
    FROM cells c CROSS JOIN months m
    LEFT JOIN monthly x ON x.gid = c.gid AND x.month = m.month
),
neighbours AS (
    SELECT d.gid, d.month, sum(n.ucdp_fatalities) AS fatalities
    FROM dense d
    CROSS JOIN (VALUES {_NEIGHBOUR_OFFSETS}) AS o(dr, dc)
    JOIN monthly n
      ON n.month = d.month
     AND n.gid = ((d.gid - 1) / 720 + o.dr) * 720 + ((d.gid - 1) % 720 + o.dc + 720) % 720 + 1
    WHERE (d.gid - 1) / 720 + o.dr BETWEEN 0 AND 359
    GROUP BY 1, 2
),
history AS (
    SELECT d.*,
           coalesce(nb.fatalities, 0) AS neighbour_fatalities,
           coalesce(sum(d.ucdp_fatalities) OVER (w ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING), 0)
               AS ucdp_fatalities_last1m,
           coalesce(sum(d.ucdp_fatalities) OVER (w ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 0)
               AS ucdp_fatalities_last3m,
           coalesce(sum(d.ucdp_fatalities) OVER (w ROWS BETWEEN 12 PRECEDING AND 1 PRECEDING), 0)
               AS ucdp_fatalities_last12m,
           coalesce(sum(d.ucdp_fatalities) OVER (w ROWS BETWEEN 36 PRECEDING AND 1 PRECEDING), 0)
               AS ucdp_fatalities_last36m,
           max(d.month) FILTER (WHERE d.violent_events > 0)
               OVER (w ROWS BETWEEN {LOOKBACK_MONTHS} PRECEDING AND 1 PRECEDING) AS last_violent_month,
           coalesce(sum(coalesce(nb.fatalities, 0)) OVER (w ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING), 0)
               AS neighbour_fatalities_last1m,
           coalesce(sum(coalesce(nb.fatalities, 0)) OVER (w ROWS BETWEEN 12 PRECEDING AND 1 PRECEDING), 0)
               AS neighbour_fatalities_last12m,
           coalesce(sum(d.gdelt_protests) OVER (w ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 0)
               AS gdelt_protests_last3m,
           coalesce(sum(d.gdelt_threats) OVER (w ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 0)
               AS gdelt_threats_last3m
    FROM dense d
    LEFT JOIN neighbours nb ON nb.gid = d.gid AND nb.month = d.month
    WINDOW w AS (PARTITION BY d.gid ORDER BY d.month)
),
cell_country AS (
    SELECT DISTINCT ON (e.priogrid_gid) e.priogrid_gid AS gid, e.country_iso3
    FROM events e JOIN cells c ON c.gid = e.priogrid_gid
    WHERE e.country_iso3 IS NOT NULL
    GROUP BY 1, 2
    ORDER BY e.priogrid_gid, count(*) DESC, e.country_iso3
)
INSERT INTO cell_month_features (
    gid, month, iso3, ucdp_events, ucdp_fatalities, violent_events, acled_events,
    acled_fatalities, acled_protests, acled_riots, gdelt_threats, gdelt_protests,
    gdelt_force_posture, gdelt_coercion, gdelt_violence, gdelt_mentions, gdelt_tone,
    ucdp_fatalities_last1m, ucdp_fatalities_last3m, ucdp_fatalities_last12m,
    ucdp_fatalities_last36m, months_since_violence, neighbour_fatalities_last1m,
    neighbour_fatalities_last12m, gdelt_protests_last3m, gdelt_threats_last3m
)
SELECT h.gid, h.month, cc.country_iso3, h.ucdp_events, h.ucdp_fatalities, h.violent_events,
       h.acled_events, h.acled_fatalities, h.acled_protests, h.acled_riots, h.gdelt_threats,
       h.gdelt_protests, h.gdelt_force_posture, h.gdelt_coercion, h.gdelt_violence,
       h.gdelt_mentions, h.gdelt_tone, h.ucdp_fatalities_last1m, h.ucdp_fatalities_last3m,
       h.ucdp_fatalities_last12m, h.ucdp_fatalities_last36m,
       (extract(year FROM age(h.month, h.last_violent_month)) * 12
        + extract(month FROM age(h.month, h.last_violent_month)))::integer,
       h.neighbour_fatalities_last1m, h.neighbour_fatalities_last12m,
       h.gdelt_protests_last3m, h.gdelt_threats_last3m
FROM history h
CROSS JOIN bounds b
LEFT JOIN cell_country cc ON cc.gid = h.gid
WHERE h.month BETWEEN b.first_month AND b.last_month
"""


def cell_centre(gid: int) -> tuple[float, float]:
    """Latitude and longitude of a PRIO-GRID cell's centre."""
    row, col = divmod(gid - 1, 720)
    return row * 0.5 - 89.75, col * 0.5 - 179.75


def month_start(day: date) -> date:
    return day.replace(day=1)


def build_cell_months(session: Session, first: date, last: date) -> int:
    """Rebuilds the rows for every month from `first` to `last` (inclusive), a year at a time.

    Each year is its own transaction, so a long backfill keeps the years it finished.
    """
    first, last = month_start(first), month_start(last)
    if first > last:
        raise ValueError("first month must be on or before last month")
    total = 0
    for year in range(first.year, last.year + 1):
        chunk_first = max(first, date(year, 1, 1))
        chunk_last = min(last, date(year, 12, 1))
        params = {"first_month": chunk_first, "last_month": chunk_last}
        session.execute(
            text(
                "DELETE FROM cell_month_features "
                "WHERE month BETWEEN CAST(:first_month AS date) AND CAST(:last_month AS date)"
            ),
            params,
        )
        rows = session.execute(text(_BUILD_SQL), params).rowcount
        session.commit()
        log.info("built %s cell-months for %s to %s", rows, chunk_first, chunk_last)
        total += rows
    return total

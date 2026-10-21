"""Parse and store live observations: military aircraft (adsb.lol) and fires (NASA FIRMS).

The feeds only describe the present, so history exists only from when recording began.
Each row is a position at a time; boards join rows of one aircraft into a track.
"""

import csv
import http.client
import io
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.boards.articles import USER_AGENT

log = logging.getLogger(__name__)

ADSB_MIL_URL = "https://api.adsb.lol/v2/mil"
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{area}/{days}/{date}"


class FeedError(Exception):
    pass


def _get(url: str, timeout: float = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    # A response cut off mid-body raises http.client.IncompleteRead, not an OSError.
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
        raise FeedError(f"{url.split('?')[0]}: {e}") from e


def parse_adsb(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """adsb.lol /v2/mil: aircraft flagged military by its database, with positions.

    `now` is the feed time in milliseconds; `seen_pos` is how many seconds old each
    position is, so the observation time is now minus seen_pos.
    """
    now_ms = payload.get("now")
    if not isinstance(now_ms, (int, float)):
        raise FeedError("adsb.lol answer has no time")
    now = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    rows = []
    for a in payload.get("ac") or []:
        lat, lon, hex_ = a.get("lat"), a.get("lon"), a.get("hex")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not hex_:
            continue
        seen = a.get("seen_pos") if isinstance(a.get("seen_pos"), (int, float)) else 0
        # Positions older than a minute are stale repeats of an earlier poll.
        if seen > 60:
            continue
        observed = (now - timedelta(seconds=seen)).replace(microsecond=0)
        callsign = (a.get("flight") or "").strip() or None
        altitude = a.get("alt_baro")
        attributes = {
            "callsign": callsign,
            "registration": a.get("r"),
            "type": a.get("t"),
            "altitude_ft": altitude if isinstance(altitude, (int, float)) else None,
            "on_ground": altitude == "ground",
            "speed_kt": a.get("gs"),
            "track": a.get("track"),
            "squawk": a.get("squawk"),
        }
        rows.append(
            {
                "source": "adsb.lol",
                "kind": "flight",
                "external_id": str(hex_).lower(),
                "observed_at": observed,
                "latitude": float(lat),
                "longitude": float(lon),
                "label": " · ".join(x for x in (callsign, a.get("t")) if x) or str(hex_),
                "attributes": {k: v for k, v in attributes.items() if v is not None},
            }
        )
    return rows


def fetch_adsb_mil() -> list[dict[str, Any]]:
    try:
        payload = json.loads(_get(ADSB_MIL_URL))
    except ValueError as e:
        raise FeedError("adsb.lol answered with something other than JSON") from e
    return parse_adsb(payload)


def parse_firms(csv_text: str, source: str) -> list[dict[str, Any]]:
    """One FIRMS area CSV (VIIRS or MODIS): a row per active-fire pixel."""
    if not csv_text.lstrip().startswith("latitude"):
        # FIRMS answers key and quota problems in plain text.
        raise FeedError(f"FIRMS: {csv_text.strip()[:200]}")
    rows = []
    for r in csv.DictReader(io.StringIO(csv_text)):
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
            hhmm = r["acq_time"].zfill(4)
            observed = datetime.strptime(f"{r['acq_date']} {hhmm}", "%Y-%m-%d %H%M").replace(
                tzinfo=UTC
            )
        except (KeyError, ValueError):
            continue
        satellite = r.get("satellite", "")
        rows.append(
            {
                "source": f"firms:{source.lower()}",
                "kind": "fire",
                "external_id": f"{satellite}:{lat:.4f}:{lon:.4f}",
                "observed_at": observed,
                "latitude": lat,
                "longitude": lon,
                "label": f"{r.get('instrument') or source} {satellite}".strip(),
                "attributes": {
                    k: r[k]
                    for k in ("confidence", "frp", "bright_ti4", "daynight", "instrument")
                    if r.get(k)
                },
            }
        )
    return rows


def fetch_firms(
    key: str, bbox: str, start: date, days: int, source: str = "VIIRS_SNPP_NRT"
) -> list[dict[str, Any]]:
    """Fire detections in a bounding box (west,south,east,north) for up to 10 days a call."""
    rows = []
    day = start
    remaining = days
    while remaining > 0:
        span = min(10, remaining)
        url = FIRMS_URL.format(key=key, source=source, area=bbox, days=span, date=day.isoformat())
        rows += parse_firms(_get(url, timeout=60).decode("utf-8", errors="replace"), source)
        day += timedelta(days=span)
        remaining -= span
    return rows


def store(db: Session, rows: Iterable[dict[str, Any]]) -> int:
    """Insert observations, skipping ones already recorded. Returns how many were new."""
    rows = list(rows)
    if not rows:
        return 0
    result = db.execute(
        text("""
            INSERT INTO observations
                (source, kind, external_id, observed_at, latitude, longitude, label, attributes)
            SELECT source, kind, external_id, observed_at, latitude, longitude, label,
                   attributes::jsonb
            FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(
                source text, kind text, external_id text, observed_at timestamptz,
                latitude double precision, longitude double precision, label text,
                attributes text)
            ON CONFLICT (source, external_id, observed_at) DO NOTHING
        """),
        {
            "rows": json.dumps(
                [
                    {
                        **r,
                        "observed_at": r["observed_at"].isoformat(),
                        "attributes": json.dumps(r["attributes"]),
                    }
                    for r in rows
                ]
            )
        },
    )
    db.commit()
    return result.rowcount or 0


def prune(db: Session, days: int) -> int:
    result = db.execute(
        text("DELETE FROM observations WHERE observed_at < now() - make_interval(days => :d)"),
        {"d": days},
    )
    db.commit()
    return result.rowcount or 0

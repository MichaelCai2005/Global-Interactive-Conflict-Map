"""Find coordinates for a place the events table has never seen, via OpenStreetMap.

Only Claude's extraction needs this: the gazetteer extractor only finds known places.
Nominatim's usage policy asks for a real User-Agent and at most one request a second.
"""

import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

from app.boards.articles import USER_AGENT
from app.config import get_settings

log = logging.getLogger(__name__)
_last_request = 0.0


@dataclass(frozen=True)
class Geocoded:
    name: str
    latitude: float
    longitude: float
    display_name: str


@lru_cache(maxsize=512)
def geocode(name: str, country: str | None) -> Geocoded | None:
    global _last_request
    if get_settings().board_geocoder != "nominatim":
        return None
    query = f"{name}, {country}" if country else name
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "limit": 1}
    )
    wait = 1.1 - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=10) as response:
            results = json.load(response)
    except (OSError, ValueError) as e:
        log.warning("geocoding %r failed: %s", query, e)
        return None
    if not results:
        return None
    best = results[0]
    return Geocoded(
        name=name,
        latitude=float(best["lat"]),
        longitude=float(best["lon"]),
        display_name=best.get("display_name", name),
    )

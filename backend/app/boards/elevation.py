"""Ground height for exported points, so they sit on the 3D terrain instead of under it.

gods-eye-view places pack geometry at heights above the WGS84 ellipsoid; a point at zero
is underground anywhere above sea level. Heights come from Open-Meteo's free elevation
API (Copernicus 90 m DEM), up to 100 points a request.
"""

import json
import logging
import urllib.parse
import urllib.request

from app.boards.articles import USER_AGENT
from app.config import get_settings

log = logging.getLogger(__name__)

# Used when the elevation service is off or unreachable: above most inhabited ground, so
# points stay visible, at the cost of floating in low places.
FALLBACK_M = 400.0
_cache: dict[tuple[float, float], float] = {}


def _key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, 3), round(lon, 3))


def ground_heights(points: list[tuple[float, float]]) -> tuple[list[float], bool]:
    """Heights in metres for (lat, lon) points, and whether they are real or the fallback."""
    if get_settings().board_elevation != "open-meteo":
        return [FALLBACK_M] * len(points), False
    missing = sorted({_key(*p) for p in points} - set(_cache))
    try:
        for i in range(0, len(missing), 100):
            chunk = missing[i : i + 100]
            url = "https://api.open-meteo.com/v1/elevation?" + urllib.parse.urlencode(
                {
                    "latitude": ",".join(f"{lat}" for lat, _ in chunk),
                    "longitude": ",".join(f"{lon}" for _, lon in chunk),
                }
            )
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=10) as response:
                heights = json.load(response)["elevation"]
            for key, height in zip(chunk, heights, strict=True):
                # Sea and missing tiles come back as NaN or below sea level.
                _cache[key] = max(0.0, float(height)) if height == height else 0.0
    except (OSError, ValueError, KeyError) as e:
        log.warning("elevation lookup failed, using %s m: %s", FALLBACK_M, e)
        return [FALLBACK_M] * len(points), False
    return [_cache[_key(*p)] for p in points], True

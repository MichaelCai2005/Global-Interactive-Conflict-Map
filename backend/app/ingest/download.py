"""Fetches raw source files into a local folder so they can be loaded with `ingest load`."""

import logging
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

# GDELT 1.0 publishes one zipped file per day from 2013-04-01 onward.
GDELT_DAILY_URL = "http://data.gdeltproject.org/events/{day:%Y%m%d}.export.CSV.zip"
# UCDP names its GED release files by version, e.g. 25.1 -> ged251-csv.zip. Check the
# current version at https://ucdp.uu.se/downloads/ if this 404s.
UCDP_GED_URL = "https://ucdp.uu.se/downloads/ged/ged{version}-csv.zip"


def fetch(url: str, dest: Path, attempts: int = 4) -> Path:
    """Downloads with exponential backoff; skips files already on disk."""
    if dest.exists() and dest.stat().st_size > 0:
        log.info("already have %s", dest.name)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as out:
                while chunk := response.read(1 << 20):
                    out.write(chunk)
            partial.rename(dest)
            log.info("downloaded %s", dest.name)
            return dest
        except urllib.error.HTTPError as exc:
            if exc.code == 404 or attempt == attempts:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts:
                raise
        wait = 2**attempt
        log.warning("download of %s failed (attempt %s), retrying in %ss", url, attempt, wait)
        time.sleep(wait)
    raise RuntimeError("unreachable")


def gdelt_daily(start: date, end: date, out_dir: Path) -> list[Path]:
    paths = []
    day = start
    while day <= end:
        url = GDELT_DAILY_URL.format(day=day)
        try:
            paths.append(fetch(url, out_dir / "gdelt" / Path(url).name))
        except urllib.error.HTTPError as exc:
            log.warning("skipping %s: HTTP %s", day, exc.code)
        day += timedelta(days=1)
    return paths


def ucdp_ged(version: str, out_dir: Path) -> Path:
    compact = version.replace(".", "")
    url = UCDP_GED_URL.format(version=compact)
    return fetch(url, out_dir / "ucdp" / Path(url).name)

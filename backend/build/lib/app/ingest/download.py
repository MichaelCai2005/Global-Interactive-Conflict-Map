"""Fetches raw source files into a local folder so they can be loaded with `ingest load`."""

import csv
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from app.ingest import wdi

log = logging.getLogger(__name__)

# GDELT 1.0 publishes one zipped file per day from 2013-04-01 onward.
GDELT_DAILY_URL = "http://data.gdeltproject.org/events/{day:%Y%m%d}.export.CSV.zip"
# UCDP names its GED release files by version, e.g. 26.1 -> ged261-csv.zip. Check the
# current version at https://ucdp.uu.se/downloads/ if this 404s.
UCDP_GED_URL = "https://ucdp.uu.se/downloads/ged/ged{version}-csv.zip"
# UCDP Candidate posts one file a month, around the 20th, holding the month before plus a
# few corrections to earlier months: version 26.0.9 is September 2026. The yearly GED
# release later replaces them.
UCDP_CANDIDATE_URL = "https://ucdp.uu.se/downloads/candidateged/GEDEvent_v{yy:02d}_0_{month}.csv"
# ACLED's API takes an OAuth token from the account's email and password. Its firewall
# rejects Python's default User-Agent, so every ACLED request names this client.
ACLED_TOKEN_URL = "https://acleddata.com/oauth/token"
ACLED_READ_URL = "https://acleddata.com/api/acled/read"
ACLED_USER_AGENT = "conflict-map-backend/0.1"
ACLED_PAGE_SIZE = 5000
# World Bank Indicators API v2: one indicator for every country and year range per query.
WDI_URL = "https://api.worldbank.org/v2/country/all/indicator/{indicator}"
WDI_PAGE_SIZE = 20000
# EPR Core, ETH Zurich. Newer releases keep this naming (EPR-2021.csv, EPR-2023.csv...).
EPR_URL = "https://icr.ethz.ch/data/epr/core/EPR-{version}.csv"


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
        except (urllib.error.URLError, TimeoutError, ConnectionError):
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


def ucdp_candidate(start_year: int, end_year: int, out_dir: Path) -> list[Path]:
    """Fetches every monthly Candidate file posted for these years; months not out yet are skipped."""
    paths = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            url = UCDP_CANDIDATE_URL.format(yy=year % 100, month=month)
            try:
                paths.append(fetch(url, out_dir / "ucdp" / Path(url).name))
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
                log.info("no UCDP Candidate file for %s-%02d yet", year, month)
    return paths


def _request_json(request: urllib.request.Request, attempts: int = 4) -> dict | list:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == attempts:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts:
                raise
        wait = 2**attempt
        log.warning(
            "request to %s failed (attempt %s), retrying in %ss", request.full_url, attempt, wait
        )
        time.sleep(wait)
    raise RuntimeError("unreachable")


def acled_token(email: str, password: str) -> str:
    body = urllib.parse.urlencode(
        {"username": email, "password": password, "grant_type": "password", "client_id": "acled"}
    ).encode()
    request = urllib.request.Request(
        ACLED_TOKEN_URL, body, headers={"User-Agent": ACLED_USER_AGENT}
    )
    return _request_json(request)["access_token"]


def acled_pages(token: str, filters: dict[str, str]) -> list[dict]:
    """Reads every page of one query. ACLED pages are 1-based; a short page is the last."""
    rows: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {"_format": "json", "limit": ACLED_PAGE_SIZE, "page": page, **filters}
        )
        request = urllib.request.Request(
            f"{ACLED_READ_URL}?{query}",
            headers={"Authorization": f"Bearer {token}", "User-Agent": ACLED_USER_AGENT},
        )
        data = _request_json(request)
        if data.get("status") != 200:
            raise RuntimeError(
                f"ACLED returned status {data.get('status')}: {data.get('messages')}"
            )
        batch = data.get("data") or []
        rows += batch
        if len(batch) < ACLED_PAGE_SIZE:
            return rows
        page += 1


def acled_events(
    email: str,
    password: str,
    start_year: int,
    end_year: int,
    countries: list[str],
    out_dir: Path,
    today: date | None = None,
) -> list[Path]:
    """Saves one CSV per country (or "all") per year, in the column layout `acled.parse` reads.

    Free accounts only see events more than a year old, and ACLED revises recent events
    weekly, so the last two years are always fetched again; older files on disk are kept.
    """
    today = today or date.today()
    token = acled_token(email, password)
    paths = []
    for country in countries or [None]:
        slug = re.sub(r"[^a-z0-9]+", "-", country.lower()).strip("-") if country else "all"
        for year in range(start_year, end_year + 1):
            dest = out_dir / "acled" / f"acled-{slug}-{year}.csv"
            if dest.exists() and year < today.year - 1:
                log.info("already have %s", dest.name)
                paths.append(dest)
                continue
            filters = {"event_date": f"{year}-01-01|{year}-12-31", "event_date_where": "BETWEEN"}
            if country:
                filters["country"] = country
            rows = acled_pages(token, filters)
            if not rows:
                log.warning("no ACLED events for %s in %s", country or "any country", year)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            partial = dest.with_suffix(".csv.part")
            with partial.open("w", encoding="utf-8", newline="") as out:
                writer = csv.DictWriter(out, fieldnames=list(rows[0]), extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            partial.replace(dest)
            log.info("downloaded %s (%s events)", dest.name, len(rows))
            paths.append(dest)
    return paths


def wdi_indicators(
    start_year: int, end_year: int, out_dir: Path, indicators: list[str] | None = None
) -> Path:
    """Saves every country's values for the WDI indicators to one CSV that `wdi.parse` reads.

    The World Bank revises past years, so the file is always fetched again.
    """
    rows: list[dict] = []
    for indicator in indicators or list(wdi.INDICATORS):
        page, pages = 1, 1
        while page <= pages:
            query = urllib.parse.urlencode(
                {
                    "format": "json",
                    "date": f"{start_year}:{end_year}",
                    "per_page": WDI_PAGE_SIZE,
                    "page": page,
                }
            )
            request = urllib.request.Request(f"{WDI_URL.format(indicator=indicator)}?{query}")
            data = _request_json(request)
            # Errors come back as a one-element list holding a "message".
            if len(data) < 2:
                raise RuntimeError(f"World Bank API error for {indicator}: {data}")
            pages = data[0]["pages"]
            rows += [
                {
                    "indicator": indicator,
                    "countryiso3code": r["countryiso3code"],
                    "date": r["date"],
                    "value": r["value"],
                }
                for r in data[1] or []
            ]
            page += 1
        log.info("fetched WDI %s", indicator)

    dest = out_dir / "wdi" / f"wdi-{start_year}-{end_year}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(".csv.part")
    with partial.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=["indicator", "countryiso3code", "date", "value"])
        writer.writeheader()
        writer.writerows(rows)
    partial.replace(dest)
    log.info("downloaded %s (%s values)", dest.name, len(rows))
    return dest


def epr_core(version: str, out_dir: Path) -> Path:
    url = EPR_URL.format(version=version)
    return fetch(url, out_dir / "epr" / Path(url).name)

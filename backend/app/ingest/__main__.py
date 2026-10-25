"""Command line entry point.

python -m app.ingest download gdelt --start 2022-02-01 --end 2022-02-28
python -m app.ingest live
python -m app.ingest download ucdp --version 26.1
python -m app.ingest download ucdp-candidate --start-year 2026
python -m app.ingest download acled --start-year 2018 --end-year 2024 --country Ukraine
python -m app.ingest download wdi --start-year 1989 --end-year 2025
python -m app.ingest download epr
python -m app.ingest load ucdp data/ucdp/ged261-csv.zip
python -m app.ingest load ucdp data/ucdp/GEDEvent_v26_0_*.csv
python -m app.ingest load acled data/acled/*.csv
python -m app.ingest load gdelt data/gdelt/*.zip
python -m app.ingest load wdi data/wdi/wdi-1989-2025.csv
python -m app.ingest load epr data/epr/EPR-2021.csv
python -m app.ingest load vdem V-Dem-CY-Core-v16.csv
python -m app.ingest build-features --start 2022-01 --end 2022-12
python -m app.ingest prune-gdelt-ids --days 30
"""

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from app.config import get_settings
from app.db import session_factory
from app.features import build_cell_months
from app.ingest import download
from app.ingest.loader import SOURCES, ingest_file, load_gdelt_live, prune_gdelt_ids


def _month(value: str) -> date:
    """Accepts 2022-03 or any date in the month."""
    return date.fromisoformat(value + "-01" if len(value) == 7 else value).replace(day=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingest")
    commands = parser.add_subparsers(dest="command", required=True)

    load = commands.add_parser("load", help="load source files into the database")
    load.add_argument("source", choices=SOURCES)
    load.add_argument("paths", nargs="+", type=Path)

    fetch = commands.add_parser("download", help="download raw source files")
    fetch.add_argument("source", choices=["acled", "epr", "gdelt", "ucdp", "ucdp-candidate", "wdi"])
    fetch.add_argument("--start", type=date.fromisoformat, help="GDELT: first day")
    fetch.add_argument("--end", type=date.fromisoformat, help="GDELT: last day")
    fetch.add_argument("--version", default="26.1", help="UCDP GED release, e.g. 26.1")
    fetch.add_argument("--start-year", type=int, help="ACLED, WDI, UCDP Candidate: first year")
    fetch.add_argument("--end-year", type=int, help="ACLED, WDI: last year (default: start year)")
    fetch.add_argument("--epr-version", default="2021", help="EPR Core release year")
    fetch.add_argument(
        "--country", action="append", default=[], help="ACLED: country name, repeatable"
    )
    fetch.add_argument("--out", type=Path, default=Path("data"))

    live = commands.add_parser(
        "live", help="download and load GDELT 2.0's 15-minute files posted since the last load"
    )
    live.add_argument(
        "--max-files", type=int, default=96, help="at most this many quarter hours (default: a day)"
    )
    live.add_argument("--out", type=Path, default=Path("data"))

    prune = commands.add_parser(
        "prune-gdelt-ids", help="stop adding newly found articles to old GDELT events"
    )
    prune.add_argument("--days", type=int, default=30)

    build = commands.add_parser(
        "build-features", help="rebuild cell-month features from the loaded events"
    )
    build.add_argument("--start", type=_month, required=True, help="first month, YYYY-MM")
    build.add_argument("--end", type=_month, help="last month, YYYY-MM (default: start)")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "build-features":
        with session_factory()() as session:
            build_cell_months(session, args.start, args.end or args.start)
        return 0

    if args.command == "live":
        with session_factory()() as session:
            return 0 if load_gdelt_live(session, args.out, args.max_files) else 1

    if args.command == "prune-gdelt-ids":
        with session_factory()() as session:
            logging.info("forgot %d GDELT ids", prune_gdelt_ids(session, args.days))
        return 0

    if args.command == "download":
        if args.source == "ucdp":
            download.ucdp_ged(args.version, args.out)
        elif args.source == "ucdp-candidate":
            # By default, the year of last month's file and the current one, so January
            # still picks up December's.
            today = date.today()
            start = args.start_year or (today.replace(day=1) - timedelta(days=1)).year
            download.ucdp_candidate(start, args.end_year or today.year, args.out)
        elif args.source == "epr":
            download.epr_core(args.epr_version, args.out)
        elif args.source == "wdi":
            if not args.start_year:
                parser.error("WDI downloads need --start-year")
            download.wdi_indicators(args.start_year, args.end_year or args.start_year, args.out)
        elif args.source == "acled":
            settings = get_settings()
            if not (settings.acled_email and settings.acled_password):
                parser.error("ACLED downloads need ACLED_EMAIL and ACLED_PASSWORD in .env")
            if not args.start_year:
                parser.error("ACLED downloads need --start-year")
            download.acled_events(
                settings.acled_email,
                settings.acled_password,
                args.start_year,
                args.end_year or args.start_year,
                args.country,
                args.out,
            )
        else:
            if not args.start:
                parser.error("GDELT downloads need --start")
            download.gdelt_daily(args.start, args.end or args.start, args.out)
        return 0

    failed = 0
    with session_factory()() as session:
        for path in args.paths:
            run = ingest_file(session, args.source, path)
            failed += run.status != "succeeded"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

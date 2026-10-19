"""Command line entry point.

python -m app.ingest download gdelt --start 2022-02-01 --end 2022-02-28
python -m app.ingest download ucdp --version 25.1
python -m app.ingest load ucdp data/ucdp/ged251-csv.zip
python -m app.ingest load gdelt data/gdelt/*.zip
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from app.db import session_factory
from app.ingest import download
from app.ingest.loader import PARSERS, ingest_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingest")
    commands = parser.add_subparsers(dest="command", required=True)

    load = commands.add_parser("load", help="load source files into the database")
    load.add_argument("source", choices=sorted(PARSERS))
    load.add_argument("paths", nargs="+", type=Path)

    fetch = commands.add_parser("download", help="download raw source files")
    fetch.add_argument("source", choices=["gdelt", "ucdp"])
    fetch.add_argument("--start", type=date.fromisoformat, help="GDELT: first day")
    fetch.add_argument("--end", type=date.fromisoformat, help="GDELT: last day")
    fetch.add_argument("--version", default="25.1", help="UCDP GED release, e.g. 25.1")
    fetch.add_argument("--out", type=Path, default=Path("data"))

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "download":
        if args.source == "ucdp":
            download.ucdp_ged(args.version, args.out)
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

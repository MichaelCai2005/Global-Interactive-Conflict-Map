"""Command line for the live recorders; see app/live/__init__.py for examples."""

import argparse
import logging
import sys
import time
from datetime import date

from app.config import get_settings
from app.db import session_factory
from app.live import feeds

log = logging.getLogger("app.live")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.live")
    commands = parser.add_subparsers(dest="command", required=True)

    adsb = commands.add_parser("adsb", help="record military aircraft positions from adsb.lol")
    adsb.add_argument("--interval", type=int, default=120, help="seconds between polls")
    adsb.add_argument("--once", action="store_true", help="poll once and stop")

    firms = commands.add_parser("firms", help="record NASA FIRMS fire detections")
    firms.add_argument("--bbox", required=True, help="west,south,east,north")
    firms.add_argument("--start", type=date.fromisoformat, required=True)
    firms.add_argument("--days", type=int, default=1)
    firms.add_argument(
        "--source",
        default="VIIRS_SNPP_NRT",
        help="VIIRS_SNPP_NRT, VIIRS_NOAA20_NRT, MODIS_NRT, or a _SP archive",
    )

    old = commands.add_parser("prune", help="delete old observations")
    old.add_argument("--days", type=int, default=90)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    make_session = session_factory()

    if args.command == "prune":
        with make_session() as db:
            log.info("deleted %d observations", feeds.prune(db, args.days))
        return 0

    if args.command == "firms":
        key = get_settings().firms_map_key
        if not key:
            parser.error("set FIRMS_MAP_KEY (free from firms.modaps.eosdis.nasa.gov/api/map_key)")
        rows = feeds.fetch_firms(key, args.bbox, args.start, args.days, args.source)
        with make_session() as db:
            log.info("FIRMS: %d detections, %d new", len(rows), feeds.store(db, rows))
        return 0

    # adsb: poll until stopped. A failed poll is logged and retried next interval.
    while True:
        try:
            rows = feeds.fetch_adsb_mil()
            with make_session() as db:
                new = feeds.store(db, rows)
            log.info("adsb.lol military: %d aircraft, %d new positions", len(rows), new)
        except Exception as e:  # noqa: BLE001
            # One bad poll (a feed hiccup, a database restart) must not end a recorder
            # meant to run for days; the next poll tries again.
            log.warning("poll failed: %s", e)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(max(30, args.interval))


if __name__ == "__main__":
    sys.exit(main())

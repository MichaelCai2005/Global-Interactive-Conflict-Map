"""Copy the local database to a hosted one (Neon, Supabase, any Postgres with PostGIS).

python -m app.publish copy --target "postgresql+psycopg://user:pass@host/db?sslmode=require"
python -m app.publish copy --target ... --since 2010-01-01 --without gdelt
python -m app.publish check --url "postgresql+psycopg://..."

The copy leaves out what a public site must not show. ACLED's license forbids publishing
its events, so ACLED events, links to them and board nodes built on them stay behind. An
event whose canonical twin was an ACLED event becomes canonical itself, so it shows on the
map. Cell-month features and risk scores are rebuilt on the target from what was copied,
so no total there counts ACLED either. Rejected rows and the watchlist and tasks (personal
notes) stay behind as well; --with-workspace copies the notes.

The target gets the schema from the migrations, then rows stream over with binary COPY in
one transaction, so a failed copy leaves nothing half done. Use the provider's direct
connection, not a pooled one: COPY and temporary tables need a real session.
"""

import argparse
import logging
import os
import sys
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import psycopg
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, make_url
from sqlalchemy.engine import Connection
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.config import get_settings
from app.features import build_cell_months
from app.risk import build as build_risk
from app.security import UNPUBLISHABLE

log = logging.getLogger("app.publish")

# Every table the migrations create, children after parents. TRUNCATE uses all of them.
TABLES = (
    "ingest_runs",
    "events",
    "event_links",
    "country_indicators",
    "rejected_records",
    "watch_items",
    "analyst_tasks",
    "cell_month_features",
    "risk_countries",
    "risk_scores",
    "observations",
    "boards",
    "board_nodes",
    "board_links",
)

# What each copied table sends: the FROM clause and, per column, an expression to send
# instead of the column itself. Temporary tables kept_runs, kept_events and kept_nodes
# (built in _choose_rows) hold the ids that survive the filters.
COPIES: dict[str, tuple[str, dict[str, str]]] = {
    "ingest_runs": ("ingest_runs t JOIN kept_runs k ON k.id = t.id", {}),
    "events": (
        "events t JOIN kept_events k ON k.id = t.id"
        " LEFT JOIN kept_events d ON d.id = t.duplicate_of_id",
        {"duplicate_of_id": "d.id"},
    ),
    "event_links": (
        "event_links t JOIN kept_events a ON a.id = t.event_id"
        " JOIN kept_events b ON b.id = t.related_event_id",
        {},
    ),
    "country_indicators": ("country_indicators t JOIN kept_runs k ON k.id = t.ingest_run_id", {}),
    "observations": ("observations t", {}),
    "boards": ("boards t", {}),
    "board_nodes": (
        "board_nodes t JOIN kept_nodes k ON k.id = t.id"
        " LEFT JOIN kept_events e ON e.id = t.event_id",
        {"event_id": "e.id"},
    ),
    "board_links": (
        "board_links t JOIN kept_nodes a ON a.id = t.from_node_id"
        " JOIN kept_nodes b ON b.id = t.to_node_id",
        {},
    ),
}
WORKSPACE_COPIES: dict[str, tuple[str, dict[str, str]]] = {
    "watch_items": ("watch_items t", {}),
    "analyst_tasks": (
        "analyst_tasks t LEFT JOIN kept_events e ON e.id = t.event_id",
        {"event_id": "e.id"},
    ),
}


def libpq_url(url: str) -> str:
    """SQLAlchemy's postgresql+psycopg://... as the plain postgresql://... psycopg takes."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def licence_problems(conn: Connection) -> list[str]:
    """What in this database a public deployment must not show; empty when it is clean."""
    problems = []
    for source in UNPUBLISHABLE:
        # The (source, dedupe_key) unique index answers this without a scan.
        if conn.exec_driver_sql(
            "SELECT 1 FROM events WHERE source = %(s)s LIMIT 1", {"s": source}
        ).first():
            problems.append(f"events from {source}")
        if conn.exec_driver_sql(
            "SELECT 1 FROM board_nodes WHERE source_name ILIKE %(p)s LIMIT 1", {"p": f"%{source}%"}
        ).first():
            problems.append(f"board nodes citing {source}")
    return problems


def _alembic(url: str) -> Config:
    # No alembic.ini: its logging section would silence this module's progress lines.
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parent.parent / "alembic")
    )
    config.attributes["database_url"] = url
    return config


def _revision(conn: psycopg.Connection) -> str | None:
    row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return row[0] if row else None


def _columns(conn: psycopg.Connection, table: str) -> list[str]:
    """Columns COPY can write: generated ones (geog, priogrid_gid) are left out."""
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = 'public' AND table_name = %s AND is_generated = 'NEVER'"
        " ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    return [r[0] for r in rows]


def _choose_rows(src: psycopg.Connection, since: date | None, without: Sequence[str]) -> None:
    """Fills the temporary id tables the COPIES queries join on."""
    dropped = list(UNPUBLISHABLE) + list(without)
    src.execute("CREATE TEMP TABLE kept_runs (id integer PRIMARY KEY) ON COMMIT DROP")
    src.execute(
        "INSERT INTO kept_runs SELECT id FROM ingest_runs WHERE source <> ALL(%s)", (dropped,)
    )
    src.execute("CREATE TEMP TABLE kept_events (id bigint PRIMARY KEY) ON COMMIT DROP")
    src.execute(
        "INSERT INTO kept_events SELECT id FROM events"
        " WHERE source <> ALL(%s) AND (%s::date IS NULL OR event_date >= %s::date)",
        (dropped, since, since),
    )
    # A board node built on an ACLED event goes, and so does one naming ACLED as its
    # source; one built on an event cut by --since or --without keeps its text and loses
    # only the link to the event.
    src.execute("CREATE TEMP TABLE kept_nodes (id bigint PRIMARY KEY) ON COMMIT DROP")
    src.execute(
        "INSERT INTO kept_nodes SELECT n.id FROM board_nodes n"
        " LEFT JOIN events e ON e.id = n.event_id"
        " WHERE coalesce(e.source, '') <> ALL(%s)"
        " AND NOT coalesce(n.source_name, '') ILIKE ANY(%s)",
        (list(UNPUBLISHABLE), [f"%{s}%" for s in UNPUBLISHABLE]),
    )
    src.execute("ANALYZE kept_runs, kept_events, kept_nodes")


def _copy_table(
    src: psycopg.Connection, dst: psycopg.Connection, table: str, plan: tuple[str, dict[str, str]]
) -> int:
    source, replaced = plan
    columns = _columns(dst, table)
    select = sql.SQL(", ").join(
        sql.SQL(replaced[c]) if c in replaced else sql.SQL("t.") + sql.Identifier(c)
        for c in columns
    )
    out = sql.SQL("COPY (SELECT {} FROM {}) TO STDOUT (FORMAT BINARY)").format(
        select, sql.SQL(source)
    )
    into = sql.SQL("COPY {} ({}) FROM STDIN (FORMAT BINARY)").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns))
    )
    started = time.monotonic()
    with src.cursor() as read, dst.cursor() as write:
        with read.copy(out) as reader, write.copy(into) as writer:
            for chunk in reader:
                writer.write(chunk)
        rows = read.rowcount
    log.info("%-20s %9d rows in %.0fs", table, rows, time.monotonic() - started)
    return rows


def _reset_sequences(dst: psycopg.Connection) -> None:
    """Points each id sequence past the copied ids, so new rows don't collide."""
    sequences = dst.execute(
        "SELECT table_name, pg_get_serial_sequence(table_name, 'id')"
        " FROM information_schema.columns"
        " WHERE table_schema = 'public' AND column_name = 'id' AND table_name = ANY(%s)",
        (list(TABLES),),
    ).fetchall()
    for table, seq in sequences:
        if seq:
            dst.execute(
                sql.SQL("SELECT setval(%s, coalesce(max(id), 0) + 1, false) FROM {}").format(
                    sql.Identifier(table)
                ),
                (seq,),
            )


def copy_database(
    source_url: str,
    target_url: str,
    since: date | None = None,
    without: Sequence[str] = (),
    workspace: bool = False,
    replace: bool = False,
) -> None:
    if make_url(source_url) == make_url(target_url):
        raise SystemExit("source and target are the same database")
    log.info("migrating the target to the current schema")
    command.upgrade(_alembic(target_url), "head")

    plans = dict(COPIES) | (WORKSPACE_COPIES if workspace else {})
    with (
        psycopg.connect(libpq_url(source_url)) as src,
        psycopg.connect(libpq_url(target_url)) as dst,
    ):
        if _revision(src) != _revision(dst):
            raise SystemExit(
                f"schema mismatch: source is at {_revision(src)}, target at {_revision(dst)};"
                " run `alembic upgrade head` on the source first"
            )
        if dst.execute("SELECT 1 FROM events LIMIT 1").fetchone() and not replace:
            raise SystemExit("the target already has events; pass --replace to overwrite it")
        # One snapshot of the source, so rows loaded during the copy don't half arrive. The
        # source transaction writes nothing but its temporary tables.
        src.rollback()
        src.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        _choose_rows(src, since, without)
        months = src.execute("SELECT min(month), max(month) FROM cell_month_features").fetchone()

        dst.execute(
            sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(map(sql.Identifier, TABLES))
            )
        )
        for table in TABLES:
            if table in plans:
                _copy_table(src, dst, table, plans[table])
        _reset_sequences(dst)
        dst.commit()

    engine = create_engine(target_url)
    try:
        with sessionmaker(bind=engine)() as session:
            first, last = months
            if first:
                first = max(first, since.replace(day=1)) if since else first
                log.info("rebuilding cell-month features %s to %s", first, last)
                build_cell_months(session, first, last)
            log.info("rebuilding risk scores")
            build_risk(session)
        with engine.connect() as conn:
            if problems := licence_problems(conn):
                raise SystemExit(f"the target still holds {', '.join(problems)}")
            size = conn.exec_driver_sql(
                "SELECT pg_size_pretty(pg_database_size(current_database()))"
            ).scalar()
        log.info("done: the target holds no ACLED data and takes %s", size)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.publish")
    commands = parser.add_subparsers(dest="command", required=True)

    copy = commands.add_parser("copy", help="copy the local database to a hosted one")
    copy.add_argument(
        "--target",
        default=os.environ.get("TARGET_DATABASE_URL"),
        help="hosted database URL (or TARGET_DATABASE_URL); postgresql+psycopg://...",
    )
    copy.add_argument(
        "--source", help="database to copy from (default: DATABASE_URL, the local one)"
    )
    copy.add_argument("--since", type=date.fromisoformat, help="only events on or after this date")
    copy.add_argument(
        "--without",
        action="append",
        default=[],
        choices=["gdelt", "ucdp"],
        help="leave out a source's events too (repeatable), to fit a small free tier",
    )
    copy.add_argument("--with-workspace", action="store_true", help="copy watchlist and tasks")
    copy.add_argument("--replace", action="store_true", help="overwrite a target that has data")

    check = commands.add_parser("check", help="list data a public deployment must not show")
    check.add_argument("--url", help="database to check (default: DATABASE_URL)")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "check":
        engine = create_engine(args.url or get_settings().database_url)
        with engine.connect() as conn:
            problems = licence_problems(conn)
        engine.dispose()
        for p in problems:
            log.error("not publishable: %s", p)
        if not problems:
            log.info("nothing unpublishable found")
        return 1 if problems else 0

    if not args.target:
        parser.error("give --target or set TARGET_DATABASE_URL")
    copy_database(
        args.source or get_settings().database_url,
        args.target,
        since=args.since,
        without=args.without,
        workspace=args.with_workspace,
        replace=args.replace,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Country codes and PRIO-GRID cells on events, country-year indicators, cell-month features.

Events loaded before this revision have no country_iso3; loading their files again fills it.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19
"""

from alembic import op
from app.models import PRIOGRID_GID_SQL

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE events ADD COLUMN country_iso3 varchar(3)")
    op.execute(
        f"ALTER TABLE events ADD COLUMN priogrid_gid integer GENERATED ALWAYS AS ({PRIOGRID_GID_SQL}) STORED"
    )
    op.execute("CREATE INDEX ix_events_country_iso3 ON events (country_iso3)")
    op.execute(
        "CREATE INDEX ix_events_priogrid_month ON events (priogrid_gid, event_date) "
        "WHERE priogrid_gid IS NOT NULL"
    )
    op.execute("""
        CREATE TABLE country_indicators (
            source varchar(32) NOT NULL,
            indicator varchar(64) NOT NULL,
            iso3 varchar(3) NOT NULL,
            year smallint NOT NULL,
            value double precision NOT NULL,
            ingest_run_id integer NOT NULL REFERENCES ingest_runs(id),
            PRIMARY KEY (source, indicator, iso3, year)
        )
    """)
    op.execute("CREATE INDEX ix_country_indicators_iso3_year ON country_indicators (iso3, year)")
    counts = [
        "ucdp_events", "ucdp_fatalities", "violent_events", "acled_events", "acled_fatalities",
        "acled_protests", "acled_riots", "gdelt_threats", "gdelt_protests", "gdelt_force_posture",
        "gdelt_coercion", "gdelt_violence", "gdelt_mentions", "ucdp_fatalities_last1m",
        "ucdp_fatalities_last3m", "ucdp_fatalities_last12m", "ucdp_fatalities_last36m",
        "neighbour_fatalities_last1m", "neighbour_fatalities_last12m", "gdelt_protests_last3m",
        "gdelt_threats_last3m",
    ]  # fmt: skip
    count_columns = ",\n".join(f"{c} integer NOT NULL" for c in counts)
    op.execute(f"""
        CREATE TABLE cell_month_features (
            gid integer NOT NULL CHECK (gid BETWEEN 1 AND 259200),
            month date NOT NULL CHECK (extract(day FROM month) = 1),
            iso3 varchar(3),
            {count_columns},
            gdelt_tone double precision,
            months_since_violence integer,
            built_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (gid, month)
        )
    """)
    op.execute("CREATE INDEX ix_cell_month_features_month ON cell_month_features (month)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cell_month_features")
    op.execute("DROP TABLE IF EXISTS country_indicators")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS priogrid_gid")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS country_iso3")

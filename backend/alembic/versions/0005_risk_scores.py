"""Weekly risk scores per country, built by `python -m app.risk build`.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE risk_countries (
            iso3 varchar(3) PRIMARY KEY,
            name varchar(128) NOT NULL,
            latitude double precision,
            longitude double precision,
            neighbours varchar(3)[] NOT NULL DEFAULT '{}'
        )
    """)
    op.execute("""
        CREATE TABLE risk_scores (
            iso3 varchar(3) NOT NULL REFERENCES risk_countries(iso3) ON DELETE CASCADE,
            week date NOT NULL CHECK (extract(isodow FROM week) = 1),
            violent_events integer NOT NULL,
            deaths integer NOT NULL,
            gdelt_events integer NOT NULL,
            history double precision NOT NULL,
            surge_source varchar(32),
            surge_events integer,
            surge_baseline double precision,
            surge_z double precision,
            surge double precision NOT NULL,
            spread double precision NOT NULL,
            share_z double precision,
            goldstein_z double precision,
            tone_z double precision,
            signal double precision NOT NULL,
            points_history double precision NOT NULL,
            points_surge double precision NOT NULL,
            points_spread double precision NOT NULL,
            points_signal double precision NOT NULL,
            score double precision NOT NULL CHECK (score BETWEEN 0 AND 100),
            trend varchar(16),
            surge_alarm boolean NOT NULL,
            provisional boolean NOT NULL,
            PRIMARY KEY (iso3, week)
        )
    """)
    op.execute("CREATE INDEX ix_risk_scores_week_score ON risk_scores (week, score DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS risk_scores")
    op.execute("DROP TABLE IF EXISTS risk_countries")

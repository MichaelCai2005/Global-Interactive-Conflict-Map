"""Initial schema: ingest runs, events, cross-source links, rejected records.

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("""
        CREATE TABLE ingest_runs (
            id serial PRIMARY KEY,
            source varchar(32) NOT NULL,
            filename text NOT NULL,
            status varchar(16) NOT NULL DEFAULT 'running',
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            rows_read integer NOT NULL DEFAULT 0,
            filtered_out integer NOT NULL DEFAULT 0,
            rejected integer NOT NULL DEFAULT 0,
            merged_in_file integer NOT NULL DEFAULT 0,
            inserted integer NOT NULL DEFAULT 0,
            updated integer NOT NULL DEFAULT 0,
            cross_source_links integer NOT NULL DEFAULT 0,
            error text
        )
    """)
    op.execute("""
        CREATE TABLE events (
            id bigserial PRIMARY KEY,
            source varchar(32) NOT NULL,
            source_event_id varchar(64) NOT NULL,
            dedupe_key varchar(255) NOT NULL,
            event_date date NOT NULL,
            end_date date,
            event_type varchar(32) NOT NULL,
            is_violent boolean NOT NULL,
            country varchar(128),
            admin1 varchar(128),
            location_name text,
            latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
            longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
            geog geography(Point, 4326) GENERATED ALWAYS AS
                (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED,
            geo_precision varchar(16) NOT NULL
                CHECK (geo_precision IN ('exact', 'admin', 'country')),
            actor1 text,
            actor2 text,
            fatalities_best integer CHECK (fatalities_best >= 0),
            fatalities_low integer CHECK (fatalities_low >= 0),
            fatalities_high integer CHECK (fatalities_high >= 0),
            report_count integer NOT NULL DEFAULT 1,
            tone double precision,
            source_url text,
            conflict_id varchar(64),
            attributes jsonb NOT NULL DEFAULT '{}',
            duplicate_of_id bigint REFERENCES events(id) ON DELETE SET NULL,
            ingest_run_id integer NOT NULL REFERENCES ingest_runs(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_events_source_key UNIQUE (source, dedupe_key),
            CHECK (end_date IS NULL OR end_date >= event_date)
        )
    """)
    op.execute("CREATE INDEX ix_events_geog ON events USING gist (geog)")
    op.execute("CREATE INDEX ix_events_event_date ON events (event_date)")
    op.execute("CREATE INDEX ix_events_event_type ON events (event_type)")
    op.execute("CREATE INDEX ix_events_country ON events (lower(country))")
    op.execute("CREATE INDEX ix_events_conflict_id ON events (conflict_id)")
    op.execute("CREATE INDEX ix_events_duplicate_of_id ON events (duplicate_of_id)")
    op.execute("CREATE INDEX ix_events_ingest_run_id ON events (ingest_run_id)")
    op.execute("""
        CREATE TABLE event_links (
            id bigserial PRIMARY KEY,
            event_id bigint NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            related_event_id bigint NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            link_type varchar(32) NOT NULL,
            distance_km double precision NOT NULL,
            day_gap integer NOT NULL,
            score double precision NOT NULL,
            UNIQUE (event_id, related_event_id, link_type)
        )
    """)
    op.execute("CREATE INDEX ix_event_links_related ON event_links (related_event_id)")
    op.execute("""
        CREATE TABLE rejected_records (
            id bigserial PRIMARY KEY,
            ingest_run_id integer NOT NULL REFERENCES ingest_runs(id) ON DELETE CASCADE,
            source varchar(32) NOT NULL,
            row_number integer NOT NULL,
            reasons text[] NOT NULL,
            raw jsonb NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_rejected_records_run ON rejected_records (ingest_run_id)")


def downgrade() -> None:
    for table in ("rejected_records", "event_links", "events", "ingest_runs"):
        op.execute(f"DROP TABLE IF EXISTS {table}")

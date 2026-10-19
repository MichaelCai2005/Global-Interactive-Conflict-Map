"""Index violent, sub-country events by place and date range together for cross-source linking.

The geog index alone returns every event near a point from any year, which in dense areas
(Donbas, Aleppo) is thousands of rows per lookup. Indexing the date range alongside the
location lets a lookup skip everything outside the day window.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX ix_events_link_candidates ON events
        USING gist (geog, daterange(event_date, COALESCE(end_date, event_date), '[]'))
        WHERE is_violent AND geo_precision <> 'country'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_link_candidates")

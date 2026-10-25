"""Every article behind a GDELT event, and when GDELT first saw it.

`events.first_reported_at` is when GDELT first published an event (its DATEADDED, to the
quarter hour in GDELT 2.0's 15-minute files). The event date says when the news says it
happened; this says when it became news, which is what a "last 24 hours" view needs. GDELT
1.0's daily files only give the day, so events seen only there leave it empty.

GDELT keeps one URL per event row and lists every article in its Mentions files, keyed by
its own GLOBALEVENTID. The loader collapses many GLOBALEVENTIDs into one event, so
`gdelt_ids` remembers which event each one went into, and `event_sources` holds the
articles: one row per event and URL.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-24
"""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("first_reported_at", sa.DateTime(timezone=True)))
    op.execute(
        "CREATE INDEX ix_events_first_reported_at ON events (first_reported_at)"
        " WHERE first_reported_at IS NOT NULL"
    )
    op.create_table(
        "gdelt_ids",
        sa.Column("global_event_id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column(
            "event_id",
            sa.BigInteger,
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    op.create_table(
        "event_sources",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "event_id",
            sa.BigInteger,
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("source_name", sa.Text),
        sa.Column("first_seen_at", sa.DateTime(timezone=True)),
        # GDELT's 10-100 confidence that the article describes this event; empty for the
        # event row's own URL.
        sa.Column("confidence", sa.SmallInteger),
        sa.UniqueConstraint("event_id", "url", name="uq_event_sources_event_url"),
    )


def downgrade() -> None:
    op.drop_table("event_sources")
    op.drop_table("gdelt_ids")
    op.execute("DROP INDEX ix_events_first_reported_at")
    op.drop_column("events", "first_reported_at")

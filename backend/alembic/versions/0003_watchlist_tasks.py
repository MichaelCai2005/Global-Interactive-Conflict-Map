"""Watchlist items and analyst tasks for the map dashboard.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE watch_items (
            id serial PRIMARY KEY,
            name varchar(200) NOT NULL,
            country varchar(128),
            bbox varchar(100),
            notes text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (country IS NOT NULL OR bbox IS NOT NULL)
        )
    """)
    op.execute("""
        CREATE TABLE analyst_tasks (
            id serial PRIMARY KEY,
            title varchar(300) NOT NULL,
            notes text NOT NULL DEFAULT '',
            status varchar(16) NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'in_progress', 'done')),
            priority varchar(16) NOT NULL DEFAULT 'normal'
                CHECK (priority IN ('low', 'normal', 'high')),
            event_id bigint REFERENCES events(id) ON DELETE SET NULL,
            watch_item_id integer REFERENCES watch_items(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_analyst_tasks_event_id ON analyst_tasks (event_id)")
    op.execute("CREATE INDEX ix_analyst_tasks_watch_item_id ON analyst_tasks (watch_item_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analyst_tasks")
    op.execute("DROP TABLE IF EXISTS watch_items")

"""User accounts: people sign in and keep their own watchlist, tasks, boards and searches.

`users` holds an email and a scrypt password hash. `user_sessions` holds one row per
signed-in browser, keyed by the SHA-256 of the cookie's token so a database leak doesn't
hand out live sessions. `saved_searches` stores a named map view or board topic as JSON
for its owner to reopen; topic searches are also recorded as they run.

Watch items, tasks and boards gain an owner. Rows without one are the shared workspace a
local install (or the admin token) works in, so existing data stays where it was.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

OWNED = ("watch_items", "analyst_tasks", "boards")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )
    # Emails compare without case, so "A@x.org" can't sign up twice.
    op.execute("CREATE UNIQUE INDEX users_email_key ON users (lower(email))")

    op.create_table(
        "user_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.String(300), nullable=False, server_default=""),
    )

    op.create_table(
        "saved_searches",
        sa.Column("id", sa.Integer, primary_key=True),
        # None: the shared workspace's, like the owner columns below.
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("name", sa.String(200), nullable=False),
        # "map" (the dashboard's filters and view) or "topic" (a board topic search).
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("params", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )

    for table in OWNED:
        op.add_column(
            table,
            sa.Column(
                "user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True
            ),
        )
        op.create_index(f"{table}_user_id_idx", table, ["user_id"])


def downgrade() -> None:
    for table in OWNED:
        op.drop_index(f"{table}_user_id_idx", table)
        op.drop_column(table, "user_id")
    op.drop_table("saved_searches")
    op.drop_table("user_sessions")
    op.drop_table("users")

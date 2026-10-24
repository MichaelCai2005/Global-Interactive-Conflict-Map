"""Boards as mood boards: where each card sits on the canvas, and pictures.

`board_x`/`board_y` are a card's position on the board canvas, set when someone moves it;
cards without one are laid out by the frontend. `image_url` is a picture shown on the
card: a public http(s) link, or `/boards/images/<id>` for one uploaded to `board_images`.
A new kind, `link`, is a card that points to another web page.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-21
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

KINDS = ["article", "place", "actor", "claim", "event", "flight", "fire", "vessel", "note"]


def _kinds(kinds: list[str]) -> str:
    return ", ".join(f"'{k}'" for k in kinds)


def upgrade() -> None:
    op.execute("""
        ALTER TABLE board_nodes
            ADD COLUMN board_x double precision,
            ADD COLUMN board_y double precision,
            ADD COLUMN image_url text
    """)
    op.execute(f"""
        ALTER TABLE board_nodes DROP CONSTRAINT board_nodes_kind_check,
            ADD CONSTRAINT board_nodes_kind_check CHECK (kind IN ({_kinds(KINDS + ["link"])}))
    """)
    op.execute("""
        CREATE TABLE board_images (
            id bigserial PRIMARY KEY,
            board_id integer NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
            content_type varchar(64) NOT NULL,
            size_bytes integer NOT NULL,
            data bytea NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_board_images_board ON board_images (board_id)")


def downgrade() -> None:
    op.execute("DROP TABLE board_images")
    op.execute("DELETE FROM board_nodes WHERE kind = 'link'")
    op.execute(f"""
        ALTER TABLE board_nodes DROP CONSTRAINT board_nodes_kind_check,
            ADD CONSTRAINT board_nodes_kind_check CHECK (kind IN ({_kinds(KINDS)}))
    """)
    op.execute(
        "ALTER TABLE board_nodes DROP COLUMN board_x, DROP COLUMN board_y, DROP COLUMN image_url"
    )

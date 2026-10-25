"""Why a violent GDELT event is kept off the map.

`events.screened_out` names the reason a violent GDELT event is not armed conflict: an
article that is not about violence ("not_violence"), ordinary crime ("crime"), or a story
placed at its Washington dateline ("dateline", which the event endpoints already hid by
ADM1 code). The event endpoints hide screened events; the risk features still count them.
app.ingest.gdelt_screen holds the rules, and `python -m app.ingest screen-gdelt` applies
them again after they change.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-25
"""

import sqlalchemy as sa

from alembic import op
from app.ingest.gdelt_screen import rescreen

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("screened_out", sa.String(16)))
    rescreen(op.get_bind())


def downgrade() -> None:
    op.drop_column("events", "screened_out")

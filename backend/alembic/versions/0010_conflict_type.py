"""Which of UCDP's kinds of violence each violent event is, for every source.

`events.conflict_type` sorts violence the way UCDP does (state-based, non-state,
one-sided), so the map can color GDELT and ACLED events alike with UCDP's. UCDP's own
event type already is that, so it is copied. ACLED and GDELT rows are sorted by
app.conflict_type's rules, as `python -m app.ingest classify` does after they change.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-25
"""

import sqlalchemy as sa

from alembic import op
from app.conflict_type import reclassify

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("conflict_type", sa.String(16)))
    op.execute(
        "UPDATE events SET conflict_type = event_type WHERE source = 'ucdp'"
        " AND event_type IN ('state_based', 'non_state', 'one_sided')"
    )
    reclassify(op.get_bind())


def downgrade() -> None:
    op.drop_column("events", "conflict_type")

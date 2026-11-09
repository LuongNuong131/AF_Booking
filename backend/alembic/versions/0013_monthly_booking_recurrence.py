"""Persist monthly booking recurrence preferences and catch-up progress."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "booking_groups",
        sa.Column(
            "recurring_enabled", mysql.BOOLEAN(), nullable=False, server_default=sa.text("1")
        ),
    )
    op.add_column(
        "booking_groups",
        sa.Column(
            "recurring_through_period",
            mysql.CHAR(4, charset="ascii", collation="ascii_bin"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_booking_groups_recurring_due",
        "booking_groups",
        ["recurring_enabled", "recurring_through_period", "id"],
    )


def downgrade():
    op.drop_index("ix_booking_groups_recurring_due", table_name="booking_groups")
    op.drop_column("booking_groups", "recurring_through_period")
    op.drop_column("booking_groups", "recurring_enabled")

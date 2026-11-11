"""Persistent folder responsibility, independent of booking activity and month."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("assigned_to", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("assignment_region", mysql.VARCHAR(100), nullable=True),
        sa.Column("assignment_source_agent", mysql.VARCHAR(100), nullable=True),
        sa.Column("assignment_review", mysql.VARCHAR(1000), nullable=True),
        sa.Column("assignment_metadata", mysql.JSON(), nullable=True),
        sa.Column(
            "assignment_version", mysql.INTEGER(unsigned=True), nullable=False, server_default="1"
        ),
    ):
        op.add_column("booking_groups", column)
    op.create_index("ix_booking_groups_assigned_to", "booking_groups", ["assigned_to"])


def downgrade():
    op.drop_index("ix_booking_groups_assigned_to", table_name="booking_groups")
    for name in (
        "assignment_version",
        "assignment_metadata",
        "assignment_review",
        "assignment_source_agent",
        "assignment_region",
        "assigned_to",
    ):
        op.drop_column("booking_groups", name)

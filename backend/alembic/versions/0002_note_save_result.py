"""Persist idempotent note responses across retries and later booking updates."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "booking_notes",
        sa.Column(
            "request_fingerprint",
            mysql.CHAR(64, charset="ascii", collation="ascii_bin"),
            nullable=True,
        ),
    )
    op.add_column(
        "booking_notes", sa.Column("save_result", mysql.JSON(none_as_null=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("booking_notes", "save_result")
    op.drop_column("booking_notes", "request_fingerprint")

"""Remember a task creation result independently of later edits/completion."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "booking_tasks",
        sa.Column(
            "request_fingerprint",
            mysql.CHAR(64, charset="ascii", collation="ascii_bin"),
            nullable=True,
        ),
    )
    op.add_column(
        "booking_tasks", sa.Column("create_result", mysql.JSON(none_as_null=True), nullable=True)
    )


def downgrade():
    op.drop_column("booking_tasks", "create_result")
    op.drop_column("booking_tasks", "request_fingerprint")

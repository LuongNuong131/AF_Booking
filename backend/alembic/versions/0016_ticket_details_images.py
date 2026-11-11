"""Structured ticket titles and private images, preserving legacy tickets."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("booking_work_tasks", sa.Column("issue_type", mysql.VARCHAR(40), nullable=True))
    op.add_column("booking_work_tasks", sa.Column("title", mysql.VARCHAR(255), nullable=True))
    op.alter_column(
        "attachments", "note_id", existing_type=mysql.BIGINT(unsigned=True), nullable=True
    )
    op.add_column(
        "attachments", sa.Column("work_task_id", mysql.BIGINT(unsigned=True), nullable=True)
    )
    op.create_index("ix_attachments_work_task_id", "attachments", ["work_task_id"])
    op.create_unique_constraint(
        "uq_attachment_work_task_storage", "attachments", ["work_task_id", "storage_key"]
    )


def downgrade():
    # Ticket images cannot be represented by the older schema. Refuse data loss.
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT COUNT(*) FROM attachments WHERE work_task_id IS NOT NULL")
    ):
        raise RuntimeError("Remove ticket images using the application before downgrading 0016.")
    op.drop_constraint("uq_attachment_work_task_storage", "attachments", type_="unique")
    op.drop_index("ix_attachments_work_task_id", table_name="attachments")
    op.drop_column("attachments", "work_task_id")
    op.alter_column(
        "attachments", "note_id", existing_type=mysql.BIGINT(unsigned=True), nullable=False
    )
    op.drop_column("booking_work_tasks", "title")
    op.drop_column("booking_work_tasks", "issue_type")

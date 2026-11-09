"""Add indexes for the per-user notification feed and completed-task list."""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_notifications_user_created_id",
        "notifications",
        ["user_id", "created_at", "id"],
    )
    op.create_index(
        "ix_booking_tasks_user_status_completed",
        "booking_tasks",
        ["user_id", "status", "completed_at", "id"],
    )


def downgrade():
    op.drop_index("ix_booking_tasks_user_status_completed", table_name="booking_tasks")
    op.drop_index("ix_notifications_user_created_id", table_name="notifications")

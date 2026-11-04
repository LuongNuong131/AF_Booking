"""Indexes for bounded operational-data retention; no existing data is deleted."""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_booking_notes_live_booking_created",
        "booking_notes",
        ["deleted_at", "booking_id", "id", "created_at"],
    )
    op.create_index("ix_notifications_read_id", "notifications", ["read_at", "id"])
    op.create_index(
        "ix_booking_tasks_status_updated", "booking_tasks", ["status", "updated_at", "id"]
    )


def downgrade():
    op.drop_index("ix_booking_notes_live_booking_created", table_name="booking_notes")
    op.drop_index("ix_booking_tasks_status_updated", table_name="booking_tasks")
    op.drop_index("ix_notifications_read_id", table_name="notifications")

"""Shared booking work requests and idempotent note image references."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

OLD_TYPES = ("taken_over", "stale", "task_due", "watch_update", "assigned", "assignment_done")


def notification_types(before, after):
    # TiDB rejects changing a column referenced by a generated column. Rebuild
    # this virtual projection and its index; the notification rows stay intact.
    tidb = "tidb" in op.get_bind().execute(sa.text("SELECT VERSION()")).scalar().lower()
    if tidb:
        op.drop_constraint("uq_notifications_unread_watch", "notifications", type_="unique")
        op.drop_column("notifications", "unread_watch_booking")
    try:
        op.alter_column(
            "notifications",
            "type",
            existing_type=mysql.ENUM(*before),
            type_=mysql.ENUM(*after),
            existing_nullable=False,
            existing_server_default="taken_over",
        )
    finally:
        if tidb:
            op.add_column(
                "notifications",
                sa.Column(
                    "unread_watch_booking",
                    mysql.BIGINT(unsigned=True),
                    sa.Computed(
                        "IF(type = 'watch_update' AND read_at IS NULL, booking_id, NULL)",
                        persisted=False,
                    ),
                ),
            )
            op.create_unique_constraint(
                "uq_notifications_unread_watch",
                "notifications",
                ["user_id", "unread_watch_booking"],
            )


def upgrade():
    op.create_table(
        "booking_work_tasks",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("booking_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("message", mysql.VARCHAR(2000), nullable=False),
        sa.Column(
            "status", mysql.ENUM("pending", "handled"), nullable=False, server_default="pending"
        ),
        sa.Column(
            "client_request_id",
            mysql.CHAR(36, charset="ascii", collation="ascii_bin"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column("handled_by", mysql.BIGINT(unsigned=True)),
        sa.Column("handled_at", mysql.DATETIME(fsp=3)),
        sa.Column("handling_note", mysql.VARCHAR(2000)),
        sa.UniqueConstraint("client_request_id", name="uq_work_task_request"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_work_tasks_status_created", "booking_work_tasks", ["status", "created_at", "id"]
    )
    op.create_index(
        "ix_work_tasks_creator_created", "booking_work_tasks", ["created_by", "created_at", "id"]
    )
    op.create_index("ix_work_tasks_booking", "booking_work_tasks", ["booking_id", "id"])
    op.create_unique_constraint(
        "uq_attachment_note_storage", "attachments", ["note_id", "storage_key"]
    )
    notification_types(OLD_TYPES, (*OLD_TYPES, "work_task_created", "work_task_handled"))


def downgrade():
    op.execute("DELETE FROM notifications WHERE type IN ('work_task_created','work_task_handled')")
    notification_types((*OLD_TYPES, "work_task_created", "work_task_handled"), OLD_TYPES)
    op.drop_constraint("uq_attachment_note_storage", "attachments", type_="unique")
    op.drop_table("booking_work_tasks")

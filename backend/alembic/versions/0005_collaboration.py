"""Watch subscriptions, assignments and bounded unread notification merging."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

OPTIONS = dict(mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci")
TYPES = ("taken_over", "stale", "task_due", "watch_update", "assigned", "assignment_done")


def upgrade():
    # The initial schema reserved these enum values; explicitly retain the full set.
    op.alter_column(
        "notifications",
        "type",
        type_=mysql.ENUM(*TYPES),
        existing_nullable=False,
        existing_server_default="taken_over",
    )
    op.add_column(
        "notifications",
        sa.Column(
            "merged_count", mysql.SMALLINT(unsigned=True), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "notifications",
        sa.Column(
            "unread_watch_booking",
            mysql.BIGINT(unsigned=True),
            sa.Computed(
                "IF(type = 'watch_update' AND read_at IS NULL, booking_id, NULL)", persisted=False
            ),
        ),
    )
    op.create_unique_constraint(
        "uq_notifications_unread_watch", "notifications", ["user_id", "unread_watch_booking"]
    )
    op.create_table(
        "booking_watchers",
        sa.Column("booking_id", mysql.BIGINT(unsigned=True), primary_key=True),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), primary_key=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        **OPTIONS,
    )
    op.create_index(
        "ix_booking_watchers_user_created", "booking_watchers", ["user_id", "created_at"]
    )
    op.create_table(
        "booking_assignments",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True),
        *[
            sa.Column(name, mysql.BIGINT(unsigned=True), nullable=False)
            for name in ("booking_id", "note_id", "from_user_id", "to_user_id")
        ],
        sa.Column("message", mysql.VARCHAR(255), nullable=True),
        sa.Column(
            "status", mysql.ENUM("open", "done", "declined"), nullable=False, server_default="open"
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column("resolved_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("decline_reason", mysql.VARCHAR(255), nullable=True),
        sa.Column(
            "open_to_user_id",
            mysql.BIGINT(unsigned=True),
            sa.Computed("IF(status = 'open', to_user_id, NULL)", persisted=False),
        ),
        sa.UniqueConstraint("booking_id", "open_to_user_id", name="uq_assignments_open_recipient"),
        **OPTIONS,
    )
    op.create_index(
        "ix_assignments_to_status_created",
        "booking_assignments",
        ["to_user_id", "status", "created_at"],
    )
    op.create_index(
        "ix_assignments_from_status_created",
        "booking_assignments",
        ["from_user_id", "status", "created_at"],
    )
    op.create_index("ix_assignments_booking", "booking_assignments", ["booking_id"])


def downgrade():
    op.drop_table("booking_assignments")
    op.drop_table("booking_watchers")
    op.drop_constraint("uq_notifications_unread_watch", "notifications", type_="unique")
    op.drop_column("notifications", "unread_watch_booking")
    op.drop_column("notifications", "merged_count")
    # Enum values existed before 0005; removing them could destroy historical data.

"""Create booking tracker schema

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def canonical_key_constraints() -> list[sa.CheckConstraint]:
    bind = op.get_bind()
    version = str(bind.exec_driver_sql("SELECT VERSION()").scalar_one())
    if "tidb" in version.lower():
        enabled = str(
            bind.exec_driver_sql("SELECT @@tidb_enable_check_constraint").scalar_one()
        ).lower() in {"1", "on"}
    else:
        enabled = (bind.dialect.server_version_info or ()) >= (8, 0, 16)
    if not enabled:
        import logging

        logging.getLogger(__name__).warning(
            "CHECK enforcement is unavailable; canonical key validation is required on writes."
        )
        return []
    return [
        sa.CheckConstraint(
            "booking_key = UPPER(booking_key) AND booking_key NOT LIKE '% %'",
            name=op.f("ck_bookings_canonical_key"),
        )
    ]


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("note_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("file_name", mysql.VARCHAR(length=255), nullable=False),
        sa.Column("mime_type", mysql.VARCHAR(length=100), nullable=False),
        sa.Column("size_bytes", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("storage_key", mysql.VARCHAR(length=512), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("ix_attachments_note_id", "attachments", ["note_id"], unique=False)
    op.create_table(
        "audit_logs",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("action", mysql.VARCHAR(length=60), nullable=False),
        sa.Column("entity_type", mysql.VARCHAR(length=40), nullable=True),
        sa.Column("entity_id", mysql.VARCHAR(length=60), nullable=True),
        sa.Column("meta", mysql.JSON(none_as_null=True), nullable=True),
        sa.Column("ip", mysql.VARCHAR(length=45), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index(
        "ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"], unique=False
    )
    op.create_index(
        "ix_audit_logs_user_created", "audit_logs", ["user_id", "created_at"], unique=False
    )
    op.create_table(
        "booking_groups",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "cw_number",
            mysql.VARCHAR(charset="ascii", collation="ascii_bin", length=12),
            nullable=False,
        ),
        sa.Column(
            "station_code",
            mysql.VARCHAR(charset="ascii", collation="ascii_bin", length=4),
            nullable=False,
        ),
        sa.Column("supplier_name", mysql.VARCHAR(length=255), nullable=False),
        sa.Column("supplier_name_normalized", mysql.VARCHAR(length=255), nullable=False),
        sa.Column("supplier_type", mysql.ENUM("hotel", "transportation"), nullable=False),
        sa.Column(
            "booking_count",
            mysql.INTEGER(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "last_activity_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_groups")),
        sa.UniqueConstraint("cw_number", name="cw_number"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("ix_booking_groups_created_by", "booking_groups", ["created_by"], unique=False)
    op.create_index(
        "ix_booking_groups_last_activity_at", "booking_groups", ["last_activity_at"], unique=False
    )
    op.create_index(
        "ix_booking_groups_station_type_activity",
        "booking_groups",
        ["station_code", "supplier_type", "last_activity_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_booking_groups_supplier_name_normalized",
        "booking_groups",
        ["supplier_name_normalized"],
        unique=False,
    )
    op.create_table(
        "booking_invoices",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("booking_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "invoice_number",
            mysql.VARCHAR(charset="ascii", collation="ascii_bin", length=40),
            nullable=False,
        ),
        sa.Column("added_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_invoices")),
        sa.UniqueConstraint("booking_id", "invoice_number", name="uq_booking_invoices_number"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("ix_booking_invoices_added_by", "booking_invoices", ["added_by"], unique=False)
    op.create_index(
        "ix_booking_invoices_invoice_number", "booking_invoices", ["invoice_number"], unique=False
    )
    op.create_table(
        "booking_notes",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("booking_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("agent_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("status_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("position_label", mysql.VARCHAR(length=60), nullable=False),
        sa.Column("note", mysql.TEXT(), nullable=True),
        sa.Column(
            "client_request_id",
            mysql.CHAR(charset="ascii", collation="ascii_bin", length=36),
            nullable=True,
        ),
        sa.Column("deleted_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("deleted_by", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("delete_reason", mysql.VARCHAR(length=255), nullable=True),
        sa.Column("invoice_change", mysql.JSON(none_as_null=True), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_notes")),
        sa.UniqueConstraint("client_request_id", name="client_request_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_booking_notes_agent_created", "booking_notes", ["agent_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_booking_notes_booking_created",
        "booking_notes",
        ["booking_id", "created_at", "id"],
        unique=False,
    )
    op.create_index("ix_booking_notes_created_at", "booking_notes", ["created_at"], unique=False)
    op.create_index("ix_booking_notes_deleted_at", "booking_notes", ["deleted_at"], unique=False)
    op.create_index("ix_booking_notes_deleted_by", "booking_notes", ["deleted_by"], unique=False)
    op.create_index("ix_booking_notes_status_id", "booking_notes", ["status_id"], unique=False)
    op.create_table(
        "booking_tasks",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("booking_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("note_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("message", mysql.VARCHAR(length=255), nullable=False),
        sa.Column("remind_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column(
            "status",
            mysql.ENUM("pending", "done", "cancelled"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("notified_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "snooze_count",
            mysql.SMALLINT(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "client_request_id",
            mysql.CHAR(charset="ascii", collation="ascii_bin", length=36),
            nullable=True,
        ),
        sa.Column("completed_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_tasks")),
        sa.UniqueConstraint("client_request_id", name="client_request_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_booking_tasks_booking_user_status",
        "booking_tasks",
        ["booking_id", "user_id", "status"],
        unique=False,
    )
    op.create_index("ix_booking_tasks_note_id", "booking_tasks", ["note_id"], unique=False)
    op.create_index(
        "ix_booking_tasks_status_notified_remind",
        "booking_tasks",
        ["status", "notified_at", "remind_at"],
        unique=False,
    )
    op.create_index(
        "ix_booking_tasks_user_status_remind",
        "booking_tasks",
        ["user_id", "status", "remind_at"],
        unique=False,
    )
    op.create_table(
        "bookings",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "booking_key",
            mysql.VARCHAR(charset="ascii", collation="ascii_bin", length=32),
            nullable=False,
        ),
        sa.Column("group_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "cw_number",
            mysql.VARCHAR(charset="ascii", collation="ascii_bin", length=12),
            nullable=False,
        ),
        sa.Column(
            "station_code",
            mysql.VARCHAR(charset="ascii", collation="ascii_bin", length=4),
            nullable=False,
        ),
        sa.Column(
            "period", mysql.CHAR(charset="ascii", collation="ascii_bin", length=4), nullable=False
        ),
        sa.Column("last_note_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("last_agent_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("last_status_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("last_position", mysql.VARCHAR(length=60), nullable=True),
        sa.Column("last_note_preview", mysql.VARCHAR(length=255), nullable=True),
        sa.Column("is_done", sa.BOOLEAN(), server_default=sa.text("0"), nullable=False),
        sa.Column("done_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column("stale_notified_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "version", mysql.INTEGER(unsigned=True), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "invoice_state",
            mysql.ENUM("unknown", "has_invoice", "no_invoice"),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column(
            "invoice_count",
            mysql.INTEGER(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        *canonical_key_constraints(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bookings")),
        sa.UniqueConstraint("booking_key", name="booking_key"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_bookings_agent_updated", "bookings", ["last_agent_id", "updated_at", "id"], unique=False
    )
    op.create_index("ix_bookings_cw_period", "bookings", ["cw_number", "period"], unique=False)
    op.create_index(
        "ix_bookings_done_updated", "bookings", ["is_done", "updated_at", "id"], unique=False
    )
    op.create_index(
        "ix_bookings_group_period", "bookings", ["group_id", "period", "id"], unique=False
    )
    op.create_index("ix_bookings_last_note_id", "bookings", ["last_note_id"], unique=False)
    op.create_index(
        "ix_bookings_station_period", "bookings", ["station_code", "period", "id"], unique=False
    )
    op.create_index(
        "ix_bookings_status_updated",
        "bookings",
        ["last_status_id", "updated_at", "id"],
        unique=False,
    )
    op.create_index("ix_bookings_updated_at", "bookings", ["updated_at", "id"], unique=False)
    op.create_table(
        "notifications",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("booking_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "type",
            mysql.ENUM(
                "taken_over", "stale", "task_due", "watch_update", "assigned", "assignment_done"
            ),
            server_default="taken_over",
            nullable=False,
        ),
        sa.Column("task_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("note_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("by_agent_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("read_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("ix_notifications_booking_id", "notifications", ["booking_id"], unique=False)
    op.create_index("ix_notifications_by_agent_id", "notifications", ["by_agent_id"], unique=False)
    op.create_index("ix_notifications_note_id", "notifications", ["note_id"], unique=False)
    op.create_index("ix_notifications_task_id", "notifications", ["task_id"], unique=False)
    op.create_index(
        "ix_notifications_user_read_created",
        "notifications",
        ["user_id", "read_at", "created_at"],
        unique=False,
    )
    op.create_table(
        "stations",
        sa.Column(
            "code", mysql.VARCHAR(charset="ascii", collation="ascii_bin", length=4), nullable=False
        ),
        sa.Column("name", mysql.VARCHAR(length=100), nullable=True),
        sa.Column("is_active", sa.BOOLEAN(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_stations")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "statuses",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "code", mysql.VARCHAR(charset="ascii", collation="ascii_bin", length=40), nullable=False
        ),
        sa.Column("label", mysql.VARCHAR(length=100), nullable=False),
        sa.Column("position_label", mysql.VARCHAR(length=60), nullable=False),
        sa.Column("note_required", sa.BOOLEAN(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_done", sa.BOOLEAN(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "sort_order", mysql.INTEGER(unsigned=True), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("is_active", sa.BOOLEAN(), server_default=sa.text("1"), nullable=False),
        sa.Column("stale_after_hours", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("suggest_task", sa.BOOLEAN(), server_default=sa.text("0"), nullable=False),
        sa.Column("default_task_days", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("invoice_required", sa.BOOLEAN(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statuses")),
        sa.UniqueConstraint("code", name="code"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "users",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("username", mysql.VARCHAR(length=50), nullable=False),
        sa.Column("password_hash", mysql.VARCHAR(length=255), nullable=False),
        sa.Column("full_name", mysql.VARCHAR(length=100), nullable=False),
        sa.Column("role", mysql.ENUM("admin", "qc", "agent"), nullable=False),
        sa.Column("is_active", sa.BOOLEAN(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "current_session_id",
            mysql.CHAR(charset="ascii", collation="ascii_bin", length=36),
            nullable=True,
        ),
        sa.Column("settings", mysql.JSON(none_as_null=True), nullable=True),
        sa.Column("last_login_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name="username"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    # Dropping each table also removes all of its indexes; no FK dependencies exist.
    for table_name in (
        "users",
        "statuses",
        "stations",
        "notifications",
        "bookings",
        "booking_tasks",
        "booking_notes",
        "booking_invoices",
        "booking_groups",
        "audit_logs",
        "attachments",
    ):
        op.drop_table(table_name)

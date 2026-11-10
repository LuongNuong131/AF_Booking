"""Per-booking classification and recoverable administration deletions."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("users", "statuses", "stations", "booking_groups", "bookings"):
        op.add_column(table, sa.Column("deleted_at", mysql.DATETIME(fsp=3), nullable=True))
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"])
    op.add_column(
        "bookings",
        sa.Column(
            "classification", mysql.ENUM("hotel", "transportation", "unclassified"), nullable=True
        ),
    )
    op.create_table(
        "recycle_entries",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("resource", mysql.VARCHAR(30), nullable=False),
        sa.Column("record_id", mysql.VARCHAR(40), nullable=False),
        sa.Column("label", mysql.VARCHAR(255), nullable=False),
        sa.Column("deleted_by", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("reason", mysql.VARCHAR(255), nullable=False),
        sa.Column("payload", mysql.JSON(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_table(
        "storage_garbage",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("storage_key", mysql.VARCHAR(512), nullable=False),
        sa.Column("attempts", mysql.INTEGER(unsigned=True), nullable=False, server_default="0"),
        sa.Column("last_error", mysql.VARCHAR(100)),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.UniqueConstraint("storage_key", name="uq_storage_garbage_key"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_recycle_resource_created", "recycle_entries", ["resource", "created_at", "id"]
    )

    op.execute(
        sa.text("""
        INSERT INTO recycle_entries
            (resource, record_id, label, deleted_by, reason, payload, created_at)
        SELECT 'notes', CAST(id AS CHAR), LEFT(COALESCE(note, 'Deleted note'), 255),
            COALESCE(deleted_by, agent_id), COALESCE(delete_reason, 'Legacy note deletion'),
            JSON_OBJECT(), deleted_at
        FROM booking_notes WHERE deleted_at IS NOT NULL
    """)
    )


def downgrade():
    op.drop_table("storage_garbage")
    op.drop_table("recycle_entries")
    op.drop_column("bookings", "classification")
    for table in ("bookings", "booking_groups", "stations", "statuses", "users"):
        op.drop_index(f"ix_{table}_deleted_at", table_name=table)
        op.drop_column(table, "deleted_at")

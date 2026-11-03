"""Add durable integrity run history and refine the pre-existing task-day column."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    invalid = connection.scalar(
        sa.text("SELECT COUNT(*) FROM statuses WHERE default_task_days > 65535")
    )
    if invalid:
        raise RuntimeError("Correct out-of-range status task days before upgrading.")
    op.alter_column(
        "statuses",
        "default_task_days",
        existing_type=mysql.INTEGER(unsigned=True),
        type_=mysql.SMALLINT(unsigned=True),
        existing_nullable=True,
    )
    # The field was provisioned early in 0001. Preserve custom non-null values;
    # give the two initial statuses the requested assumed defaults on first upgrade.
    connection.execute(
        sa.text(
            "UPDATE statuses SET default_task_days = CASE code "
            "WHEN 'REJECTION' THEN 3 WHEN 'PARKING' THEN 2 END "
            "WHERE code IN ('REJECTION','PARKING') AND default_task_days IS NULL"
        )
    )
    op.create_table(
        "integrity_runs",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True),
        sa.Column(
            "started_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column("finished_at", mysql.DATETIME(fsp=3), nullable=True),
        *[
            sa.Column(name, mysql.INTEGER(unsigned=True), nullable=False, server_default="0")
            for name in ("checked", "mismatched", "fixed")
        ],
        sa.Column("status", mysql.VARCHAR(16), nullable=False),
        sa.Column("details", mysql.JSON(none_as_null=True), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_integrity_runs_started_at", "integrity_runs", ["started_at", "id"])


def downgrade():
    op.drop_table("integrity_runs")
    op.alter_column(
        "statuses",
        "default_task_days",
        existing_type=mysql.SMALLINT(unsigned=True),
        type_=mysql.INTEGER(unsigned=True),
        existing_nullable=True,
    )

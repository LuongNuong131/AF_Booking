"""Durable daily reports and session-owned Web Push subscriptions."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None
OPTIONS = dict(mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci")


def upgrade():
    op.create_table(
        "daily_reports",
        sa.Column("report_date", sa.Date(), primary_key=True),
        sa.Column("payload", mysql.JSON(none_as_null=True), nullable=False),
        sa.Column("generated_at", mysql.DATETIME(fsp=3), nullable=False),
        **OPTIONS,
    )
    op.create_table(
        "push_subscriptions",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "session_id", mysql.CHAR(36, charset="ascii", collation="ascii_bin"), nullable=False
        ),
        sa.Column(
            "endpoint", mysql.VARCHAR(2048, charset="ascii", collation="ascii_bin"), nullable=False
        ),
        sa.Column(
            "p256dh", mysql.VARCHAR(100, charset="ascii", collation="ascii_bin"), nullable=False
        ),
        sa.Column(
            "auth", mysql.VARCHAR(40, charset="ascii", collation="ascii_bin"), nullable=False
        ),
        sa.Column("user_agent", mysql.VARCHAR(255), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
        ),
        sa.Column("last_success_at", mysql.DATETIME(fsp=3), nullable=True),
        sa.UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
        **OPTIONS,
    )
    op.create_index("ix_push_subscriptions_user", "push_subscriptions", ["user_id"])


def downgrade():
    op.drop_table("push_subscriptions")
    op.drop_table("daily_reports")

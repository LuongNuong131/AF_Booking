"""Add user-private note snippets for fast note entry."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "note_snippets",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("title", mysql.VARCHAR(80), nullable=False),
        sa.Column("text", mysql.VARCHAR(1000), nullable=False),
        sa.Column(
            "use_count",
            mysql.INTEGER(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_note_snippets"),
        sa.UniqueConstraint("user_id", "title", name="uq_note_snippets_user_title"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_note_snippets_user_usage",
        "note_snippets",
        ["user_id", "use_count", "updated_at"],
    )


def downgrade():
    op.drop_index("ix_note_snippets_user_usage", table_name="note_snippets")
    op.drop_table("note_snippets")

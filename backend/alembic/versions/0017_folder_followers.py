"""Follow an entire supplier/station folder, including future monthly bookings."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "folder_followers",
        sa.Column("group_id", mysql.BIGINT(unsigned=True), primary_key=True),
        sa.Column("user_id", mysql.BIGINT(unsigned=True), primary_key=True),
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
    op.create_index(
        "ix_folder_followers_user_created",
        "folder_followers",
        ["user_id", "created_at", "group_id"],
    )


def downgrade():
    op.drop_table("folder_followers")

"""Require rotation for temporary/new account passwords without resetting existing users."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "must_change_password", mysql.BOOLEAN, nullable=False, server_default=sa.text("0")
        ),
    )
    # Accounts which have never signed in still hold their initial password.
    op.execute("UPDATE users SET must_change_password = 1 WHERE last_login_at IS NULL")


def downgrade():
    op.drop_column("users", "must_change_password")

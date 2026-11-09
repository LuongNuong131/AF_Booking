"""Allow unclassified suppliers and independent folders at multiple stations."""

from sqlalchemy.dialects import mysql

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "booking_groups",
        "supplier_type",
        existing_type=mysql.ENUM("hotel", "transportation"),
        type_=mysql.ENUM("hotel", "transportation", "unclassified"),
        existing_nullable=False,
        server_default="unclassified",
    )
    op.create_unique_constraint(
        "uq_booking_groups_cw_station", "booking_groups", ["cw_number", "station_code"]
    )
    op.drop_index("cw_number", table_name="booking_groups")


def downgrade():
    # These checks fail without changing data if the old schema cannot represent it.
    from sqlalchemy import text

    connection = op.get_bind()
    if connection.scalar(
        text("SELECT COUNT(*) FROM booking_groups WHERE supplier_type = 'unclassified'")
    ):
        raise RuntimeError("Classify suppliers before downgrading; no data was removed.")
    if connection.execute(
        text("SELECT cw_number FROM booking_groups GROUP BY cw_number HAVING COUNT(*) > 1 LIMIT 1")
    ).first():
        raise RuntimeError("Multiple station folders exist; downgrade cannot preserve them.")
    op.create_unique_constraint("cw_number", "booking_groups", ["cw_number"])
    op.drop_constraint("uq_booking_groups_cw_station", "booking_groups", type_="unique")
    op.alter_column(
        "booking_groups",
        "supplier_type",
        existing_type=mysql.ENUM("hotel", "transportation", "unclassified"),
        type_=mysql.ENUM("hotel", "transportation"),
        existing_nullable=False,
        server_default=None,
    )

"""Complete normalized invoice lookup and reconciliation indexes, preserving declarations."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    # State/count, invoice_required and note.invoice_change were provisioned in
    # 0001 and are already in active use. Never reset explicit declarations.
    op.add_column(
        "booking_invoices",
        sa.Column(
            "invoice_number_normalized",
            mysql.VARCHAR(40, charset="ascii", collation="ascii_bin"),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE booking_invoices SET invoice_number_normalized = UPPER(TRIM(invoice_number))"
    )
    op.alter_column(
        "booking_invoices",
        "invoice_number_normalized",
        existing_type=mysql.VARCHAR(40, charset="ascii", collation="ascii_bin"),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_booking_invoices_normalized",
        "booking_invoices",
        ["booking_id", "invoice_number_normalized"],
    )
    op.drop_index("uq_booking_invoices_number", table_name="booking_invoices")
    op.drop_index("ix_booking_invoices_invoice_number", table_name="booking_invoices")
    op.create_index(
        "ix_booking_invoices_normalized", "booking_invoices", ["invoice_number_normalized"]
    )
    op.create_index("ix_booking_invoices_created_at", "booking_invoices", ["created_at"])
    op.alter_column(
        "bookings",
        "invoice_count",
        existing_type=mysql.INTEGER(unsigned=True),
        type_=mysql.SMALLINT(unsigned=True),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
    )
    op.create_index("ix_bookings_period_invoice_state", "bookings", ["period", "invoice_state"])
    op.create_index(
        "ix_bookings_invoice_done_updated", "bookings", ["invoice_state", "is_done", "updated_at"]
    )


def downgrade():
    op.drop_index("ix_bookings_invoice_done_updated", table_name="bookings")
    op.drop_index("ix_bookings_period_invoice_state", table_name="bookings")
    op.alter_column(
        "bookings",
        "invoice_count",
        existing_type=mysql.SMALLINT(unsigned=True),
        type_=mysql.INTEGER(unsigned=True),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
    )
    op.drop_index("ix_booking_invoices_created_at", table_name="booking_invoices")
    op.drop_index("ix_booking_invoices_normalized", table_name="booking_invoices")
    op.create_index("ix_booking_invoices_invoice_number", "booking_invoices", ["invoice_number"])
    op.create_unique_constraint(
        "uq_booking_invoices_number", "booking_invoices", ["booking_id", "invoice_number"]
    )
    op.drop_index("uq_booking_invoices_normalized", table_name="booking_invoices")
    op.drop_column("booking_invoices", "invoice_number_normalized")

from datetime import datetime
from typing import Literal

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.models.base import TABLE_OPTIONS, Base, CreatedAt, Timestamps, UTCDateTime
from app.utils.booking_key import require_canonical_storage_key
from app.utils.supplier import normalize_supplier_name


def ascii_varchar(length: int) -> mysql.VARCHAR:
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def ascii_char(length: int) -> mysql.CHAR:
    return mysql.CHAR(length, charset="ascii", collation="ascii_bin")


class User(Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="username"), TABLE_OPTIONS)

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    username: Mapped[str] = mapped_column(mysql.VARCHAR(50), nullable=False)
    password_hash: Mapped[str] = mapped_column(mysql.VARCHAR(255), nullable=False)
    full_name: Mapped[str] = mapped_column(mysql.VARCHAR(100), nullable=False)
    role: Mapped[Literal["admin", "qc", "agent"]] = mapped_column(
        mysql.ENUM("admin", "qc", "agent"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(mysql.BOOLEAN, server_default=text("1"))
    current_session_id: Mapped[str | None] = mapped_column(ascii_char(36))
    settings: Mapped[dict[str, JsonValue] | None] = mapped_column(mysql.JSON(none_as_null=True))
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Status(Base):
    __tablename__ = "statuses"
    __table_args__ = (UniqueConstraint("code", name="code"), TABLE_OPTIONS)

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    code: Mapped[str] = mapped_column(ascii_varchar(40), nullable=False)
    label: Mapped[str] = mapped_column(mysql.VARCHAR(100), nullable=False)
    position_label: Mapped[str] = mapped_column(mysql.VARCHAR(60), nullable=False)
    note_required: Mapped[bool] = mapped_column(mysql.BOOLEAN, server_default=text("0"))
    is_done: Mapped[bool] = mapped_column(mysql.BOOLEAN, server_default=text("0"))
    sort_order: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(mysql.BOOLEAN, server_default=text("1"))
    stale_after_hours: Mapped[int | None] = mapped_column(mysql.INTEGER(unsigned=True))
    suggest_task: Mapped[bool] = mapped_column(mysql.BOOLEAN, server_default=text("0"))
    default_task_days: Mapped[int | None] = mapped_column(mysql.INTEGER(unsigned=True))
    invoice_required: Mapped[bool] = mapped_column(mysql.BOOLEAN, server_default=text("0"))


class Station(CreatedAt, Base):
    __tablename__ = "stations"
    __table_args__ = TABLE_OPTIONS

    code: Mapped[str] = mapped_column(ascii_varchar(4), primary_key=True)
    name: Mapped[str | None] = mapped_column(mysql.VARCHAR(100))
    is_active: Mapped[bool] = mapped_column(mysql.BOOLEAN, server_default=text("1"))


class BookingGroup(Timestamps, Base):
    __tablename__ = "booking_groups"
    __table_args__ = (
        UniqueConstraint("cw_number", name="cw_number"),
        Index(
            "ix_booking_groups_station_type_activity",
            "station_code",
            "supplier_type",
            "last_activity_at",
            "id",
        ),
        Index("ix_booking_groups_supplier_name_normalized", "supplier_name_normalized"),
        Index("ix_booking_groups_last_activity_at", "last_activity_at"),
        Index("ix_booking_groups_created_by", "created_by"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    cw_number: Mapped[str] = mapped_column(ascii_varchar(12), nullable=False)
    station_code: Mapped[str] = mapped_column(ascii_varchar(4), nullable=False)
    supplier_name: Mapped[str] = mapped_column(mysql.VARCHAR(255), nullable=False)
    supplier_name_normalized: Mapped[str] = mapped_column(mysql.VARCHAR(255), nullable=False)
    supplier_type: Mapped[Literal["hotel", "transportation"]] = mapped_column(
        mysql.ENUM("hotel", "transportation"), nullable=False
    )
    booking_count: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), server_default=text("0")
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=text("CURRENT_TIMESTAMP(3)")
    )
    created_by: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)

    @validates("supplier_name")
    def update_normalized_name(self, attribute: str, value: str) -> str:
        self.supplier_name_normalized = normalize_supplier_name(value)
        return value


class Booking(Timestamps, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("booking_key", name="booking_key"),
        CheckConstraint(
            "booking_key = UPPER(booking_key) AND booking_key NOT LIKE '% %'", name="canonical_key"
        ),
        Index("ix_bookings_agent_updated", "last_agent_id", "updated_at", "id"),
        Index("ix_bookings_updated_at", "updated_at", "id"),
        Index("ix_bookings_status_updated", "last_status_id", "updated_at", "id"),
        Index("ix_bookings_done_updated", "is_done", "updated_at", "id"),
        Index("ix_bookings_group_period", "group_id", "period", "id"),
        Index("ix_bookings_station_period", "station_code", "period", "id"),
        Index("ix_bookings_cw_period", "cw_number", "period"),
        Index("ix_bookings_last_note_id", "last_note_id"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    booking_key: Mapped[str] = mapped_column(ascii_varchar(32), nullable=False)
    group_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    cw_number: Mapped[str] = mapped_column(ascii_varchar(12), nullable=False)
    station_code: Mapped[str] = mapped_column(ascii_varchar(4), nullable=False)
    period: Mapped[str] = mapped_column(ascii_char(4), nullable=False)
    last_note_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    last_agent_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    last_status_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    last_position: Mapped[str | None] = mapped_column(mysql.VARCHAR(60))
    last_note_preview: Mapped[str | None] = mapped_column(mysql.VARCHAR(255))
    is_done: Mapped[bool] = mapped_column(mysql.BOOLEAN, server_default=text("0"))
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    stale_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    version: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), server_default=text("1"))
    invoice_state: Mapped[Literal["unknown", "has_invoice", "no_invoice"]] = mapped_column(
        mysql.ENUM("unknown", "has_invoice", "no_invoice"), server_default="unknown"
    )
    invoice_count: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True), server_default=text("0")
    )

    @validates("booking_key")
    def validate_storage_key(self, attribute: str, value: str) -> str:
        return require_canonical_storage_key(value)


class BookingNote(CreatedAt, Base):
    __tablename__ = "booking_notes"
    __table_args__ = (
        UniqueConstraint("client_request_id", name="client_request_id"),
        Index("ix_booking_notes_booking_created", "booking_id", "created_at", "id"),
        Index("ix_booking_notes_created_at", "created_at"),
        Index("ix_booking_notes_agent_created", "agent_id", "created_at"),
        Index("ix_booking_notes_deleted_at", "deleted_at"),
        Index("ix_booking_notes_status_id", "status_id"),
        Index("ix_booking_notes_deleted_by", "deleted_by"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    booking_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    agent_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    status_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    position_label: Mapped[str] = mapped_column(mysql.VARCHAR(60), nullable=False)
    note: Mapped[str | None] = mapped_column(mysql.TEXT)
    client_request_id: Mapped[str | None] = mapped_column(ascii_char(36))
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deleted_by: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    delete_reason: Mapped[str | None] = mapped_column(mysql.VARCHAR(255))
    invoice_change: Mapped[dict[str, JsonValue] | None] = mapped_column(
        mysql.JSON(none_as_null=True)
    )


class Attachment(CreatedAt, Base):
    __tablename__ = "attachments"
    __table_args__ = (Index("ix_attachments_note_id", "note_id"), TABLE_OPTIONS)

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    note_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    file_name: Mapped[str] = mapped_column(mysql.VARCHAR(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(mysql.VARCHAR(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    storage_key: Mapped[str] = mapped_column(mysql.VARCHAR(512), nullable=False)


class Notification(CreatedAt, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),
        Index("ix_notifications_booking_id", "booking_id"),
        Index("ix_notifications_task_id", "task_id"),
        Index("ix_notifications_note_id", "note_id"),
        Index("ix_notifications_by_agent_id", "by_agent_id"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    booking_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    type: Mapped[str] = mapped_column(
        mysql.ENUM(
            "taken_over", "stale", "task_due", "watch_update", "assigned", "assignment_done"
        ),
        server_default="taken_over",
    )
    task_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    note_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    by_agent_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AuditLog(CreatedAt, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    action: Mapped[str] = mapped_column(mysql.VARCHAR(60), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(mysql.VARCHAR(40))
    entity_id: Mapped[str | None] = mapped_column(mysql.VARCHAR(60))
    meta: Mapped[dict[str, JsonValue] | None] = mapped_column(mysql.JSON(none_as_null=True))
    ip: Mapped[str | None] = mapped_column(mysql.VARCHAR(45))


class BookingTask(Timestamps, Base):
    __tablename__ = "booking_tasks"
    __table_args__ = (
        UniqueConstraint("client_request_id", name="client_request_id"),
        Index("ix_booking_tasks_user_status_remind", "user_id", "status", "remind_at"),
        Index("ix_booking_tasks_status_notified_remind", "status", "notified_at", "remind_at"),
        Index("ix_booking_tasks_booking_user_status", "booking_id", "user_id", "status"),
        Index("ix_booking_tasks_note_id", "note_id"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    booking_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    user_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    note_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True))
    message: Mapped[str] = mapped_column(mysql.VARCHAR(255), nullable=False)
    remind_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[Literal["pending", "done", "cancelled"]] = mapped_column(
        mysql.ENUM("pending", "done", "cancelled"), server_default="pending"
    )
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    snooze_count: Mapped[int] = mapped_column(
        mysql.SMALLINT(unsigned=True), server_default=text("0")
    )
    client_request_id: Mapped[str | None] = mapped_column(ascii_char(36))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class BookingInvoice(CreatedAt, Base):
    __tablename__ = "booking_invoices"
    __table_args__ = (
        UniqueConstraint("booking_id", "invoice_number", name="uq_booking_invoices_number"),
        Index("ix_booking_invoices_invoice_number", "invoice_number"),
        Index("ix_booking_invoices_added_by", "added_by"),
        TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    booking_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    invoice_number: Mapped[str] = mapped_column(ascii_varchar(40), nullable=False)
    added_by: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)

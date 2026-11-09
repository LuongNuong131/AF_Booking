"""Prompt 1B wire models. Business routes are implemented in later prompts."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
)


def serialize_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcTimestamp = Annotated[
    AwareDatetime,
    AfterValidator(lambda value: value.astimezone(UTC)),
    PlainSerializer(
        serialize_timestamp,
        return_type=str,
        when_used="json",
    ),
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, str_max_length=5000)


class ErrorCode(StrEnum):
    PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNAUTHORIZED = "UNAUTHORIZED"
    SESSION_REPLACED = "SESSION_REPLACED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOTE_REQUIRED = "NOTE_REQUIRED"
    STATUS_INACTIVE = "STATUS_INACTIVE"
    TASK_LIMIT_REACHED = "TASK_LIMIT_REACHED"
    NEW_BOOKING_NEEDS_CONFIRM = "NEW_BOOKING_NEEDS_CONFIRM"
    DUPLICATE_RECENT_NOTE = "DUPLICATE_RECENT_NOTE"
    WATCH_LIMIT_REACHED = "WATCH_LIMIT_REACHED"
    ASSIGNMENT_INVALID = "ASSIGNMENT_INVALID"
    INVALID_BOOKING_KEY = "INVALID_BOOKING_KEY"
    STATION_REQUIRED = "STATION_REQUIRED"
    STATION_MISMATCH = "STATION_MISMATCH"
    SUPPLIER_REQUIRED = "SUPPLIER_REQUIRED"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    INVOICE_REQUIRED = "INVOICE_REQUIRED"
    INVOICE_INVALID = "INVOICE_INVALID"
    INVOICE_STATE_CONFLICT = "INVOICE_STATE_CONFLICT"
    INVOICE_LIMIT_REACHED = "INVOICE_LIMIT_REACHED"
    RATE_LIMITED = "RATE_LIMITED"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    SERVICE_BUSY = "SERVICE_BUSY"
    INTERNAL = "INTERNAL"


class ApiError(ContractModel):
    code: ErrorCode
    message: str
    details: JsonValue = None


class SupplierType(StrEnum):
    HOTEL = "hotel"
    TRANSPORTATION = "transportation"
    UNCLASSIFIED = "unclassified"


class InvoiceState(StrEnum):
    UNKNOWN = "unknown"
    HAS_INVOICE = "has_invoice"
    NO_INVOICE = "no_invoice"


class TaskStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    CANCELLED = "cancelled"


class NotificationType(StrEnum):
    TAKEN_OVER = "taken_over"
    STALE = "stale"
    TASK_DUE = "task_due"
    WATCH_UPDATE = "watch_update"
    ASSIGNED = "assigned"
    ASSIGNMENT_DONE = "assignment_done"


class SearchKind(StrEnum):
    BOOKING = "booking"
    PARTIAL_KEY = "partial_key"
    FOLDER = "folder"
    FOLDERS = "folders"
    STATION = "station"
    STATION_PERIOD = "station_period"
    INVOICE = "invoice"
    NONE = "none"


class ServerEventName(StrEnum):
    BOOKING_UPDATED = "booking.updated"
    LOCK_ACQUIRED = "lock.acquired"
    LOCK_RELEASED = "lock.released"
    LOCK_SNAPSHOT = "lock.snapshot"
    LOCK_DENIED = "lock.denied"
    NOTIFICATION_NEW = "notification.new"
    TASK_DUE = "task.due"
    SESSION_FORCE_LOGOUT = "session.force_logout"


class ClientEventName(StrEnum):
    LOCK_ACQUIRE = "lock.acquire"
    LOCK_HEARTBEAT = "lock.heartbeat"
    LOCK_RELEASE = "lock.release"


class AgentSummary(ContractModel):
    id: int
    full_name: str


class StatusSummary(ContractModel):
    code: str
    label: str


class SupplierSummary(ContractModel):
    name: str
    type: SupplierType


class BookingIdentity(ContractModel):
    booking_key: str
    display_key: str


class BookingSnapshot(BookingIdentity):
    cw_number: str
    station_code: str
    period: str
    period_label: str
    supplier: SupplierSummary
    version: int
    last_status: StatusSummary | None
    last_position: str | None
    last_agent: AgentSummary | None
    last_note_preview: str | None
    is_done: bool
    done_at: UtcTimestamp | None
    updated_at: UtcTimestamp
    is_stale: bool
    invoice_state: InvoiceState
    invoice_count: int
    invoices_preview: list[str] = Field(max_length=3)


class Invoice(ContractModel):
    id: int
    invoice_number: str
    added_by: AgentSummary
    created_at: UtcTimestamp


class InvoiceChange(ContractModel):
    add: list[str] = Field(default_factory=list, max_length=50)
    remove_ids: list[int] = Field(default_factory=list, max_length=50)
    no_invoice: bool = False


class Attachment(ContractModel):
    id: int
    file_name: str
    mime_type: str
    size_bytes: int


class NoteInvoiceChange(ContractModel):
    added: list[str]
    removed: list[str]
    no_invoice: bool | None


class Note(ContractModel):
    id: int
    agent: AgentSummary
    status: StatusSummary
    position: str
    note: str | None
    created_at: UtcTimestamp
    attachments: list[Attachment]
    invoice_change: NoteInvoiceChange | None


class Status(ContractModel):
    id: int
    code: str
    label: str
    position_label: str
    note_required: bool
    is_done: bool
    sort_order: int
    suggest_task: bool
    default_task_days: int | None
    invoice_required: bool


class TaskBookingSummary(ContractModel):
    last_status: StatusSummary | None
    last_agent: AgentSummary | None
    is_done: bool
    updated_at: UtcTimestamp


class Task(BookingIdentity):
    id: int
    message: str
    remind_at: UtcTimestamp
    status: TaskStatus
    is_due: bool
    is_overdue: bool
    snooze_count: int
    created_at: UtcTimestamp
    completed_at: UtcTimestamp | None
    booking_changed_since: bool
    booking: TaskBookingSummary


class Suggestion(BookingIdentity):
    last_status: StatusSummary | None
    last_agent: AgentSummary | None
    updated_at: UtcTimestamp
    distance: int


class FolderLatest(BookingIdentity):
    period_label: str
    status: StatusSummary | None
    agent: AgentSummary | None


class FolderCard(ContractModel):
    cw_number: str
    supplier_name: str
    supplier_type: SupplierType
    station_code: str
    booking_count: int
    open_count: int
    stale_count: int = 0
    last_activity_at: UtcTimestamp
    latest: FolderLatest | None


class MonthRow(BookingIdentity):
    period: str
    period_label: str
    last_status: StatusSummary | None
    last_position: str | None
    last_agent: AgentSummary | None
    is_done: bool
    is_stale: bool
    updated_at: UtcTimestamp
    invoice_state: InvoiceState
    invoice_count: int


class ResolutionStatus(StrEnum):
    EXACT = "exact"
    RESOLVED_FROM_PARTIAL = "resolved_from_partial"
    NEEDS_STATION = "needs_station"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"


class InputKind(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    INVALID = "invalid"


class KeyCandidate(ContractModel):
    key: str
    display_key: str
    station_code: str
    supplier_name: str


class KeyResolution(ContractModel):
    status: ResolutionStatus
    input_kind: InputKind
    key: str | None
    display_key: str | None
    candidates: list[KeyCandidate] = Field(default_factory=list)


class NoteSaveRequest(ContractModel):
    status_code: str
    note: str | None
    expected_version: int
    client_request_id: UUID
    confirm_new: bool = False
    allow_duplicate: bool = False
    assign_to: int | None = Field(default=None, gt=0)
    assign_message: str | None = Field(default=None, max_length=255)
    invoices: InvoiceChange | None = None
    supplier_name: str | None = None
    supplier_type: SupplierType | None = None


class Page[T](ContractModel):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    size: int = Field(ge=1)


class CursorPage[T](ContractModel):
    items: list[T]
    next_cursor: str | None


# Explicit roots make type generation deterministic without importing business routers.
CONTRACT_MODELS = (
    ApiError,
    BookingSnapshot,
    Invoice,
    InvoiceChange,
    Note,
    Status,
    Task,
    Suggestion,
    FolderCard,
    MonthRow,
    KeyResolution,
    NoteSaveRequest,
    Page,
    CursorPage,
)
CONTRACT_ENUMS = (NotificationType, SearchKind, ServerEventName, ClientEventName)

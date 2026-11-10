from datetime import date
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator

from app.schemas.auth import UserRole
from app.schemas.contracts import (
    AgentSummary,
    BookingIdentity,
    ContractModel,
    JsonValue,
    StatusSummary,
    UtcTimestamp,
)
from app.utils.text import clean_note


def display_name(value):
    value = clean_note(value)
    if not value or not 2 <= len(value) <= 100:
        raise ValueError("Use 2–100 characters for the display name.")
    return value


class AdminUser(ContractModel):
    id: int
    username: str
    full_name: str
    role: UserRole
    is_active: bool
    must_change_password: bool
    created_at: UtcTimestamp
    last_login_at: UtcTimestamp | None
    has_session: bool


class UserCreate(ContractModel):
    is_active: bool = True
    username: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,49}$")
    full_name: str
    role: UserRole = "agent"
    temporary_password: SecretStr = Field(min_length=10, max_length=128)
    _name = field_validator("full_name")(display_name)


class UserUpdate(ContractModel):
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None

    @field_validator("full_name", "role", "is_active")
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged fields instead of null.")
        return value

    _name = field_validator("full_name")(display_name)


class ResetPassword(ContractModel):
    temporary_password: SecretStr = Field(min_length=10, max_length=128)


class DeleteNote(ContractModel):
    reason: str = Field(min_length=3, max_length=255)

    @field_validator("reason")
    @classmethod
    def reason_text(cls, value):
        value = clean_note(value)
        if not value or len(value) < 3:
            raise ValueError("Enter a reason of at least 3 characters.")
        return value


class AdminNote(BookingIdentity):
    id: int
    agent: AgentSummary
    status: StatusSummary
    position: str
    note: str | None
    created_at: UtcTimestamp
    deleted_at: UtcTimestamp | None
    deleted_by: AgentSummary | None
    delete_reason: str | None


class AuditEntry(ContractModel):
    id: int
    user: AgentSummary | None
    action: str
    entity_type: str | None
    entity_id: str | None
    meta: dict[str, JsonValue] | None
    ip: str | None
    created_at: UtcTimestamp


class AdminStatus(ContractModel):
    id: int
    code: str
    label: str
    position_label: str
    note_required: bool
    is_done: bool
    sort_order: int
    is_active: bool
    stale_after_hours: int | None
    suggest_task: bool
    default_task_days: int | None
    invoice_required: bool


class StatusCreate(ContractModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=100)
    position_label: str = Field(min_length=1, max_length=60)
    note_required: bool = False
    is_done: bool = False
    sort_order: int = Field(default=0, ge=0, le=100000)
    is_active: bool = True
    stale_after_hours: int | None = Field(default=None, ge=1, le=87600)
    suggest_task: bool = False
    default_task_days: int | None = Field(default=None, ge=1, le=90)
    invoice_required: bool = False

    @field_validator("label", "position_label")
    @classmethod
    def label_text(cls, value):
        value = clean_note(value)
        if not value:
            raise ValueError("This label is required.")
        return value


class StatusUpdate(ContractModel):
    id: int = Field(gt=0)
    code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,39}$")
    label: str | None = Field(default=None, min_length=1, max_length=100)
    position_label: str | None = Field(default=None, min_length=1, max_length=60)
    note_required: bool | None = None
    is_done: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None
    stale_after_hours: int | None = Field(default=None, ge=1, le=87600)
    suggest_task: bool | None = None
    default_task_days: int | None = Field(default=None, ge=1, le=90)
    invoice_required: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self):
        for name in self.model_fields_set - {"stale_after_hours", "default_task_days"}:
            if getattr(self, name) is None:
                raise ValueError("Omit unchanged fields instead of null.")
        for name in {"label", "position_label"} & self.model_fields_set:
            value = clean_note(getattr(self, name))
            if not value:
                raise ValueError("This label is required.")
            setattr(self, name, value)
        return self


class LoginActivity(ContractModel):
    action: str
    created_at: UtcTimestamp
    ip: str | None


class ProfileStats(ContractModel):
    notes_today: int
    notes_week: int
    timezone: str
    login_history: list[LoginActivity]


class PerformanceUser(ContractModel):
    agent: AgentSummary | None
    note_count: int = 0
    done_count: int = 0


class StatusCount(ContractModel):
    status: StatusSummary | None
    count: int


class AgentCount(ContractModel):
    agent: AgentSummary | None
    count: int


class TrendPoint(ContractModel):
    date: date
    count: int


class PerformanceReport(ContractModel):
    date_from: date
    date_to: date
    timezone: str
    generated_at: UtcTimestamp
    note_count: int
    done_count: int
    users: list[PerformanceUser]
    statuses: list[StatusCount]
    trend: list[TrendPoint]
    stale_by_user: list[AgentCount]
    stale_by_status: list[StatusCount]
    overdue_tasks_by_user: list[AgentCount]


class BookingImportRequest(ContractModel):
    data: str = Field(min_length=1, max_length=500000)
    apply: bool = False
    station_source: Literal["strict", "station_code", "booking_number"] = "strict"
    fill_missing_supplier: bool = False


class ImportAdjustment(ContractModel):
    row: int
    field: str
    before: str
    after: str


class BookingImportResult(ContractModel):
    source_rows: int
    unique_bookings: int
    duplicate_rows: int
    new_bookings: int
    existing_bookings: int
    new_folders: int
    applied: bool
    sample_keys: list[str]
    adjustments: list[ImportAdjustment] = []


class MonthlyBookingResult(ContractModel):
    period: str
    created: int
    processed_folders: int
    enabled: bool


class MonthlyBookingStatus(ContractModel):
    enabled: bool
    day: int
    timezone: str
    due_period: str
    next_run_at: UtcTimestamp
    active_folders: int
    pending_folders: int
    external_trigger_configured: bool


ADMIN_MODELS = (
    ImportAdjustment,
    MonthlyBookingResult,
    MonthlyBookingStatus,
    BookingImportRequest,
    BookingImportResult,
    AdminUser,
    UserCreate,
    UserUpdate,
    ResetPassword,
    DeleteNote,
    AdminNote,
    AuditEntry,
    AdminStatus,
    StatusCreate,
    StatusUpdate,
    ProfileStats,
    PerformanceReport,
)

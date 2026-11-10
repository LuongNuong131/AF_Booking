from datetime import date
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.contracts import (
    AgentSummary,
    BookingIdentity,
    ContractModel,
    StatusSummary,
    UtcTimestamp,
)
from app.utils.text import clean_note


class PersonalBookingRow(BookingIdentity):
    supplier_name: str
    station_code: str
    note_count: int
    last_status: StatusSummary
    last_note: str | None
    updated_at: UtcTimestamp
    is_done: bool


class PersonalDailyReport(ContractModel):
    report_date: date
    timezone: str
    agent: AgentSummary
    booking_count: int
    note_count: int
    done_count: int
    items: list[PersonalBookingRow]
    total: int
    page: int
    size: int


class WorkTaskCreate(ContractModel):
    message: str = Field(min_length=1, max_length=2000)
    client_request_id: UUID

    @field_validator("message")
    @classmethod
    def clean(cls, value):
        value = (clean_note(value) or "").strip()
        if not value:
            raise ValueError("Describe the work required.")
        return value


class WorkTaskHandle(ContractModel):
    handling_note: str | None = Field(default=None, max_length=2000)


class WorkTaskItem(BookingIdentity):
    id: int
    supplier_name: str
    creator: AgentSummary
    message: str
    status: str
    created_at: UtcTimestamp
    handled_by: AgentSummary | None
    handled_at: UtcTimestamp | None
    handling_note: str | None


class AttachmentStorageInfo(ContractModel):
    enabled: bool
    max_file_bytes: int
    max_files: int
    mime_types: list[str]


WORKFLOW_MODELS = (
    PersonalDailyReport,
    WorkTaskCreate,
    WorkTaskHandle,
    WorkTaskItem,
    AttachmentStorageInfo,
)

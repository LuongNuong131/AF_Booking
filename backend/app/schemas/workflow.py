from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.contracts import (
    AgentSummary,
    Attachment,
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


IssueType = Literal["contract", "cannot_send_rejection_letters"]


class WorkTaskCreate(ContractModel):
    issue_type: IssueType | None = None
    message: str = Field(min_length=1, max_length=2000)
    client_request_id: UUID

    @field_validator("message")
    @classmethod
    def clean(cls, value):
        value = (clean_note(value) or "").strip()
        if not value:
            raise ValueError("Describe the work required.")
        from app.utils.ticket_text import validate_english

        validate_english(value)
        return value


class WorkTaskUpdate(ContractModel):
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=2000)
    issue_type: IssueType | None = None
    status: Literal["pending", "handled"]
    handling_note: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        value = (clean_note(value) or "").strip()
        if not value:
            raise ValueError("Enter a ticket title.")
        return value

    @field_validator("message")
    @classmethod
    def clean_message(cls, value):
        return WorkTaskCreate.clean(value)


class WorkTaskHandle(ContractModel):
    handling_note: str | None = Field(default=None, max_length=2000)


class WorkTaskItem(BookingIdentity):
    issue_type: IssueType | None = None
    title: str
    edit_token: str
    attachments: list[Attachment] = Field(default_factory=list)
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


class WorkTaskMerge(ContractModel):
    ids: list[Annotated[int, Field(gt=0)]] = Field(min_length=2, max_length=100)


class WorkTaskBundle(ContractModel):
    title: str
    message: str
    booking_keys: list[str]
    attachments: list[Attachment]


class TranslationConfig(ContractModel):
    enabled: bool


class TranslationRequest(ContractModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def clean(cls, value):
        value = (clean_note(value) or "").strip()
        if not value:
            raise ValueError("Enter text to translate.")
        return value


class TranslationResult(ContractModel):
    text: str


WORKFLOW_MODELS = (
    WorkTaskMerge,
    WorkTaskBundle,
    TranslationConfig,
    TranslationRequest,
    TranslationResult,
    PersonalDailyReport,
    WorkTaskCreate,
    WorkTaskUpdate,
    WorkTaskHandle,
    WorkTaskItem,
    AttachmentStorageInfo,
)

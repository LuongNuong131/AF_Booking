"""Concrete Prompt 4 response envelopes; shared wire objects remain in contracts."""

from typing import Literal

from pydantic import Field

from app.schemas.contracts import (
    AgentSummary,
    BookingIdentity,
    BookingSnapshot,
    ContractModel,
    CursorPage,
    Invoice,
    KeyResolution,
    Note,
    NotificationType,
    Suggestion,
    SupplierType,
    Task,
    UtcTimestamp,
)


class GroupInfo(ContractModel):
    cw_number: str
    supplier_name: str
    supplier_type: SupplierType
    station_code: str
    recurring_enabled: bool = True


class BookingItem(BookingSnapshot):
    supplier_name: str
    supplier_type: SupplierType
    my_pending_tasks: int = 0
    my_watching: bool = False
    stale_hours: float | None = None


class BookingCreateRequest(ContractModel):
    booking_key: str = Field(min_length=1, max_length=100)
    supplier_name: str | None = Field(default=None, max_length=255)
    supplier_type: Literal["hotel", "transportation"] | None = None
    confirm_new: bool = False


class BookingLookup(ContractModel):
    booking_key: str | None
    display_key: str | None
    exists: bool
    version: int
    resolution: KeyResolution
    format_warning: str | None = None
    done_warning: str | None = None
    snapshot: BookingItem | None = None
    group: GroupInfo | None = None
    group_exists: bool = False
    suggestions: list[Suggestion] = []
    my_tasks: list[Task] = []
    invoices: list[Invoice] = []
    invoice_rules: dict[str, str | int] = {}
    history: CursorPage[Note]


class InvoiceWarning(ContractModel):
    invoice_number: str
    booking_keys: list[str]


class NoteSaveResponse(ContractModel):
    invoices: list[Invoice] | None = None
    skipped_duplicates: list[str] = []
    warnings: list[InvoiceWarning] = []
    my_watching: bool = False
    snapshot: BookingSnapshot
    note: Note


class FolderPatch(ContractModel):
    supplier_name: str | None = None
    supplier_type: SupplierType | None = None
    recurring_enabled: bool | None = None


class NotificationItem(BookingIdentity):
    id: int
    type: NotificationType
    merged_count: int = 1
    by_agent: AgentSummary | None
    note_id: int | None
    task_id: int | None
    created_at: UtcTimestamp
    read_at: UtcTimestamp | None


class NotificationList(ContractModel):
    items: list[NotificationItem]
    unread_count: int


class MutationResult(ContractModel):
    ok: bool = True


BOOKING_MODELS = (
    GroupInfo,
    BookingItem,
    BookingCreateRequest,
    BookingLookup,
    NoteSaveResponse,
    FolderPatch,
    NotificationItem,
    NotificationList,
    MutationResult,
)


class BookingClassification(ContractModel):
    supplier_type: Literal["hotel", "transportation"]
    expected_type: SupplierType | None = None


BOOKING_MODELS += (BookingClassification,)

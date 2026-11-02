"""Concrete Prompt 4 response envelopes; shared wire objects remain in contracts."""

from app.schemas.contracts import (
    AgentSummary,
    BookingIdentity,
    BookingSnapshot,
    ContractModel,
    CursorPage,
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


class BookingItem(BookingSnapshot):
    supplier_name: str
    supplier_type: SupplierType
    my_pending_tasks: int = 0
    stale_hours: float | None = None


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
    history: CursorPage[Note]


class NoteSaveResponse(ContractModel):
    snapshot: BookingSnapshot
    note: Note


class FolderPatch(ContractModel):
    supplier_name: str | None = None
    supplier_type: SupplierType | None = None


class NotificationItem(BookingIdentity):
    id: int
    type: NotificationType
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
    BookingLookup,
    NoteSaveResponse,
    FolderPatch,
    NotificationItem,
    NotificationList,
    MutationResult,
)

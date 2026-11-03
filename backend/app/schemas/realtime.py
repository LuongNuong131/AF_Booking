"""Prompt 5 JSON WebSocket frames. Timestamps share the HTTP UTC serializer."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, TypeAdapter

from app.schemas.contracts import ContractModel, NotificationType, Task, UtcTimestamp


class Frame(ContractModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class BookingUpdatedData(ContractModel):
    booking_key: str
    display_key: str
    cw_number: str
    station_code: str
    version: int
    last_agent_id: int | None
    last_agent_name: str | None
    status_code: str | None
    position: str | None
    snapshot_rebuilt: bool = False
    updated_at: UtcTimestamp
    is_done: bool


class BookingUpdatedFrame(Frame):
    event: Literal["booking.updated"] = "booking.updated"
    data: BookingUpdatedData


class LockHolder(ContractModel):
    booking_key: str
    display_key: str
    user_id: int
    user_name: str


class LockInfo(LockHolder):
    expires_at: UtcTimestamp


class LockChangedFrame(Frame):
    event: Literal["lock.acquired", "lock.released", "lock.denied"]
    data: LockHolder


class LockSnapshotData(ContractModel):
    locks: list[LockInfo]


class LockSnapshotFrame(Frame):
    event: Literal["lock.snapshot"] = "lock.snapshot"
    data: LockSnapshotData


class NotificationNewData(ContractModel):
    id: int
    booking_key: str
    display_key: str
    by_agent_name: str | None
    created_at: UtcTimestamp
    type: NotificationType


class NotificationNewFrame(Frame):
    event: Literal["notification.new"] = "notification.new"
    data: NotificationNewData


class TaskDueData(ContractModel):
    task: Task
    notification_id: int
    created_at: UtcTimestamp


class TaskDueFrame(Frame):
    event: Literal["task.due"] = "task.due"
    data: TaskDueData


class ForceLogoutData(ContractModel):
    reason: str
    message: str


class ForceLogoutFrame(Frame):
    event: Literal["session.force_logout"] = "session.force_logout"
    data: ForceLogoutData


class EmptyData(ContractModel):
    pass


class CatalogData(ContractModel):
    resource: Literal["statuses", "users"]
    snapshots_changed: bool = False


class CatalogFrame(Frame):
    event: Literal["catalog.updated"] = "catalog.updated"
    data: CatalogData


class HeartbeatFrame(Frame):
    event: Literal["ping", "pong"]
    data: EmptyData = Field(default_factory=EmptyData)


class LockCommandData(ContractModel):
    booking_key: str = Field(min_length=1, max_length=32)


class LockCommandFrame(Frame):
    event: Literal["lock.acquire", "lock.heartbeat", "lock.release"]
    data: LockCommandData


ClientFrame = Annotated[LockCommandFrame | HeartbeatFrame, Field(discriminator="event")]
ServerFrame = Annotated[
    BookingUpdatedFrame
    | LockChangedFrame
    | LockSnapshotFrame
    | NotificationNewFrame
    | TaskDueFrame
    | ForceLogoutFrame
    | HeartbeatFrame
    | CatalogFrame,
    # Catalog events invalidate dynamic labels and current-view snapshots.
    Field(discriminator="event"),
]
client_frame_adapter = TypeAdapter(ClientFrame)
REALTIME_MODELS = (
    CatalogFrame,
    BookingUpdatedFrame,
    LockChangedFrame,
    LockSnapshotFrame,
    NotificationNewFrame,
    TaskDueFrame,
    ForceLogoutFrame,
    HeartbeatFrame,
    LockCommandFrame,
)

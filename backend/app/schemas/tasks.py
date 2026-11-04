"""Reminder dates are local to users.settings.timezone; responses use UTC."""

from datetime import date, time
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

from app.schemas.contracts import ContractModel, Task


class TaskCreate(ContractModel):
    remind_date: date
    remind_time: time | None = None
    message: str | None = Field(default=None, max_length=255)
    client_request_id: UUID | None = None

    @field_validator("remind_time")
    @classmethod
    def local_minute(cls, value):
        if value is not None and (value.tzinfo is not None or value.second or value.microsecond):
            raise ValueError("Use a local HH:mm time.")
        return value


class TaskEdit(ContractModel):
    remind_date: date | None = None
    remind_time: time | None = None
    message: str | None = Field(default=None, max_length=255)

    @field_validator("remind_date", "message")
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError("Omit this field instead of null.")
        return value

    _local_minute = field_validator("remind_time")(TaskCreate.local_minute.__func__)


class DueTasks(ContractModel):
    items: list[Task]
    total: int


class ReminderSettingsPatch(ContractModel):
    timezone: str | None = None
    default_remind_time: str | None = Field(
        default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
    )
    auto_watch_on_note: bool | None = None
    web_push_enabled: bool | None = None
    task_sound: bool | None = None
    web_notifications: bool | None = None
    skip_weekends: bool | None = None

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        if value is None:
            raise ValueError("Timezone cannot be null.")
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Use an IANA timezone.") from None
        return value


class ProfilePatch(ContractModel):
    settings: ReminderSettingsPatch | None = None
    full_name: str | None = None

    @field_validator("full_name")
    @classmethod
    def name(cls, value):
        from app.schemas.admin import display_name

        return display_name(value)


TASK_MODELS = (TaskCreate, TaskEdit, DueTasks, ReminderSettingsPatch, ProfilePatch)

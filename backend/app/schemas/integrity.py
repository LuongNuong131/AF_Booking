from typing import Literal

from pydantic import Field

from app.schemas.contracts import BookingIdentity, ContractModel, JsonValue, Page, UtcTimestamp


class IntegrityDifference(ContractModel):
    actual: JsonValue
    expected: JsonValue


class IntegrityFinding(BookingIdentity):
    fields: dict[str, IntegrityDifference]
    repairable: bool = True
    fixed: bool = False


class IntegrityDetails(ContractModel):
    mode: Literal["report", "fix"]
    trigger: Literal["manual", "scheduled"]
    requested_by: int | None = None
    source_run_id: int | None = None
    scheduled_day: str | None = None
    high_water_id: int = 0
    items: list[IntegrityFinding] = Field(default_factory=list, max_length=200)
    truncated: bool = False
    error: str | None = None


class IntegrityRunDTO(ContractModel):
    id: int
    started_at: UtcTimestamp
    finished_at: UtcTimestamp | None
    checked: int
    mismatched: int
    fixed: int
    status: Literal["running", "completed", "failed", "interrupted"]
    details: IntegrityDetails


class IntegrityFix(ContractModel):
    run_id: int = Field(gt=0)


class IntegrityHistory(Page[IntegrityRunDTO]):
    autofix_enabled: bool
    run_time: str
    timezone: str


INTEGRITY_MODELS = (
    IntegrityHistory,
    IntegrityDifference,
    IntegrityFinding,
    IntegrityDetails,
    IntegrityRunDTO,
    IntegrityFix,
)

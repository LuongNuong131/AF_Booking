from typing import Literal

from pydantic import Field, field_validator

from app.schemas.contracts import AgentSummary, BookingIdentity, ContractModel, UtcTimestamp


class WatchState(ContractModel):
    watching: bool


class AssignmentItem(BookingIdentity):
    id: int
    note_id: int
    from_user: AgentSummary
    to_user: AgentSummary
    message: str | None
    status: Literal["open", "done", "declined"]
    created_at: UtcTimestamp
    resolved_at: UtcTimestamp | None
    decline_reason: str | None


class AssignmentDecline(ContractModel):
    reason: str = Field(min_length=1, max_length=255)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter a reason.")
        return value.strip()


COLLABORATION_MODELS = (WatchState, AssignmentItem, AssignmentDecline)

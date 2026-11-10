from typing import Literal

from pydantic import Field, JsonValue, field_validator

from app.schemas.contracts import ContractModel, UtcTimestamp


class DataField(ContractModel):
    name: str
    kind: str = "text"
    required: bool = False
    options: list[str] = []
    readonly: bool = False
    max_length: int | None = None
    reference: str | None = None


class DataResource(ContractModel):
    name: str
    fields: list[DataField]


class DataMutation(ContractModel):
    values: dict[str, JsonValue]


class DataDelete(ContractModel):
    reason: str = Field(min_length=3, max_length=255)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Enter a meaningful deletion reason.")
        return value


class DataBulkDelete(DataDelete):
    ids: list[str] = Field(min_length=1, max_length=100)


class TrashItem(ContractModel):
    id: int
    resource: str
    record_id: str
    label: str
    deleted_by: int
    reason: str
    created_at: UtcTimestamp


class PurgeRequest(ContractModel):
    ids: list[int] = Field(min_length=1, max_length=2000)
    confirmation: Literal["DELETE"]
    preview_token: str


class PurgePreview(ContractModel):
    token: str
    entries: int
    counts: dict[str, int]
    blockers: list[str]


MANAGEMENT_MODELS = (
    DataField,
    DataResource,
    DataMutation,
    DataDelete,
    DataBulkDelete,
    TrashItem,
    PurgeRequest,
    PurgePreview,
)

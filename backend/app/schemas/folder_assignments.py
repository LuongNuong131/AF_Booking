from pydantic import Field

from app.schemas.contracts import AgentSummary, ContractModel, FolderCard, SupplierType


class FolderAssignmentItem(ContractModel):
    group_id: int
    folder: FolderCard
    assigned_to: AgentSummary | None
    region: str | None
    source_agent: str | None
    review: str | None
    metadata: dict[str, str]
    version: int


class FolderAssignmentPatch(ContractModel):
    assigned_to: int | None = Field(default=None, gt=0)
    region: str | None = Field(default=None, max_length=100)
    review: str | None = Field(default=None, max_length=1000)
    supplier_type: SupplierType | None = None
    expected_version: int = Field(ge=1)
    expected_supplier_type: SupplierType | None = None


class AssignmentImport(ContractModel):
    workbook: str = Field(min_length=1, max_length=700000)
    agent_map: dict[str, str] = Field(default_factory=dict, max_length=100)
    apply: bool = False


class AssignmentImportRow(ContractModel):
    booking_key: str
    supplier_name: str
    station_code: str
    supplier_type: SupplierType
    source_agent: str | None
    username: str | None
    region: str | None
    review: str | None


class AssignmentImportResult(ContractModel):
    source_rows: int
    duplicate_rows: int
    new_bookings: int
    new_folders: int
    updated_folders: int
    preserved_folders: int
    applied: bool
    agent_map: dict[str, str]
    rows: list[AssignmentImportRow]


FOLDER_ASSIGNMENT_MODELS = [
    FolderAssignmentItem,
    FolderAssignmentPatch,
    AssignmentImport,
    AssignmentImportRow,
    AssignmentImportResult,
]

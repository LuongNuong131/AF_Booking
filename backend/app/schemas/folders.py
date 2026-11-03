from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from app.schemas.bookings import BookingItem, GroupInfo
from app.schemas.contracts import ContractModel, FolderCard, KeyResolution, MonthRow, SupplierType


class FolderDetail(ContractModel):
    folder: FolderCard
    months: list[MonthRow]


class StationInfo(ContractModel):
    code: str
    name: str | None


class StationOption(StationInfo):
    folder_count: int


class StationPatch(ContractModel):
    name: str | None = Field(max_length=100)


class StationSection(ContractModel):
    type: SupplierType
    items: list[FolderCard]


class SearchBase(ContractModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    query: str


class SearchBooking(SearchBase):
    kind: Literal["booking"] = "booking"
    booking_key: str
    display_key: str
    exists: bool
    group: GroupInfo | None


class SearchPartial(SearchBase):
    kind: Literal["partial_key"] = "partial_key"
    resolution: KeyResolution


class SearchFolder(SearchBase, FolderDetail):
    kind: Literal["folder"] = "folder"


class SearchFolders(SearchBase):
    kind: Literal["folders"] = "folders"
    items: list[FolderCard]
    total: int
    page: int
    size: int


class SearchStation(SearchBase):
    kind: Literal["station"] = "station"
    station: StationInfo
    sections: list[StationSection]
    total: int
    page: int
    size: int


class SearchStationPeriod(SearchBase):
    kind: Literal["station_period"] = "station_period"
    station: StationInfo
    period: str
    period_label: str
    items: list[BookingItem]
    total: int
    page: int
    size: int


class SearchNone(SearchBase):
    kind: Literal["none"] = "none"
    items: list[FolderCard] = Field(default_factory=list, max_length=0)


SearchResponse = Annotated[
    SearchBooking
    | SearchPartial
    | SearchFolder
    | SearchFolders
    | SearchStation
    | SearchStationPeriod
    | SearchNone,
    Field(discriminator="kind"),
]
FOLDER_MODELS = (
    FolderDetail,
    StationInfo,
    StationOption,
    StationPatch,
    StationSection,
    SearchBooking,
    SearchPartial,
    SearchFolder,
    SearchFolders,
    SearchStation,
    SearchStationPeriod,
    SearchNone,
)

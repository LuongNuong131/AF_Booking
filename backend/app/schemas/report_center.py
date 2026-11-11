from datetime import date
from typing import Literal

from pydantic import Field

from app.schemas.contracts import (
    AgentSummary,
    ContractModel,
    InvoiceState,
    SupplierType,
    UtcTimestamp,
)


class ReportFilters(ContractModel):
    date_from: date
    date_to: date
    agent_id: int | None = Field(default=None, gt=0)
    station: str | None = Field(default=None, pattern=r"^[A-Z]{3,4}$")
    supplier_type: SupplierType | None = None
    status_code: str | None = Field(default=None, max_length=40)
    invoice_state: InvoiceState | None = None
    scope: Literal["mine", "team"] = "mine"


class ReportRecord(ContractModel):
    booking_key: str
    display_key: str
    supplier_name: str
    supplier_type: str
    station: str
    period: str
    agent: AgentSummary
    status_code: str
    status_label: str
    position: str
    note: str | None
    updated_at: UtcTimestamp
    note_count: int
    is_done: bool
    invoice_state: str
    invoice_count: int
    invoices: list[str]


class ReportBreakdown(ContractModel):
    key: str
    label: str
    bookings: int
    updates: int
    done: int


class ReportCenter(ContractModel):
    filters: ReportFilters
    generated_at: UtcTimestamp
    timezone: str
    requested_by: str
    bookings: int
    updates: int
    done: int
    unclassified: int
    undeclared_invoices: int
    agents: list[ReportBreakdown]
    statuses: list[ReportBreakdown]
    stations: list[ReportBreakdown]
    classifications: list[ReportBreakdown]
    trend: list[ReportBreakdown]
    items: list[ReportRecord]
    total: int
    page: int
    size: int


REPORT_CENTER_MODELS = (ReportFilters, ReportRecord, ReportBreakdown, ReportCenter)

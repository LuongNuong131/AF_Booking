from app.schemas.bookings import InvoiceWarning
from app.schemas.contracts import BookingSnapshot, ContractModel, Invoice, InvoiceState


class InvoiceList(ContractModel):
    invoice_state: InvoiceState
    items: list[Invoice]
    number_pattern: str
    max_per_booking: int


class InvoiceResult(ContractModel):
    snapshot: BookingSnapshot
    invoices: list[Invoice]
    skipped_duplicates: list[str]
    warnings: list[InvoiceWarning]


class InvoiceDistribution(ContractModel):
    invoices: str
    bookings: int


class InvoiceReport(ContractModel):
    period: str
    period_label: str
    bookings: int
    with_invoice: int
    no_invoice: int
    not_declared: int
    invoice_total: int
    multi_invoice_bookings: int
    avg_per_booking: float
    max_per_booking: int
    distribution: list[InvoiceDistribution]


INVOICE_MODELS = (InvoiceList, InvoiceResult, InvoiceReport)

from datetime import date

from pydantic import Field

from app.schemas.contracts import (
    AgentSummary,
    BookingIdentity,
    ContractModel,
    InvoiceState,
    StatusSummary,
    SupplierType,
    UtcTimestamp,
)


class RequestMetrics(ContractModel):
    requests: int
    errors: int
    error_rate: float
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None


class EndpointMetrics(RequestMetrics):
    group: str


class MetricPoint(RequestMetrics):
    at: UtcTimestamp
    db_latency_ms: float | None


class SlowQuery(ContractModel):
    fingerprint: str
    duration_ms: float
    at: UtcTimestamp


class PoolMetrics(ContractModel):
    size: int
    checked_out: int
    overflow: int


class JobMetrics(ContractModel):
    name: str
    running: bool
    last_started_at: UtcTimestamp | None
    last_finished_at: UtcTimestamp | None
    duration_ms: float | None
    last_error: str | None


class KeyIndexMetrics(ContractModel):
    ready: bool = False
    keys: int = 0
    folders: int = 0
    container_bytes: int = 0


class SnapshotMetrics(ContractModel):
    entries: int = 0
    hits: int = 0
    misses: int = 0
    hit_ratio: float | None = None


class OperationalErrors(ContractModel):
    window_seconds: int = 60
    counts: dict[str, int] = Field(default_factory=dict)
    threshold: int = 10


class SystemHealth(ContractModel):
    generated_at: UtcTimestamp
    uptime_seconds: float
    version: str
    window_seconds: int
    percentiles_approximate: bool
    total: RequestMetrics
    groups: list[EndpointMetrics]
    db_latency_ms: float | None
    db_error: str | None
    pool: PoolMetrics
    websocket_connections: int
    soft_locks: int
    jobs: list[JobMetrics]
    slow_queries: list[SlowQuery]
    points: list[MetricPoint]
    degraded: bool
    key_index: KeyIndexMetrics = Field(default_factory=KeyIndexMetrics)
    snapshot_cache: SnapshotMetrics = Field(default_factory=SnapshotMetrics)
    operational_errors: OperationalErrors = Field(default_factory=OperationalErrors)


class DailyStatusCount(ContractModel):
    code: str
    label: str
    count: int


class DailyAgent(ContractModel):
    id: int
    full_name: str
    note_count: int
    done_count: int


class DailyStation(ContractModel):
    station_code: str
    supplier_type: SupplierType
    note_count: int
    done_count: int


class DailyBooking(BookingIdentity):
    invoice_state: InvoiceState = InvoiceState.UNKNOWN
    invoice_count: int = 0
    invoices_preview: list[str] = []
    supplier_name: str
    supplier_type: SupplierType
    station_code: str
    status: StatusSummary | None
    agent: AgentSummary | None
    updated_at: UtcTimestamp
    note_count: int = 0


class DailyReportDTO(ContractModel):
    # Frozen export source is persisted internally, never sent in the JSON API.
    record_rows: list[list[str]] = Field(default_factory=list, exclude=True, repr=False)
    report_date: date
    provisional: bool = False
    timezone: str
    generated_at: UtcTimestamp
    cutoff_at: UtcTimestamp
    note_count: int
    new_booking_count: int
    done_count: int
    overdue_task_count: int
    status_distribution: list[DailyStatusCount]
    agents: list[DailyAgent]
    stations: list[DailyStation]
    stale: list[DailyBooking]
    open_rejection_parking: list[DailyBooking]
    repeated: list[DailyBooking]
    done_not_declared: list[DailyBooking] = []


class NoteSearchHit(BookingIdentity):
    note_id: int
    note: str | None
    agent: AgentSummary
    status: StatusSummary
    position: str
    created_at: UtcTimestamp
    match_count: int
    supplier_name: str
    station_code: str
    supplier_type: SupplierType


class NoteSearchPage(ContractModel):
    items: list[NoteSearchHit]
    total: int
    page: int
    size: int
    date_from: date
    date_to: date
    timezone: str
    strategy: str


class PushKeys(ContractModel):
    p256dh: str = Field(max_length=100)
    auth: str = Field(max_length=40)


class PushSubscribe(ContractModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushKeys


class PushUnsubscribe(ContractModel):
    endpoint: str = Field(min_length=1, max_length=2048)


class PushPublicKey(ContractModel):
    public_key: str | None
    enabled: bool


OPERATIONS_MODELS = (
    SystemHealth,
    DailyReportDTO,
    NoteSearchPage,
    PushKeys,
    PushSubscribe,
    PushUnsubscribe,
    PushPublicKey,
)

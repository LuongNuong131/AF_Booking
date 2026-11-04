from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request

from app.core.bounds import KeyPath
from app.core.deps import get_current_user, require_roles
from app.core.timeouts import DeadlineRoute, timeout
from app.schemas.contracts import InvoiceChange
from app.schemas.invoices import InvoiceList, InvoiceReport, InvoiceResult
from app.services.audit import AuditContext
from app.services.session_cache import CurrentUser

router = APIRouter(route_class=DeadlineRoute, tags=["invoices"])
UserDep = Annotated[CurrentUser, Depends(get_current_user)]
ReportDep = Annotated[CurrentUser, Depends(require_roles("admin", "qc"))]
Period = Annotated[str, Query(pattern=r"^[0-9]{2}(0[1-9]|1[0-2])$")]


def current_period(request):
    return datetime.now(ZoneInfo(request.app.state.settings.business_timezone)).strftime("%y%m")


@router.get("/bookings/{key}/invoices", response_model=InvoiceList)
async def listing(key: KeyPath, request: Request, user: UserDep):
    return await request.app.state.invoices.listing(key)


@router.put("/bookings/{key}/invoices", response_model=InvoiceResult)
async def put(key: KeyPath, body: InvoiceChange, request: Request, user: UserDep):
    return await request.app.state.invoices.put(key, body, user, AuditContext.from_request(request))


@router.get("/reports/invoices", response_model=InvoiceReport)
async def report(request: Request, user: ReportDep, period: Period | None = None):
    return await request.app.state.invoices.report(period or current_period(request))


@router.get("/export/invoices")
@timeout("export_timeout_seconds")
async def export(
    request: Request,
    user: ReportDep,
    period: Period | None = None,
    format: Literal["xlsx", "csv"] = "xlsx",
):
    from app.services.invoice_exports import export_invoices

    return await export_invoices(
        request.app.state.engine,
        request.app.state.settings,
        period or current_period(request),
        format,
        request,
        user,
        AuditContext.from_request(request),
    )

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.core.deps import get_current_user
from app.core.timeouts import DeadlineRoute, timeout
from app.schemas.report_center import ReportCenter, ReportFilters
from app.services.audit import AuditContext
from app.services.session_cache import CurrentUser

router = APIRouter(route_class=DeadlineRoute, tags=["report center"])
Actor = Annotated[CurrentUser, Depends(get_current_user)]


@router.get("/reports/center", response_model=ReportCenter)
@timeout("export_timeout_seconds")
async def report(
    request: Request,
    user: Actor,
    filters: Annotated[ReportFilters, Depends()],
    page: int = Query(1, ge=1, le=100000),
    size: int = Query(20, ge=1, le=100),
):
    return await request.app.state.report_center.get(filters, user, page, size)


@router.get("/reports/center/export")
@timeout("export_timeout_seconds")
async def export(
    request: Request,
    user: Actor,
    filters: Annotated[ReportFilters, Depends()],
    format: Literal["xlsx", "csv"] = "xlsx",
):
    return await request.app.state.report_center.export(
        filters, user, AuditContext.from_request(request), format
    )


@router.get("/reports/center/options")
async def report_options(request: Request, user: Actor):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.schemas.report_options import ReportOptions

    zone = request.app.state.settings.business_timezone
    return ReportOptions(
        timezone=zone,
        today=datetime.now(ZoneInfo(zone)).date(),
        scopes=["mine", "team"] if user.role in {"admin", "qc"} else ["mine"],
    )

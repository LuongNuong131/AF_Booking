from dataclasses import dataclass
from ipaddress import ip_address

from fastapi import Request
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import request_id
from app.models import AuditLog


@dataclass(frozen=True)
class AuditContext:
    ip: str | None = None
    request_id: str | None = None

    @classmethod
    def from_request(cls, request: Request) -> "AuditContext":
        try:
            ip = str(ip_address(request.client.host)) if request.client else None
        except ValueError:
            ip = None
        return cls(ip=ip, request_id=request_id.get())


def record_audit(
    session: AsyncSession,
    action: str,
    *,
    actor_id: int | None,
    target_user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    context: AuditContext | None = None,
    meta: dict[str, JsonValue] | None = None,
) -> None:
    data = dict(meta or {})
    if context is not None and context.request_id:
        data["request_id"] = context.request_id
    session.add(
        AuditLog(
            user_id=actor_id,
            action=action,
            entity_type=entity_type or ("user" if target_user_id else None),
            entity_id=entity_id or (str(target_user_id) if target_user_id else None),
            ip=context.ip if context else None,
            meta=data or None,
        )
    )

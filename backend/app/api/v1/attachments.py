import hashlib
import urllib.error
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select

from app.core.bounds import Identifier
from app.core.deps import get_current_user
from app.core.errors import ApiException
from app.core.timeouts import DeadlineRoute, timeout
from app.core.unit_of_work import transaction
from app.models import Attachment, Booking, BookingNote, BookingWorkTask, User
from app.schemas.contracts import Attachment as AttachmentDTO
from app.schemas.contracts import ErrorCode
from app.schemas.workflow import AttachmentStorageInfo
from app.services.audit import AuditContext, record_audit
from app.services.auth import AuthService
from app.services.session_cache import CurrentUser
from app.services.storage import MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS_PER_NOTE
from app.utils.text import clean_note

router = APIRouter(route_class=DeadlineRoute, tags=["note-images"])
Actor = Annotated[CurrentUser, Depends(get_current_user)]
IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"]


def image_type(content):
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def storage_ready(request):
    if not request.app.state.storage.configured:
        raise ApiException(ErrorCode.SERVICE_BUSY, message="Image storage is not configured.")
    return request.app.state.storage


@router.get("/attachments/config", response_model=AttachmentStorageInfo)
async def capabilities(request: Request, user: Actor):
    return AttachmentStorageInfo(
        enabled=request.app.state.storage.configured,
        max_file_bytes=MAX_ATTACHMENT_BYTES,
        max_files=MAX_ATTACHMENTS_PER_NOTE,
        mime_types=IMAGE_TYPES,
    )


@router.post("/notes/{id}/attachments", response_model=AttachmentDTO, status_code=201)
@timeout("note_save_timeout_seconds")
async def upload(
    id: Identifier,
    request: Request,
    user: Actor,
    file_name: Annotated[str, Query(min_length=1, max_length=255)],
):
    return await upload_image(id, request, user, file_name, ticket=False)


@router.post("/work-tasks/{id}/attachments", response_model=AttachmentDTO, status_code=201)
@timeout("note_save_timeout_seconds")
async def upload_ticket(
    id: Identifier,
    request: Request,
    user: Actor,
    file_name: Annotated[str, Query(min_length=1, max_length=255)],
):
    return await upload_image(id, request, user, file_name, ticket=True)


async def upload_image(id, request, user, file_name, *, ticket):
    mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime not in IMAGE_TYPES:
        raise ApiException(
            ErrorCode.VALIDATION_ERROR, message="Use a JPEG, PNG, WebP or GIF image."
        )
    content = await request.body()
    if not content or len(content) > MAX_ATTACHMENT_BYTES:
        raise ApiException(ErrorCode.PAYLOAD_TOO_LARGE)
    if image_type(content) != mime:
        raise ApiException(ErrorCode.VALIDATION_ERROR, message="The file is not a supported image.")
    name = (clean_note(file_name) or "image").replace("\n", " ").replace("\t", " ")[:255]
    key = f"{'tickets' if ticket else 'notes'}/{id}/{hashlib.sha256(content).hexdigest()}"
    owner_column = Attachment.work_task_id if ticket else Attachment.note_id
    async with transaction(
        request.app.state.engine,
        request.app.state.settings,
        seconds=request.app.state.settings.note_save_timeout_seconds,
    ) as session:
        live = await session.scalar(select(User).where(User.id == user.id).with_for_update())
        AuthService.require_live_row(live, user)
        if ticket:
            parent = await session.scalar(
                select(BookingWorkTask)
                .join(Booking, Booking.id == BookingWorkTask.booking_id)
                .where(BookingWorkTask.id == id, Booking.deleted_at.is_(None))
                .with_for_update()
            )
            author = parent.created_by if parent else None
        else:
            parent = await session.scalar(
                select(BookingNote)
                .where(BookingNote.id == id, BookingNote.deleted_at.is_(None))
                .with_for_update()
            )
            author = parent.agent_id if parent else None
        if parent is None or (author != user.id and live.role not in {"qc", "admin"}):
            raise ApiException(ErrorCode.NOT_FOUND)
        storage = storage_ready(request)
        existing = await session.scalar(
            select(Attachment).where(owner_column == id, Attachment.storage_key == key)
        )
        if existing:
            return AttachmentDTO.model_validate(existing, from_attributes=True)
        count = await session.scalar(
            select(func.count()).select_from(Attachment).where(owner_column == id)
        )
        if count >= MAX_ATTACHMENTS_PER_NOTE:
            raise ApiException(
                ErrorCode.VALIDATION_ERROR, message="A note or ticket can have at most five images."
            )
        try:
            await storage.put(key, content, mime)
        except (OSError, urllib.error.URLError, TimeoutError):
            raise ApiException(
                ErrorCode.SERVICE_BUSY, message="Image storage is unavailable. Retry the upload."
            ) from None
        image = Attachment(
            **({"work_task_id": id} if ticket else {"note_id": id}),
            file_name=name,
            mime_type=mime,
            size_bytes=len(content),
            storage_key=key,
        )
        session.add(image)
        await session.flush()
        record_audit(
            session,
            "ticket_image_added" if ticket else "note_image_added",
            actor_id=user.id,
            context=AuditContext.from_request(request),
            entity_type="attachment",
            entity_id=str(image.id),
            meta={"work_task_id" if ticket else "note_id": id},
        )
        return AttachmentDTO.model_validate(image, from_attributes=True)


@router.get("/attachments/{id}/content")
async def download(id: Identifier, request: Request, user: Actor):
    storage = storage_ready(request)
    async with transaction(request.app.state.engine, request.app.state.settings) as session:
        image = await session.get(Attachment, id)
        if image is None:
            raise ApiException(ErrorCode.NOT_FOUND)
        if image.work_task_id is not None:
            parent = await session.scalar(
                select(BookingWorkTask)
                .join(Booking, Booking.id == BookingWorkTask.booking_id)
                .where(BookingWorkTask.id == image.work_task_id, Booking.deleted_at.is_(None))
            )
            if parent is None or (
                parent.created_by != user.id and user.role not in {"qc", "admin"}
            ):
                raise ApiException(ErrorCode.NOT_FOUND)
        else:
            parent = await session.scalar(
                select(BookingNote.id).where(
                    BookingNote.id == image.note_id, BookingNote.deleted_at.is_(None)
                )
            )
            if parent is None:
                raise ApiException(ErrorCode.NOT_FOUND)
        key, mime = image.storage_key, image.mime_type
    try:
        content = await storage.read(key)
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        raise ApiException(
            ErrorCode.SERVICE_BUSY, message="Image storage is unavailable. Retry opening the image."
        ) from None
    return Response(
        content,
        media_type=mime,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="note-image"',
            "X-Content-Type-Options": "nosniff",
        },
    )

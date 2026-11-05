from sqlalchemy import func, or_, select

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import NoteSnippet
from app.schemas.contracts import ErrorCode
from app.schemas.snippets import NoteSnippet as NoteSnippetDTO
from app.services.audit import AuditContext, record_audit


class SnippetService:
    def __init__(self, engine, settings):
        self.engine = engine
        self.settings = settings

    def tx(self):
        return transaction(self.engine, self.settings)

    @staticmethod
    def dto(item: NoteSnippet) -> NoteSnippetDTO:
        return NoteSnippetDTO.model_validate(item, from_attributes=True)

    async def listing(self, user_id: int, query: str | None = None, limit: int = 20):
        stmt = select(NoteSnippet).where(NoteSnippet.user_id == user_id)
        if query:
            needle = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    func.lower(NoteSnippet.title).like(func.lower(needle)),
                    func.lower(NoteSnippet.text).like(func.lower(needle)),
                )
            )
        async with self.tx() as session:
            rows = (
                await session.scalars(
                    stmt.order_by(
                        NoteSnippet.use_count.desc(), NoteSnippet.updated_at.desc()
                    ).limit(limit)
                )
            ).all()
        return [self.dto(row) for row in rows]

    async def create(self, user_id: int, body, context: AuditContext):
        async with self.tx() as session:
            item = NoteSnippet(
                user_id=user_id,
                title=body.title.strip(),
                text=body.text.strip(),
                use_count=0,
            )
            session.add(item)
            await session.flush()
            record_audit(
                session,
                "snippet_created",
                actor_id=user_id,
                entity_type="note_snippet",
                entity_id=str(item.id),
                context=context,
                meta={"title": item.title},
            )
            return self.dto(item)

    async def update(self, snippet_id: int, user_id: int, body, context: AuditContext):
        async with self.tx() as session:
            item = await session.scalar(
                select(NoteSnippet)
                .where(NoteSnippet.id == snippet_id, NoteSnippet.user_id == user_id)
                .with_for_update()
            )
            if item is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            values = body.model_dump(exclude_unset=True)
            if "title" in values:
                item.title = values["title"].strip()
            if "text" in values:
                item.text = values["text"].strip()
            record_audit(
                session,
                "snippet_updated",
                actor_id=user_id,
                entity_type="note_snippet",
                entity_id=str(item.id),
                context=context,
                meta={"fields": list(values)},
            )
            return self.dto(item)

    async def delete(self, snippet_id: int, user_id: int, context: AuditContext):
        async with self.tx() as session:
            item = await session.scalar(
                select(NoteSnippet)
                .where(NoteSnippet.id == snippet_id, NoteSnippet.user_id == user_id)
                .with_for_update()
            )
            if item is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            await session.delete(item)
            record_audit(
                session,
                "snippet_deleted",
                actor_id=user_id,
                entity_type="note_snippet",
                entity_id=str(snippet_id),
                context=context,
            )
        return {"id": snippet_id}

    async def use(self, snippet_id: int, user_id: int, context: AuditContext):
        async with self.tx() as session:
            item = await session.scalar(
                select(NoteSnippet)
                .where(NoteSnippet.id == snippet_id, NoteSnippet.user_id == user_id)
                .with_for_update()
            )
            if item is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            item.use_count += 1
            record_audit(
                session,
                "snippet_used",
                actor_id=user_id,
                entity_type="note_snippet",
                entity_id=str(snippet_id),
                context=context,
            )
            return self.dto(item)

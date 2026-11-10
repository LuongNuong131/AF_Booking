"""Hide recycled operational roots while retaining historical user/status attribution."""

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.models import Booking, BookingGroup, Station


@event.listens_for(Session, "do_orm_execute")
def visible_records(state):
    if state.is_select and not state.session.info.get("include_deleted"):
        state.statement = state.statement.options(
            with_loader_criteria(
                Booking, lambda row: row.deleted_at.is_(None), include_aliases=True
            ),
            with_loader_criteria(
                BookingGroup, lambda row: row.deleted_at.is_(None), include_aliases=True
            ),
            with_loader_criteria(
                Station, lambda row: row.deleted_at.is_(None), include_aliases=True
            ),
        )

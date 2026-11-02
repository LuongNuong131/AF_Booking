from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.contracts import (
    BookingSnapshot,
    CursorPage,
    FolderCard,
    Invoice,
    InvoiceChange,
    Page,
    Task,
)


def snapshot() -> dict[str, Any]:
    return {
        "booking_key": "CW2154654-RDU-2609",
        "display_key": "CW 2154654-RDU-2609",
        "cw_number": "CW2154654",
        "station_code": "RDU",
        "period": "2609",
        "period_label": "Sep 2026",
        "supplier": {"name": "Example Hotel", "type": "hotel"},
        "version": 1,
        "last_status": None,
        "last_position": None,
        "last_agent": None,
        "last_note_preview": None,
        "is_done": False,
        "done_at": None,
        "updated_at": "2026-11-02T15:15:30.123+07:00",
        "is_stale": False,
        "invoice_state": "unknown",
        "invoice_count": 0,
        "invoices_preview": [],
    }


def test_snapshot_serializes_utc_milliseconds_and_preserves_nullable_fields() -> None:
    data = BookingSnapshot.model_validate(snapshot()).model_dump(mode="json")
    assert data["updated_at"] == "2026-11-02T08:15:30.123Z"
    assert data["done_at"] is None
    assert data["last_agent"] is None
    assert data["booking_key"] == "CW2154654-RDU-2609"
    assert data["display_key"] == "CW 2154654-RDU-2609"


def test_naive_timestamps_and_oversized_invoice_previews_are_rejected() -> None:
    with pytest.raises(ValidationError):
        BookingSnapshot.model_validate({**snapshot(), "updated_at": "2026-11-02T08:15:30"})
    with pytest.raises(ValidationError):
        BookingSnapshot.model_validate({**snapshot(), "invoices_preview": ["A", "B", "C", "D"]})


def test_task_and_nested_folder_booking_require_display_keys() -> None:
    task = {
        "id": 1,
        "booking_key": "CW2154654-RDU-2609",
        "message": "Check mail",
        "remind_at": "2026-11-02T08:15:30.123Z",
        "status": "pending",
        "is_due": False,
        "is_overdue": False,
        "snooze_count": 0,
        "created_at": "2026-11-01T08:15:30.000Z",
        "completed_at": None,
        "booking_changed_since": False,
        "booking": {
            "last_status": None,
            "last_agent": None,
            "is_done": False,
            "updated_at": "2026-11-01T08:15:30.000Z",
        },
    }
    with pytest.raises(ValidationError):
        Task.model_validate(task)
    Task.model_validate({**task, "display_key": "CW 2154654-RDU-2609"})
    folder = {
        "cw_number": "CW2154654",
        "supplier_name": "Example Hotel",
        "supplier_type": "hotel",
        "station_code": "RDU",
        "booking_count": 1,
        "open_count": 1,
        "last_activity_at": "2026-11-01T08:15:30.000Z",
        "latest": {
            "booking_key": task["booking_key"],
            "period_label": "Sep 2026",
            "status": None,
            "agent": None,
        },
    }
    with pytest.raises(ValidationError):
        FolderCard.model_validate(folder)


def test_pagination_requires_explicit_cursor_end_and_positive_page_size() -> None:
    assert CursorPage[Invoice](items=[], next_cursor=None).model_dump(mode="json") == {
        "items": [],
        "next_cursor": None,
    }
    with pytest.raises(ValidationError):
        CursorPage[Invoice].model_validate({"items": []})
    with pytest.raises(ValidationError):
        Page[BookingSnapshot](items=[], total=0, page=0, size=20)
    assert Page[BookingSnapshot](items=[], total=0, page=1, size=20).page == 1


def test_optional_invoice_change_retains_the_difference_between_absent_and_false() -> None:
    assert InvoiceChange().model_dump(exclude_unset=True) == {}
    assert InvoiceChange(no_invoice=False).model_dump(exclude_unset=True) == {"no_invoice": False}
    with pytest.raises(ValidationError):
        InvoiceChange.model_validate({"no_invoice": None})

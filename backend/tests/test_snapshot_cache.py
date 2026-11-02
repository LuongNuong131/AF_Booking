from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.schemas.bookings import BookingItem
from app.services.snapshot_cache import SnapshotCache


def snapshot():
    return BookingItem(
        booking_key="CW2154654-RDU-2609",
        display_key="CW 2154654-RDU-2609",
        cw_number="CW2154654",
        station_code="RDU",
        period="2609",
        period_label="Sep 2026",
        supplier={"name": "Example Hotel", "type": "hotel"},
        supplier_name="Example Hotel",
        supplier_type="hotel",
        version=1,
        last_status=None,
        last_position=None,
        last_agent=None,
        last_note_preview=None,
        is_done=False,
        done_at=None,
        updated_at=datetime.now(UTC) - timedelta(hours=2),
        is_stale=False,
        invoice_state="unknown",
        invoice_count=0,
        invoices_preview=[],
    )


def test_generation_blocks_racing_reads_and_group_edit_invalidates():
    cache = SnapshotCache()
    generation = cache.generation
    cache.invalidate(1)
    cache.put(1, snapshot(), 10, 1, generation)
    assert cache.get(1) is None
    cache.put(1, snapshot(), 10, 1, cache.generation)
    cached = cache.get(1)
    assert cached.is_stale and cached.stale_hours >= 2
    cached.supplier_name = "Changed by caller"
    assert cache.get(1).supplier_name == "Example Hotel"
    cache.invalidate_group(10)
    assert cache.get(1) is None


def test_lru_expiry_and_done_never_stale():
    cache = SnapshotCache(capacity=2, ttl=30)
    with patch("app.services.snapshot_cache.time.monotonic", return_value=100):
        for identifier in (1, 2):
            cache.put(identifier, snapshot(), 10, 1, cache.generation)
        cache.get(1)
        done = snapshot().model_copy(update={"is_done": True})
        cache.put(3, done, 10, 1, cache.generation)
        assert cache.get(2) is None and not cache.get(3).is_stale
    with patch("app.services.snapshot_cache.time.monotonic", return_value=131):
        assert cache.get(1) is None and cache.get(3) is None

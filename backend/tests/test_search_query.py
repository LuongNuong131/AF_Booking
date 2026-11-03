import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import ApiException
from app.schemas.bookings import GroupInfo
from app.services.key_index import GroupEntry, KeyIndex
from app.services.search_limiter import SearchLimiter
from app.services.snapshot_cache import SnapshotCache
from app.utils.search_query import QueryKind, classify_query


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        (case["input"], case["kind"])
        for case in json.loads(
            (Path(__file__).resolve().parents[2] / "fixtures" / "search-queries.json").read_text()
        )
    ],
)
def test_classification(raw, kind):
    assert classify_query(raw, {"YUL"}).kind == kind


def test_configurable_station_and_canonical_query():
    assert classify_query("XX", {"XX"}, r"[A-Z]{2}").kind == QueryKind.STATION
    assert classify_query("xx 2608", (), r"[A-Z]{2}").kind == QueryKind.STATION_PERIOD
    assert classify_query("cw 2154927 - yul - 2608").query == "CW2154927-YUL-2608"
    assert classify_query(" double   tree ").query == "DOUBLE TREE"


def entry(identifier, name, age=0):
    return GroupEntry(
        identifier,
        GroupInfo(
            cw_number=f"CW{2154000 + identifier}",
            station_code="YUL",
            supplier_name=name,
            supplier_type="hotel",
        ),
        datetime.now(UTC) - timedelta(hours=age),
    )


def test_supplier_word_prefixes_accents_punctuation_and_ranking_use_same_index():
    index = KeyIndex(None, Settings(_env_file=None), SnapshotCache())
    for group in [
        entry(1, "Double Tree", 3),
        entry(2, "Double Tree Hotel", 2),
        entry(3, "YUL Double Tree", 1),
        entry(4, "Grand HÔTEL d/b/a & Étoile", 0),
        entry(5, "Double Tree West", 4),
    ]:
        index.update(None, group)
    assert [g.id for g in index.matching_groups("double tree")] == [1, 2, 5, 3]
    assert {g.id for g in index.matching_groups("tr dou")} == {1, 2, 3, 5}
    assert [g.id for g in index.matching_groups("eto hot")] == [4]
    assert [g.id for g in index.matching_groups("d/b/a étoile")] == [4]
    index.update(None, entry(4, "Renamed Hotel"))
    assert index.matching_groups("étoile") == []
    assert index.matching_groups("ren hot")[0].id == 4


def test_search_limiter_is_per_user_expires_and_cannot_evict_active_limits():
    limiter = SearchLimiter(limit=2, window=60, capacity=2)
    now = [100.0]
    limiter.clock = lambda: now[0]
    limiter.check(1)
    limiter.check(1)
    with pytest.raises(ApiException) as error:
        limiter.check(1)
    assert error.value.code == "RATE_LIMITED" and error.value.headers["Retry-After"] == "60"
    limiter.check(2)
    with pytest.raises(ApiException):
        limiter.check(3)
    now[0] += 61
    limiter.check(1)
    limiter.check(3)

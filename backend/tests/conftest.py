"""Unit tests never inherit a real deployment database from the surrounding shell."""

import pytest


@pytest.fixture(autouse=True)
def isolate_unit_database_environment(request, monkeypatch):
    if (
        not request.node.path.name.endswith("_database.py")
        and request.node.path.name != "test_tidb_integration.py"
    ):
        for name in (
            "DATABASE_URL",
            "DATABASE_SSL_CA",
            "DB_SSL",
            "DATABASE_SSL",
            "SENTRY_DSN",
        ):
            monkeypatch.delenv(name, raising=False)

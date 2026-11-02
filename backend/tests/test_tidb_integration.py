import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.core.db import create_database_engine
from app.main import create_app

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not configured"
)


def database_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=os.environ["TEST_DATABASE_URL"],
        database_ssl_ca=os.environ.get("TEST_DATABASE_SSL_CA"),
        **overrides,
    )


def test_ready_connects_to_real_tidb() -> None:
    with TestClient(create_app(database_settings())) as client:
        response = client.get("/api/v1/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "connected"}


async def test_database_session_uses_tls_utc_and_binary_ascii() -> None:
    engine = create_database_engine(database_settings())
    assert engine is not None
    try:
        async with engine.connect() as connection:
            tls = (await connection.execute(text("SHOW STATUS LIKE 'Ssl_cipher'"))).one()
            assert tls[1], "The database connection must be encrypted"
            assert (await connection.execute(text("SELECT @@session.time_zone"))).scalar_one() == (
                "+00:00"
            )
            collation = await connection.execute(
                text("SELECT COLLATION(CONVERT('CW2154927-YUL-2608' USING ascii))")
            )
            assert collation.scalar_one() == "ascii_bin"
    finally:
        await engine.dispose()

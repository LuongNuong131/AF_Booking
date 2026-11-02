import ssl

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.db import create_database_engine


@pytest.mark.parametrize(
    "overrides",
    [
        {"app_env": "production", "database_ssl": False, "cors_origins": []},
        {"app_env": "production", "cors_origins": ["http://localhost:5173"]},
        {"cors_origins": ["*"]},
        {"cors_origins": ["https://example.com/"]},
        {"database_url": "mysql://user:password@localhost/tracker"},
        {"database_url": "mysql+aiomysql://user:password@localhost/tracker?ssl=false"},
        {"db_pool_size": 10, "db_max_overflow": 1},
        {"business_timezone": "Not/AZone"},
    ],
)
def test_unsafe_configuration_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_tls_uses_certificate_and_hostname_verification() -> None:
    config = Settings(
        _env_file=None, database_url="mysql+aiomysql://user:password@localhost/tracker"
    )
    engine = create_database_engine(config)
    assert engine is not None
    _, connection_args = engine.dialect.create_connect_args(engine.url)
    # Inspect the final DBAPI arguments without opening a network connection.
    from unittest.mock import patch

    with patch("app.core.db.create_async_engine", return_value=engine) as create:
        create_database_engine(config)
    tls = create.call_args.kwargs["connect_args"]["ssl"]
    assert tls.check_hostname is True
    assert tls.verify_mode == ssl.CERT_REQUIRED
    assert connection_args["db"] == "tracker"


def test_invalid_url_error_does_not_print_secrets() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url="invalid-private-database-secret")
    assert "invalid-private-database-secret" not in str(error.value)

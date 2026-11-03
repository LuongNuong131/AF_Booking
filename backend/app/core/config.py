import re
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr | None = None
    database_ssl: bool = True
    db_ssl: bool | None = None
    database_ssl_ca: str | None = None
    cors_origins: list[str] = ["http://localhost:5173"]
    business_timezone: str = "Asia/Ho_Chi_Minh"
    db_pool_size: int = Field(default=5, ge=1, le=10)
    db_max_overflow: int = Field(default=0, ge=0, le=5)
    db_pool_recycle_seconds: int = Field(default=280, ge=1, le=280)
    db_pool_timeout_seconds: float = Field(default=5, gt=0, le=30)
    db_connect_timeout_seconds: float = Field(default=5, gt=0, le=30)
    db_query_timeout_ms: int = Field(default=5000, ge=1, le=30000)
    request_timeout_seconds: float = Field(default=8, gt=0, le=60)
    db_lock_wait_timeout_seconds: int = Field(default=5, ge=1, le=30)
    jwt_secret_key: SecretStr | None = Field(default=None, min_length=32)
    jwt_expire_minutes: int = Field(default=720, ge=1, le=10080)
    jwt_issuer: str = Field(default="booking-tracker", min_length=1, max_length=100)
    jwt_audience: str = Field(default="booking-tracker-web", min_length=1, max_length=100)
    auth_cache_ttl_seconds: float = Field(default=12, ge=10, le=15)
    auth_cache_max_entries: int = Field(default=1000, ge=100, le=10000)
    login_max_failures: int = Field(default=5, ge=1, le=20)
    login_lockout_seconds: int = Field(default=300, ge=1, le=3600)
    auth_hash_concurrency: int = Field(default=2, ge=1, le=8)
    ws_send_timeout_seconds: float = Field(default=5, gt=0, le=30)
    ws_ping_interval_seconds: float = Field(default=25, gt=0, le=60)
    ws_idle_timeout_seconds: float = Field(default=60, gt=0, le=300)
    ws_queue_size: int = Field(default=128, ge=1, le=1024)
    ws_max_message_bytes: int = Field(default=4096, ge=256, le=65536)
    lock_ttl_seconds: float = Field(default=150, gt=0, le=600)
    lock_sweep_interval_seconds: float = Field(default=25, gt=0, le=30)
    scheduler_enabled: bool = True
    scheduler_job_timeout_seconds: float = Field(default=120, gt=0, le=300)
    stale_job_interval_seconds: float = Field(default=1200, gt=0, le=1800)
    stale_job_batch_size: int = Field(default=100, ge=1, le=500)
    lookup_timeout_seconds: float = Field(default=6, gt=0, le=60)
    note_save_timeout_seconds: float = Field(default=12, gt=0, le=60)
    export_timeout_seconds: float = Field(default=55, gt=0, le=300)
    search_db_timeout_seconds: float = Field(default=3, gt=0, le=3)
    search_max_requests: int = Field(default=120, ge=1, le=10000)
    search_rate_window_seconds: float = Field(default=60, gt=0, le=3600)
    search_rate_max_entries: int = Field(default=10000, ge=1, le=100000)
    station_cache_ttl_seconds: float = Field(default=60, gt=0, le=60)
    key_index_enabled: bool = True
    key_index_batch_size: int = Field(default=1000, ge=1, le=5000)
    key_index_reconcile_seconds: float = Field(default=600, gt=0, le=3600)
    snapshot_cache_ttl_seconds: float = Field(default=30, gt=0, le=300)
    snapshot_cache_max_entries: int = Field(default=2000, ge=1, le=10000)
    stale_hours_default: int = Field(default=24, ge=1, le=8760)
    station_code_pattern: str = r"[A-Z]{3}"
    invoice_number_pattern: str = r"[A-Z0-9_./-]{3,40}"
    invoice_max_per_booking: int = Field(default=20, ge=1, le=100)

    @field_validator("station_code_pattern", "invoice_number_pattern")
    @classmethod
    def validate_pattern(cls, value: str) -> str:
        try:
            re.compile(value, re.ASCII)
        except re.error:
            raise ValueError("A valid ASCII regular expression is required") from None
        return value

    @field_validator("database_url", "database_ssl_ca", "jwt_secret_key", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            url = make_url(value.get_secret_value())
        except Exception:
            raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from None
        if url.drivername != "mysql+aiomysql" or not url.host or not url.database:
            raise ValueError("DATABASE_URL must use mysql+aiomysql and include a host and database")
        if url.query:
            if any(key != "charset" for key in url.query):
                raise ValueError(
                    "Only the charset URL option is supported; configure TLS separately"
                )
            if url.query.get("charset") != "utf8mb4":
                raise ValueError("DATABASE_URL charset must be utf8mb4")
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        for origin in values:
            url = urlsplit(origin)
            if (
                url.scheme not in {"http", "https"}
                or not url.netloc
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
                or "*" in origin
            ):
                raise ValueError(
                    "CORS origins must be exact HTTP(S) origins without a trailing slash"
                )
        return values

    @field_validator("business_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("BUSINESS_TIMEZONE must be a valid IANA timezone") from None
        return value

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        if self.db_ssl is not None:
            if "database_ssl" in self.model_fields_set and self.db_ssl != self.database_ssl:
                raise ValueError("DB_SSL and DATABASE_SSL must agree when both are configured")
            self.database_ssl = self.db_ssl
        if self.db_pool_size + self.db_max_overflow > 10:
            raise ValueError("The total database pool must not exceed 10 connections")
        if self.app_env == "production":
            if not self.database_ssl:
                raise ValueError("TLS verification is required in production")
            if any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("Production CORS origins must use HTTPS")
        return self

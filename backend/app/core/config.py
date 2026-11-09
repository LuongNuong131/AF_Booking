import re
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
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
    jwt_secret_key: SecretStr | None = Field(
        default=None,
        min_length=32,
        validation_alias=AliasChoices("JWT_SECRET_KEY", "JWT_SECRET", "jwt_secret_key"),
    )
    jwt_expire_minutes: int = Field(default=720, ge=1, le=10080)
    jwt_issuer: str = Field(default="booking-tracker", min_length=1, max_length=100)
    jwt_audience: str = Field(default="booking-tracker-web", min_length=1, max_length=100)
    auth_cache_ttl_seconds: float = Field(default=12, ge=10, le=15)
    auth_cache_max_entries: int = Field(default=1000, ge=100, le=10000)
    login_max_failures: int = Field(default=5, ge=1, le=20)
    login_lockout_seconds: int = Field(default=300, ge=1, le=3600)
    auth_hash_concurrency: int = Field(default=2, ge=1, le=8)
    max_request_body_bytes: int = Field(default=1048576, ge=1, le=1048576)
    ws_max_messages_per_second: int = Field(default=20, ge=1, le=100)
    ws_send_timeout_seconds: float = Field(default=5, gt=0, le=30)
    ws_ping_interval_seconds: float = Field(default=25, gt=0, le=60)
    ws_idle_timeout_seconds: float = Field(default=60, gt=0, le=300)
    ws_queue_size: int = Field(default=128, ge=1, le=1024)
    ws_max_message_bytes: int = Field(default=4096, ge=256, le=65536)
    lock_ttl_seconds: float = Field(default=150, gt=0, le=600)
    lock_sweep_interval_seconds: float = Field(default=25, gt=0, le=30)
    integrity_autofix: bool = False
    integrity_run_time: str = Field(default="02:00", pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    integrity_timeout_seconds: float = Field(default=600, gt=0, le=3600)
    app_version: str = Field(default="0.2.0", min_length=1, max_length=64)
    sentry_dsn: SecretStr | None = None
    error_alert_threshold: int = Field(default=10, ge=1, le=100000)
    error_alert_window_seconds: int = Field(default=60, ge=10, le=900)
    error_alert_cooldown_seconds: int = Field(default=60, ge=1, le=3600)
    retention_enabled: bool = True
    audit_retention_days: int = Field(default=180, ge=1, le=3650)
    notification_retention_days: int = Field(default=60, ge=1, le=3650)
    task_retention_days: int = Field(default=90, ge=1, le=3650)
    retention_interval_seconds: int = Field(default=86400, ge=60, le=604800)
    retention_batch_size: int = Field(default=1000, ge=1, le=5000)
    retention_max_batches: int = Field(default=100, ge=1, le=1000)
    daily_report_time: str = Field(default="18:30", pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    note_search_strategy: Literal["like", "fulltext"] = "like"
    slow_query_threshold_ms: float = Field(default=200, ge=0, le=30000)
    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    vapid_subject: str | None = None
    scheduler_enabled: bool = True
    monthly_booking_enabled: bool = True
    monthly_booking_day: int = Field(default=25, ge=1, le=28)
    monthly_booking_token: SecretStr | None = Field(default=None, min_length=32, max_length=512)
    scheduler_job_timeout_seconds: float = Field(default=120, gt=0, le=300)
    task_job_interval_seconds: float = Field(default=30, gt=0, le=60)
    stale_job_interval_seconds: float = Field(default=1200, gt=0, le=1800)
    stale_job_batch_size: int = Field(default=100, ge=1, le=500)
    lookup_timeout_seconds: float = Field(default=6, gt=0, le=60)
    note_save_timeout_seconds: float = Field(default=12, gt=0, le=60)
    export_booking_key_style: Literal["display", "canonical"] = "display"
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
    invoice_number_pattern: str = r"^[A-Z0-9][A-Z0-9\-_/.]{2,39}$"
    invoice_max_per_booking: int = Field(default=20, ge=1, le=100)

    @field_validator("station_code_pattern", "invoice_number_pattern")
    @classmethod
    def validate_pattern(cls, value: str) -> str:
        try:
            re.compile(value, re.ASCII)
        except re.error:
            raise ValueError("A valid ASCII regular expression is required") from None
        return value

    @field_validator(
        "database_url",
        "database_ssl_ca",
        "jwt_secret_key",
        "sentry_dsn",
        "vapid_public_key",
        "vapid_private_key",
        "vapid_subject",
        "monthly_booking_token",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("sentry_dsn")
    @classmethod
    def valid_sentry_dsn(cls, value):
        if value is not None:
            url = urlsplit(value.get_secret_value())
            if (
                url.scheme != "https"
                or not url.hostname
                or not url.username
                or not url.path.strip("/").isdigit()
                or url.query
                or url.fragment
            ):
                raise ValueError("SENTRY_DSN must be a valid HTTPS project DSN")
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def reject_default_signing_key(cls, value):
        if value is not None:
            key = value.get_secret_value().strip().lower()
            if (
                len(key) < 32
                or key.startswith(
                    (
                        "change-me",
                        "changeme",
                        "your-secret",
                        "your-super-secret",
                        "replace-with",
                        "default-secret",
                        "development-secret",
                    )
                )
                or key in {"secret" * 8, "x" * 32, "a" * 32, "0" * 32}
            ):
                raise ValueError("Configure a random JWT signing key; default values are forbidden")
        return value

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
            if self.jwt_secret_key is None:
                raise ValueError("JWT_SECRET_KEY is required in production")
            if not self.database_ssl:
                raise ValueError("TLS verification is required in production")
            if any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("Production CORS origins must use HTTPS")
        return self

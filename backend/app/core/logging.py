"""Structured logs retain only approved context fields; exceptions never dump locals."""

import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record):
        from app.core.request_context import request_id

        output = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", "application.log"),
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id.get()),
            "user_id": getattr(record, "user_id", None),
        }
        for field in (
            "method",
            "path",
            "status",
            "duration_ms",
            "fingerprint",
            "error_code",
            "window_seconds",
            "count",
            "deleted",
            "key_count",
            "cache_hit_ratio",
        ):
            if hasattr(record, field):
                output[field] = getattr(record, field)
        if record.exc_info:
            output["exception_type"] = record.exc_info[0].__name__
        return json.dumps(output, ensure_ascii=False, separators=(",", ":"))


def configure_json_logging():
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    root.setLevel(logging.WARNING)
    logging.getLogger("app").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    for name in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    formatter = JsonFormatter()
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(formatter)

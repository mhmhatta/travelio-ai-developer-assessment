"""Minimal JSON logging without guest-content leakage."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Final

_LOGGER_NAME: Final = "travelio_classifier"
_HANDLER_MARKER: Final = "travelio_json_handler"
_SAFE_EXTRA_FIELDS: Final = (
    "request_id",
    "attempt",
    "latency_ms",
    "error_code",
)


class JsonFormatter(logging.Formatter):
    """Format application records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize standard metadata and approved extra fields."""
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for field_name in _SAFE_EXTRA_FIELDS:
            if hasattr(record, field_name):
                payload[field_name] = getattr(record, field_name)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging() -> None:
    """Install one package-scoped JSON handler."""
    package_logger = logging.getLogger(_LOGGER_NAME)
    has_handler = any(
        getattr(handler, "name", None) == _HANDLER_MARKER
        for handler in package_logger.handlers
    )
    if not has_handler:
        handler = logging.StreamHandler(sys.stdout)
        handler.name = _HANDLER_MARKER
        handler.setFormatter(JsonFormatter())
        package_logger.addHandler(handler)
    package_logger.setLevel(logging.INFO)
    package_logger.propagate = False

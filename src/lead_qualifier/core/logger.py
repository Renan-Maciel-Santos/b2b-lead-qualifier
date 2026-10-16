"""Structured JSON logging configuration for cloud and container runtime."""

from datetime import UTC, datetime
import json
import logging
from typing import Any


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects for log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a LogRecord into a serialized JSON string.

        Args:
            record: Standard Python logging LogRecord.

        Returns:
            str: JSON-encoded log payload.
        """
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def setup_logger() -> logging.Logger:
    """Initialize and configure the root application logger.

    Returns:
        logging.Logger: Configured logger instance outputting structured JSON to stdout.
    """
    app_logger = logging.getLogger("lead_qualifier")
    app_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JSONFormatter())
    app_logger.addHandler(console_handler)

    return app_logger


logger = setup_logger()

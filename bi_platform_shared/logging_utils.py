"""Safe structured logging helpers shared across backend services.

Python's ``logging`` module raises ``KeyError`` when ``extra`` contains
reserved ``LogRecord`` attributes (for example ``filename`` or ``message``).
These helpers sanitize conflicting keys so structured logging never crashes a
request handler.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

_RESERVED_LOG_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__.keys()) | {
    "message",
    "asctime",
}

_SAFE_KEY_RENAMES: dict[str, str] = {
    "filename": "uploaded_filename",
    "module": "source_module",
    "msg": "log_message_template",
    "name": "logger_name",
    "levelname": "log_level_name",
    "pathname": "source_pathname",
    "funcName": "source_func_name",
    "lineno": "source_lineno",
    "process": "source_process_id",
    "thread": "source_thread_id",
    "threadName": "source_thread_name",
    "message": "log_message",
}


def sanitize_log_extra(extra: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return an ``extra`` mapping that is safe for ``logging``.

    Reserved keys are renamed to predictable, non-conflicting names while
    preserving all values.
    """

    if not extra:
        return {}

    sanitized: dict[str, Any] = {}
    for raw_key, value in extra.items():
        key = str(raw_key)
        candidate = _SAFE_KEY_RENAMES.get(key, key)
        if key in _RESERVED_LOG_RECORD_KEYS or candidate in _RESERVED_LOG_RECORD_KEYS:
            candidate = _SAFE_KEY_RENAMES.get(key, f"extra_{key}")

        if candidate in sanitized:
            suffix = 2
            unique = f"{candidate}_{suffix}"
            while unique in sanitized or unique in _RESERVED_LOG_RECORD_KEYS:
                suffix += 1
                unique = f"{candidate}_{suffix}"
            candidate = unique

        sanitized[candidate] = value
    return sanitized


def log_with_safe_extra(
    logger: logging.Logger,
    level: int,
    message: str,
    *args: Any,
    extra: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """Log while automatically sanitizing ``extra`` fields."""

    kwargs["extra"] = sanitize_log_extra(extra)
    logger.log(level, message, *args, **kwargs)


__all__ = ["log_with_safe_extra", "sanitize_log_extra"]

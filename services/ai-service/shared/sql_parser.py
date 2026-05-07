from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


class SqlParserStatus:
    def __init__(self, parser: str, available: bool, degraded: bool):
        self.parser = parser
        self.available = available
        self.degraded = degraded


def _fallback_allowed() -> bool:
    value = str(os.getenv("ALLOW_SQLGLOT_FALLBACK", "false")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def ensure_sql_parser_ready(*, strict: bool = True) -> SqlParserStatus:
    try:
        import sqlglot  # noqa: F401

        return SqlParserStatus(parser="sqlglot", available=True, degraded=False)
    except Exception as exc:
        allow_fallback = _fallback_allowed()
        if strict and not allow_fallback:
            raise RuntimeError(
                "sqlglot is required at runtime. Install sqlglot or set "
                "ALLOW_SQLGLOT_FALLBACK=true only for local dev/test."
            ) from exc
        logger.warning("sqlglot unavailable; SQL parsing is running in degraded fallback mode")
        return SqlParserStatus(parser="fallback", available=False, degraded=True)

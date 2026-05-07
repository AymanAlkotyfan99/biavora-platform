"""SQL execution flow for query-service (Phase 7 / CRIT-05).

The previous implementation accepted client-supplied ``workspace_database``
fields and silently fell back to ``"etl"`` when the field was missing. Phase
7 of the audit forbids both: every call into ``execute_sql_payload`` must
arrive with a workspace-derived database, otherwise it returns HTTP 400.
"""

from __future__ import annotations

import logging
from typing import Any

from query_api.services import (
    SQLGuard,
    WorkspaceClickhouseDbResolutionError,
    get_clickhouse_executor,
    resolve_workspace_clickhouse_db,
    sanitize_query_results,
)

logger = logging.getLogger(__name__)


def _failed_payload(
    *,
    sql: str,
    error: str,
    error_code: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a stable failure payload.

    Phase 8 — the response always carries the full ``QueryExecutionResult``
    metadata (``column_types``, ``scanned_rows``, ``output_bytes``,
    ``aborted_due_to_timeout``, ``settings_applied``) so the caller does
    not have to special-case the failure shape.
    """

    payload: dict[str, Any] = {
        "status": "failed",
        "sql": sql,
        "rows": [],
        "columns": [],
        "column_types": [],
        "row_count": 0,
        "scanned_rows": None,
        "output_bytes": None,
        "empty_result": False,
        "execution_time_ms": 0,
        "aborted_due_to_timeout": False,
        "settings_applied": {},
        "error": error,
        "error_code": error_code,
        "error_message": error,
    }
    if extra:
        payload.update(extra)
    return payload


def _resolve_workspace_database(payload: dict[str, Any]) -> tuple[str, dict[str, Any] | None, int]:
    """Resolve and validate the ClickHouse database for this request.

    Phase 7 / CRIT-05: an explicit ``workspace_database`` (set by
    ``QueryExecuteInternalView`` after it consulted the workspace model) is
    preferred. When absent, we resolve from ``workspace_id``. If neither is
    available we return an HTTP-400-shaped failure payload.
    """

    explicit_db = str(payload.get("workspace_database") or "").strip()
    if explicit_db:
        return explicit_db, None, 200

    workspace_id = payload.get("workspace_id")
    if workspace_id in (None, "", b""):
        failed = _failed_payload(
            sql=str(payload.get("sql", "")).strip(),
            error="workspace_id is required for query execution.",
            error_code="WORKSPACE_ID_REQUIRED",
        )
        return "", failed, 400

    try:
        resolution = resolve_workspace_clickhouse_db(workspace_id)
    except WorkspaceClickhouseDbResolutionError as exc:
        logger.warning(
            "execute_sql_payload_workspace_unresolved code=%s message=%s",
            exc.code,
            str(exc),
        )
        failed = _failed_payload(
            sql=str(payload.get("sql", "")).strip(),
            error=str(exc),
            error_code=exc.code.upper(),
        )
        return "", failed, int(exc.http_status or 400)

    return resolution.clickhouse_db, None, 200


def execute_sql_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    sql = str(payload.get("sql", "") or "").strip()

    workspace_database, failure, failure_status = _resolve_workspace_database(payload)
    if failure is not None:
        return failure, failure_status

    if ";" in sql[:-1]:
        return (
            _failed_payload(
                sql=sql,
                error="Only single SELECT/WITH statements are allowed.",
                error_code="MULTI_STATEMENT_NOT_ALLOWED",
            ),
            400,
        )

    guard = SQLGuard(workspace_database=workspace_database)
    is_valid, error_msg, clean_sql = guard.validate_and_sanitize(sql)
    if not is_valid:
        cross_db = error_msg.startswith("database_mismatch") or error_msg.startswith("cross_db_violation")
        return (
            _failed_payload(
                sql=clean_sql,
                error=error_msg,
                error_code=(
                    "CROSS_DB_VIOLATION" if cross_db else "SQL_VALIDATION_FAILED"
                ),
            ),
            403 if cross_db else 400,
        )

    result = get_clickhouse_executor().execute_query(
        clean_sql,
        workspace_database=workspace_database,
    )
    if not result.get("success"):
        result_error_code = str(result.get("error_code") or "").upper()
        if result_error_code == "CROSS_DB_VIOLATION":
            return (
                _failed_payload(
                    sql=clean_sql,
                    error=result.get("error", "cross_db_violation"),
                    error_code="CROSS_DB_VIOLATION",
                ),
                403,
            )
        return (
            _failed_payload(
                sql=clean_sql,
                error=result.get("error", "query_failed"),
                error_code="QUERY_EXECUTION_FAILED",
            ),
            502,
        )

    rows = sanitize_query_results(result.get("rows", []))
    row_count = int(result.get("row_count", len(rows)) or 0)
    return (
        {
            "status": "success",
            "sql": clean_sql,
            "rows": rows,
            "columns": result.get("columns", []),
            "column_types": result.get("column_types", []) or [],
            "row_count": row_count,
            "scanned_rows": result.get("scanned_rows"),
            "output_bytes": result.get("output_bytes"),
            "empty_result": row_count == 0,
            "execution_time_ms": int(result.get("execution_time_ms", 0) or 0),
            "aborted_due_to_timeout": bool(result.get("aborted_due_to_timeout", False)),
            "settings_applied": dict(result.get("settings_applied") or {}),
            "sql_hash": result.get("sql_hash"),
            "error": None,
            "error_code": None,
            "error_message": None,
            "workspace_database": workspace_database,
        },
        200,
    )

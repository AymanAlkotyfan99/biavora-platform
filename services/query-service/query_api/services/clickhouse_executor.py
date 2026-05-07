"""
ClickHouse Executor

Executes validated SQL queries on ClickHouse.
Returns results for visualization.

Phase 7 / CRIT-05: ``execute_query`` now accepts a ``workspace_database``
kwarg so the per-tenant ClickHouse database resolved by the views drives
``normalize_sql_table_references`` instead of the global default. The legacy
fall-back to ``self.database`` (which used to silently route to ``etl``) is
retained only for the diagnostic helpers (``test_connection``,
``get_tables``, ``get_table_schema``).

Phase 8 — Query Execution Metadata:
* The compiler-emitted ``/* ch_settings: max_execution_time=..., max_memory_usage=...,
  max_result_rows=... */`` header is parsed here and forwarded to the
  ClickHouse driver as per-query ``settings``.
* Hard caps from the environment (``CLICKHOUSE_MAX_EXECUTION_TIME``,
  ``CLICKHOUSE_MAX_MEMORY_USAGE``, ``CLICKHOUSE_MAX_RESULT_ROWS``) are
  applied unconditionally — even when the SQL header is missing.
* ``execute_query`` returns the canonical ``QueryExecutionResult`` shape:
  ``columns``, ``rows``, ``column_types``, ``row_count``, ``scanned_rows``,
  ``output_bytes``, ``execution_time_ms``, ``aborted_due_to_timeout``,
  ``settings_applied``.
"""

import clickhouse_connect
import hashlib
import logging
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from bi_platform_shared.sql import sanitize_sql_for_metabase
from query_api.utils import (
    CrossDatabaseViolationError,
    normalize_sql_table_references,
)

logger = logging.getLogger(__name__)


def hash_sql(sql: str) -> str:
    payload = str(sql or "").encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


# Phase 8: ``compile_sql`` emits a comment of the form
# ``/* ch_settings: key=value, key2=value2 */`` at the top of every query.
# We parse it here, strip it from the SQL we send to ClickHouse (so the
# driver does not try to interpret it as an actual statement), and merge it
# with the operator-level hard caps below.
_CH_SETTINGS_HEADER_RE = re.compile(
    r"^\s*/\*\s*ch_settings\s*:(?P<body>[^*]*)\*/",
    flags=re.IGNORECASE | re.DOTALL,
)


def _parse_ch_settings_header(sql: str) -> Tuple[str, Dict[str, Any]]:
    """Strip and parse the ``/* ch_settings: ... */`` header.

    Returns ``(sql_without_header, parsed_settings)``. Parsed values are
    coerced into integers when they look like integers so the ClickHouse
    driver receives the right Python type for ``max_execution_time`` etc.
    """

    raw_sql = str(sql or "")
    match = _CH_SETTINGS_HEADER_RE.match(raw_sql)
    if not match:
        return raw_sql, {}

    body = match.group("body") or ""
    parsed: Dict[str, Any] = {}
    for fragment in body.split(","):
        fragment = fragment.strip()
        if not fragment or "=" not in fragment:
            continue
        key, _, value = fragment.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        try:
            parsed[key] = int(value)
        except (TypeError, ValueError):
            parsed[key] = value
    stripped = raw_sql[match.end():]
    return stripped, parsed


def _operator_hard_caps() -> Dict[str, int]:
    """Return mandatory per-query ClickHouse caps from the environment."""

    return {
        "max_execution_time": int(os.getenv("CLICKHOUSE_MAX_EXECUTION_TIME", "60") or 60),
        "max_memory_usage": int(
            os.getenv("CLICKHOUSE_MAX_MEMORY_USAGE", str(2 * 1024 * 1024 * 1024)) or (2 * 1024 * 1024 * 1024)
        ),
        "max_result_rows": int(os.getenv("CLICKHOUSE_MAX_RESULT_ROWS", "100000") or 100000),
        # Soft sane defaults that protect the cluster even if the operator
        # does not set them.
        "result_overflow_mode": "break",
        "timeout_overflow_mode": "throw",
    }


_TIMEOUT_HINTS = (
    "timeout exceeded",
    "max_execution_time",
    "query execution timeout",
    "execution time limit exceeded",
)


def _detect_timeout_abort(error_text: str) -> bool:
    if not error_text:
        return False
    lowered = error_text.lower()
    return any(hint in lowered for hint in _TIMEOUT_HINTS)


def _merged_settings(header_settings: Dict[str, Any]) -> Dict[str, Any]:
    """Combine the operator caps with the compiler-emitted settings.

    The compiler-emitted values cannot exceed the operator caps. If the
    header asks for a higher ``max_execution_time`` we silently clamp to
    the operator value — the operator setting is the ceiling.
    """

    effective: Dict[str, Any] = dict(_operator_hard_caps())
    for key, value in (header_settings or {}).items():
        if key in {"max_execution_time", "max_memory_usage", "max_result_rows"}:
            try:
                value_int = int(value)
            except (TypeError, ValueError):
                continue
            cap = int(effective.get(key, value_int))
            effective[key] = max(1, min(value_int, cap))
        else:
            effective[key] = value
    return effective


def _normalize_invalid_casts(sql: str) -> str:
    """
    Global fix: Replace invalid ClickHouse functions with valid ones.
    toFloat64OrNullOrNull / toInt64OrNullOrNull do NOT exist in ClickHouse.
    Applied at execution time so ALL queries (including those bypassing the compiler) are safe.
    """
    if not sql:
        return sql
    sql = sql.replace("toFloat64OrNullOrNull(", "toFloat64OrNull(")
    sql = sql.replace("toInt64OrNullOrNull(", "toInt64OrNull(")
    return sql


def sanitize_sql_for_http(sql: str) -> str:
    """
    Sanitize SQL for ClickHouse HTTP execution.
    
    Removes incompatible syntax:
    - FORMAT Native (not supported via HTTP)
    - Semicolons (causes multi-statement errors)
    - Invalid cast functions (toFloat64OrNullOrNull → toFloat64OrNull)
    - Extra whitespace
    
    Args:
        sql: Raw SQL string (possibly from LLM)
    
    Returns:
        Clean SQL safe for HTTP execution
    """
    if not sql:
        return ""

    original_sql = sql
    # Global fix: normalize invalid ClickHouse cast functions
    sql = _normalize_invalid_casts(sql)

    # Remove FORMAT Native (case-insensitive)
    import re
    clean_sql = re.sub(r'\s+FORMAT\s+Native\s*', ' ', sql, flags=re.IGNORECASE)

    # Normalize trailing semicolons using shared sanitizer.
    if str(clean_sql).strip().endswith(";"):
        logger.warning("Trailing semicolon detected and removed for Metabase compatibility")
    clean_sql = sanitize_sql_for_metabase(clean_sql)

    # Remove extra whitespace and trim
    clean_sql = ' '.join(clean_sql.split())
    clean_sql = clean_sql.strip()
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("SQL sanitization original_sql=%r sanitized_sql=%r", original_sql, clean_sql)

    return clean_sql


def sanitize_numeric_value(value: Any) -> Any:
    """
    🔒 NaN-SAFE: Sanitize a single numeric value to ensure JSON compatibility.
    
    Replaces NaN, Infinity, and -Infinity with 0 (or None for NULL).
    This ensures values can be safely stored in PostgreSQL JSON/JSONB fields
    and serialized to JSON without errors.
    
    Handles all numeric types including:
    - Python float, int
    - Decimal (from ClickHouse Decimal types)
    - numpy.float64, numpy.float32 (if numpy is used)
    - Any other numeric type that can be converted to float
    
    Args:
        value: Any value (numeric, string, None, etc.)
    
    Returns:
        Sanitized value (NaN/Infinity → 0, None → None, other values unchanged)
    """
    # Handle None/NULL
    if value is None:
        return None
    
    # Handle Python int - never NaN/Infinity, return as-is
    if isinstance(value, int):
        return value
    
    # Handle float types (NaN, Infinity) - direct check
    if isinstance(value, float):
        if math.isnan(value):
            return 0  # Replace NaN with 0
        elif math.isinf(value):
            return 0  # Replace Infinity/-Infinity with 0
        return value
    
    # Handle Decimal types (ClickHouse returns Decimal for Decimal/Float64 columns)
    # Decimal types can be converted to float for NaN/Infinity checking
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            # Convert Decimal to float to check for NaN/Infinity
            # Decimal('NaN') and Decimal('Infinity') exist but are rare
            # Converting to float is the safest way to detect them
            try:
                float_val = float(value)
                if math.isnan(float_val):
                    return 0  # Replace NaN with 0
                elif math.isinf(float_val):
                    return 0  # Replace Infinity/-Infinity with 0
                # Return as float for JSON compatibility (Decimal isn't JSON serializable)
                return float_val
            except (ValueError, OverflowError, TypeError):
                # If conversion fails, return 0 as fallback
                return 0
    except ImportError:
        # Decimal not available, skip this check
        pass
    
    # Handle numpy types (if numpy is installed and used by clickhouse-connect)
    try:
        import numpy as np
        if isinstance(value, (np.floating, np.integer)):
            # Convert numpy numeric types to Python float for NaN/Infinity checking
            float_val = float(value)
            if math.isnan(float_val):
                return 0  # Replace NaN with 0
            elif math.isinf(float_val):
                return 0  # Replace Infinity/-Infinity with 0
            # Convert numpy types to Python native types for JSON serialization
            if isinstance(value, np.integer):
                return int(value)
            return float_val
    except (ImportError, ValueError, OverflowError, TypeError):
        # numpy not available or conversion failed, continue to generic check
        pass
    
    # Generic fallback: Try to convert any numeric-like value to float
    # This catches edge cases where ClickHouse returns unusual numeric types
    try:
        # Only attempt conversion if value looks numeric (not strings, lists, etc.)
        if not isinstance(value, (str, bytes, list, dict, tuple, bool)):
            float_val = float(value)
            if math.isnan(float_val):
                return 0  # Replace NaN with 0
            elif math.isinf(float_val):
                return 0  # Replace Infinity/-Infinity with 0
            # If conversion succeeded and no NaN/Infinity, return original value
            # (to preserve type if it's JSON-serializable)
    except (ValueError, TypeError, OverflowError):
        # Conversion failed - value is not numeric, return as-is
        pass
    
    # For non-numeric types (strings, lists, dicts, etc.), return as-is
    return value


def sanitize_query_results(rows: List[Dict]) -> List[Dict]:
    """
    🔒 NaN-SAFE: Sanitize query results to ensure JSON compatibility.
    
    Recursively sanitizes all numeric values in result rows, replacing
    NaN, Infinity, and -Infinity with 0. This ensures results can be:
    - Safely serialized to JSON
    - Stored in PostgreSQL JSON/JSONB fields
    - Sent to frontend/Metabase without errors
    
    Args:
        rows: List of dictionaries representing query result rows
    
    Returns:
        Sanitized list of dictionaries with all NaN/Infinity values replaced
    """
    sanitized_rows = []
    
    for row in rows:
        sanitized_row = {}
        for key, value in row.items():
            # Recursively sanitize nested structures
            if isinstance(value, dict):
                sanitized_row[key] = sanitize_query_results([value])[0] if value else {}
            elif isinstance(value, list):
                sanitized_row[key] = [sanitize_numeric_value(item) for item in value]
            else:
                sanitized_row[key] = sanitize_numeric_value(value)
        sanitized_rows.append(sanitized_row)
    
    return sanitized_rows


class ClickHouseExecutor:
    """
    Execute SELECT queries on ClickHouse using HTTP protocol (port 8123).
    Returns results in format suitable for Metabase/visualization.
    """
    
    def __init__(self):
        """Initialize ClickHouse executor with environment configuration."""
        host = os.getenv('CLICKHOUSE_HOST', 'localhost')
        port_raw = os.getenv('CLICKHOUSE_PORT', '8123')
        username = os.getenv('CLICKHOUSE_USER', 'user_etl')
        password = os.getenv('CLICKHOUSE_PASSWORD', 'etl_pass123')
        database = os.getenv('CLICKHOUSE_DATABASE', 'default')

        try:
            port = int(port_raw)
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid CLICKHOUSE_PORT value: {port_raw!r}. Expected an integer (8123)."
            ) from exc

        # Validate port for HTTP protocol
        if port == 9000:
            logger.warning(
                "CLICKHOUSE_PORT is set to 9000 (native protocol). "
                "HTTP interface requires port 8123. "
                "Update your .env file: CLICKHOUSE_PORT=8123"
            )

        logger.info("Connecting to ClickHouse: %s:%s user=%s", host, port, username)

        try:
            client = clickhouse_connect.get_client(
                host=host,
                port=port,
                username=username,
                password=password,
                database=database
            )
            version_result = client.query("SELECT version()")
            version = (
                version_result.result_rows[0][0]
                if version_result.result_rows and version_result.result_rows[0]
                else "unknown"
            )
            logger.info("ClickHouse connection verified. version=%s database=%s", version, database)
        except Exception as exc:
            error_msg = str(exc)
            logger.error(
                "ClickHouse initialization failed for %s:%s user=%s database=%s: %s",
                host,
                port,
                username,
                database,
                error_msg
            )
            if 'AUTHENTICATION_FAILED' in error_msg or 'Authentication failed' in error_msg:
                raise RuntimeError(
                    "ClickHouse authentication failed. Verify CLICKHOUSE_USER, CLICKHOUSE_PASSWORD, "
                    "and CLICKHOUSE_DATABASE values. "
                    f"Loaded config host={host}, port={port}, user={username}, database={database}. "
                    f"Original error: {error_msg}"
                ) from exc
            raise RuntimeError(
                "ClickHouse connection initialization failed. "
                f"Loaded config host={host}, port={port}, user={username}, database={database}. "
                f"Original error: {error_msg}"
            ) from exc

        self.host = host
        self.port = port
        self.user = username
        self.password = password
        self.database = database
        self.client = client

    def execute_query(self, sql: str, *, workspace_database: Optional[str] = None) -> Dict:
        """
        Execute SQL query on ClickHouse.

        Phase 7 / CRIT-05: the optional ``workspace_database`` kwarg drives
        ``normalize_sql_table_references`` so cross-tenant references can be
        rejected. When the caller does not supply a workspace database we
        fall back to the executor's connection database (``self.database``)
        purely so legacy diagnostic queries (``SELECT 1``, ``SHOW TABLES``)
        keep working.

        Phase 8 — Query Execution Metadata:
        * Parses ``/* ch_settings: ... */`` and merges with operator caps
          (``CLICKHOUSE_MAX_EXECUTION_TIME``, ``CLICKHOUSE_MAX_MEMORY_USAGE``,
          ``CLICKHOUSE_MAX_RESULT_ROWS``); the merged settings are sent to
          the driver as per-query ``settings``.
        * Returns ``column_types``, ``scanned_rows``, ``output_bytes``,
          ``aborted_due_to_timeout`` and ``settings_applied`` so the caller
          can build a complete ``QueryExecutionResult``.

        Args:
            sql: SQL query (must be SELECT only)
            workspace_database: Per-workspace ClickHouse database (preferred).

        Returns:
            dict: ``QueryExecutionResult``-shaped dict containing
                ``success``, ``rows``, ``columns``, ``column_types``,
                ``row_count``, ``scanned_rows``, ``output_bytes``,
                ``execution_time_ms``, ``aborted_due_to_timeout``,
                ``settings_applied`` and ``error`` (on failure).
        """
        try:
            import time
            start_time = time.time()
            query_hash = hash_sql(sql)
            query_length = len(sql or "")
            log_full_sql = str(os.getenv("LOG_FULL_SQL", "false")).strip().lower() == "true"

            # Phase 11 / CRIT-13.7: structured logs never include raw SQL by
            # default. ``LOG_FULL_SQL`` is intentionally only honored at
            # ``DEBUG`` level so production logs see hashes, not SQL bodies.
            if log_full_sql and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Executing SQL query_hash=%s query_length=%s sql=%s",
                    query_hash,
                    query_length,
                    sql,
                )
            else:
                logger.info(
                    "Executing SQL query_hash=%s query_length=%s",
                    query_hash,
                    query_length,
                )

            sql_without_header, header_settings = _parse_ch_settings_header(sql)
            settings_to_apply = _merged_settings(header_settings)

            normalize_target_db = (
                str(workspace_database).strip()
                if workspace_database
                else str(self.database)
            )
            normalized_sql = sql_without_header
            if sql_without_header and sql_without_header.strip().upper().startswith(("SELECT", "WITH")):
                try:
                    normalized_sql = normalize_sql_table_references(sql_without_header, normalize_target_db)
                except CrossDatabaseViolationError as exc:
                    logger.warning(
                        "cross_db_violation query_hash=%s expected_db=%s offending_tables=%s",
                        query_hash,
                        normalize_target_db,
                        exc.offending_tables,
                    )
                    return self._failed_payload(
                        sql_hash=query_hash,
                        error=str(exc),
                        error_code="CROSS_DB_VIOLATION",
                        settings_applied=settings_to_apply,
                    )

            clean_sql = sanitize_sql_for_http(normalized_sql)
            clean_hash = hash_sql(clean_sql)
            clean_length = len(clean_sql or "")
            if log_full_sql and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "SQL normalized query_hash=%s query_length=%s sql=%s settings=%s",
                    clean_hash,
                    clean_length,
                    clean_sql,
                    settings_to_apply,
                )
            else:
                logger.info(
                    "SQL normalized query_hash=%s query_length=%s settings_keys=%s",
                    clean_hash,
                    clean_length,
                    sorted(settings_to_apply.keys()),
                )

            result = self.client.query(clean_sql, settings=settings_to_apply)
            execution_time_ms = int((time.time() - start_time) * 1000)

            rows = []
            columns = list(result.column_names or [])
            column_types = [str(t) for t in (getattr(result, "column_types", None) or [])]

            for row in result.result_rows:
                row_dict: Dict[str, Any] = {}
                for i, col_name in enumerate(columns):
                    row_dict[col_name] = row[i]
                rows.append(row_dict)

            sanitized_rows = sanitize_query_results(rows)

            scanned_rows: Optional[int] = None
            output_bytes: Optional[int] = None
            summary = getattr(result, "summary", None)
            if isinstance(summary, dict):
                # ClickHouse exposes these as strings (``X-ClickHouse-Summary``);
                # we coerce them to int when present.
                read_rows = summary.get("read_rows")
                if read_rows is not None:
                    try:
                        scanned_rows = int(read_rows)
                    except (TypeError, ValueError):
                        scanned_rows = None
                read_bytes = summary.get("read_bytes")
                if read_bytes is not None:
                    try:
                        output_bytes = int(read_bytes)
                    except (TypeError, ValueError):
                        output_bytes = None

            logger.info(
                "Query successful query_hash=%s row_count=%s scanned_rows=%s output_bytes=%s execution_time_ms=%s",
                clean_hash,
                len(sanitized_rows),
                scanned_rows if scanned_rows is not None else "n/a",
                output_bytes if output_bytes is not None else "n/a",
                execution_time_ms,
            )

            return {
                'success': True,
                'rows': sanitized_rows,
                'columns': columns,
                'column_types': column_types,
                'row_count': len(sanitized_rows),
                'scanned_rows': scanned_rows,
                'output_bytes': output_bytes,
                'execution_time_ms': execution_time_ms,
                'aborted_due_to_timeout': False,
                'settings_applied': settings_to_apply,
                'sql_hash': clean_hash,
            }

        except Exception as e:
            error_msg = str(e)
            error_hash = hash_sql(sql)
            timed_out = _detect_timeout_abort(error_msg)
            logger.error(
                "SQL execution failed query_hash=%s query_length=%s error_type=%s aborted_due_to_timeout=%s error=%s",
                error_hash,
                len(sql or ""),
                type(e).__name__,
                timed_out,
                error_msg[:200],
                exc_info=True,
            )

            if 'Port 9000 is for clickhouse-client' in error_msg or 'Connection refused' in error_msg:
                return self._failed_payload(
                    sql_hash=error_hash,
                    error=(
                        'ClickHouse connection error. '
                        'Ensure ClickHouse is running and CLICKHOUSE_PORT=8123 is set in .env file.'
                    ),
                    error_code="CLICKHOUSE_UNREACHABLE",
                    settings_applied=_operator_hard_caps(),
                )

            return self._failed_payload(
                sql_hash=error_hash,
                error=f"Query execution failed: {error_msg[:200]}",
                error_code="QUERY_TIMEOUT" if timed_out else "QUERY_EXECUTION_FAILED",
                settings_applied=_operator_hard_caps(),
                aborted_due_to_timeout=timed_out,
            )

    @staticmethod
    def _failed_payload(
        *,
        sql_hash: str,
        error: str,
        error_code: str,
        settings_applied: Dict[str, Any],
        aborted_due_to_timeout: bool = False,
    ) -> Dict[str, Any]:
        """Return the canonical failure payload shape with full metadata."""

        return {
            'success': False,
            'rows': [],
            'columns': [],
            'column_types': [],
            'row_count': 0,
            'scanned_rows': None,
            'output_bytes': None,
            'execution_time_ms': 0,
            'aborted_due_to_timeout': aborted_due_to_timeout,
            'settings_applied': dict(settings_applied or {}),
            'sql_hash': sql_hash,
            'error': error,
            'error_code': error_code,
        }

    def test_connection(self) -> bool:
        """
        Test ClickHouse connection.
        
        Returns:
            bool: True if connected
        """
        try:
            result = self.execute_query("SELECT 1 as test")
            return result['success']
        except Exception:
            return False
    
    def get_tables(self, database: Optional[str] = None) -> List[str]:
        """
        Get list of tables in database.
        
        Args:
            database: Database name (uses default if not provided)
        
        Returns:
            list: Table names
        """
        db = database or self.database
        sql = f"SHOW TABLES FROM {db}"
        
        result = self.execute_query(sql)
        
        if result['success']:
            return [row['name'] for row in result['rows']]
        return []
    
    def get_table_schema(self, table_name: str, database: Optional[str] = None) -> Dict:
        """
        Get schema for a table.
        
        Args:
            table_name: Table name
            database: Database name
        
        Returns:
            dict: Schema information
        """
        db = database or self.database
        sql = f"DESCRIBE TABLE {db}.{table_name}"
        
        result = self.execute_query(sql)
        
        if result['success']:
            return {
                'columns': result['rows'],
                'column_names': [row['name'] for row in result['rows']],
                'column_types': {row['name']: row['type'] for row in result['rows']}
            }
        
        return {}


# Singleton instance
_clickhouse_executor = None

def get_clickhouse_executor() -> ClickHouseExecutor:
    """Get or create ClickHouse executor singleton."""
    global _clickhouse_executor
    if _clickhouse_executor is None:
        _clickhouse_executor = ClickHouseExecutor()
    return _clickhouse_executor


import logging
import os
import re
import time
from typing import Any

import clickhouse_connect

from shared.dataset_binding import DatasetBindingError, normalize_dataset_context, validate_dataset_context
from shared.pipeline_guards import dataset_scope_guard, is_technical_column_name
from shared.schema_utils import is_date_type, is_dimension_type, is_numeric_type, unqualify_table_name
from shared.schema_filtering import filter_business_schema

logger = logging.getLogger(__name__)

_SCHEMA_CACHE: dict[str, list[dict[str, Any]]] | None = None
_SCHEMA_CACHE_AT = 0.0
SCHEMA_CACHE_TTL_SECONDS = int(os.getenv("SCHEMA_CACHE_TTL_SECONDS", "60"))


def sanitize_sql_for_http(sql: str) -> str:
    if not sql:
        return ""
    clean_sql = re.sub(r"\s+FORMAT\s+Native\s*", " ", sql, flags=re.IGNORECASE)
    clean_sql = clean_sql.replace(";", "")
    clean_sql = " ".join(clean_sql.split())
    return clean_sql.strip()


def get_query_clickhouse_client():
    host = os.getenv("CLICKHOUSE_HOST", "localhost")
    port = int(os.getenv("CLICKHOUSE_PORT", "8123"))
    username = os.getenv("CLICKHOUSE_USER", "etl_user")
    password = os.getenv("CLICKHOUSE_PASSWORD", "etl_pass123")
    database = os.getenv("CLICKHOUSE_DATABASE", "etl")

    logger.info("Connecting to ClickHouse for schema read: %s:%s db=%s", host, port, database)

    try:
        return clickhouse_connect.get_client(
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
        )
    except Exception as exc:
        raise RuntimeError(
            f"ClickHouse connection error (schema read): host={host}, port={port}, db={database}. {exc}"
        ) from exc


def _classify_column(column: str, col_type: str) -> dict[str, Any]:
    technical = is_technical_column_name(column)
    return {
        "name": column,
        "type": col_type,
        "is_numeric": (not technical) and is_numeric_type(col_type),
        "is_date": (not technical) and is_date_type(col_type),
        "is_dimension": (not technical) and is_dimension_type(col_type),
        "column_role": "technical" if technical else "business",
    }


def _fetch_schema_from_clickhouse() -> dict[str, list[dict[str, Any]]]:
    client = get_query_clickhouse_client()

    schema_query = """
        SELECT table, name, type
        FROM system.columns
        WHERE database = currentDatabase()
        ORDER BY table, position;
    """
    clean_query = sanitize_sql_for_http(schema_query)

    try:
        result = client.query(clean_query)
    except Exception as exc:
        raise RuntimeError(f"ClickHouse schema query failed: {exc}") from exc

    schema: dict[str, list[dict[str, Any]]] = {}
    for table, column, col_type in result.result_rows:
        normalized_table = unqualify_table_name(str(table))
        schema.setdefault(normalized_table, []).append(_classify_column(column, col_type))

    if not schema:
        raise RuntimeError("No tables found in current ClickHouse database")
    filtered_schema, _ = filter_business_schema(schema)
    return filtered_schema or schema


def get_schema(
    *,
    force_refresh: bool = False,
    dataset_scope: dict[str, Any] | None = None,
    selected_table: str = "",
    strict_scope: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    global _SCHEMA_CACHE, _SCHEMA_CACHE_AT

    now = time.time()
    cache_valid = (
        not force_refresh
        and _SCHEMA_CACHE is not None
        and (now - _SCHEMA_CACHE_AT) < SCHEMA_CACHE_TTL_SECONDS
    )
    if cache_valid:
        base_schema = _SCHEMA_CACHE
        if dataset_scope or selected_table:
            scoped_schema, _ = dataset_scope_guard(
                schema=base_schema,
                dataset_scope=dataset_scope,
                selected_table=selected_table,
                strict=strict_scope,
            )
            return scoped_schema
        return base_schema

    schema = _fetch_schema_from_clickhouse()
    _SCHEMA_CACHE = schema
    _SCHEMA_CACHE_AT = now
    if dataset_scope or selected_table:
        scoped_schema, _ = dataset_scope_guard(
            schema=schema,
            dataset_scope=dataset_scope,
            selected_table=selected_table,
            strict=strict_scope,
        )
        return scoped_schema
    return schema


def get_schema_for_dataset(
    *,
    workspace_id: str,
    dataset_id: str,
    manager_id: str,
    table_name: str,
    source_id: str = "",
    report_id: str = "",
    force_refresh: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    dataset_context = validate_dataset_context(
        normalize_dataset_context(
            {
                "workspace_id": workspace_id,
                "dataset_id": dataset_id,
                "manager_id": manager_id,
                "table_name": table_name,
                "source_id": source_id,
                "report_id": report_id,
            }
        )
    )
    schema = get_schema(
        force_refresh=force_refresh,
        dataset_scope=dataset_context,
        selected_table=dataset_context.get("table_name", ""),
        strict_scope=True,
    )
    if len(schema) != 1:
        bound = str(dataset_context.get("table_name", "")).strip()
        suffix = bound.split(".")[-1].lower() if bound else ""
        narrowed: dict[str, list[dict[str, Any]]] = {}
        if suffix:
            for table_name, columns in schema.items():
                if str(table_name).strip().split(".")[-1].lower() == suffix:
                    narrowed[str(table_name)] = columns
                    break
        if len(narrowed) == 1:
            return narrowed
        keys = list(schema.keys())[:25]
        raise DatasetBindingError(
            "Dataset-table mismatch: invalid ETL binding "
            f"(expected exactly one scoped table for dataset_id={dataset_context.get('dataset_id')!r} "
            f"table_name={bound!r}; got {len(schema)} tables: {keys!r})"
        )
    return schema


def is_question_matching_schema(question: str, schema: dict[str, list[dict[str, Any]]]) -> bool:
    question_lower = question.lower()
    tokens = set()

    for table, columns in schema.items():
        tokens.add(table.split(".")[-1].lower())
        for col in columns:
            col_name = col["name"].lower()
            tokens.add(col_name)
            tokens.add(col_name.replace("_", " "))

    return any(token in question_lower for token in tokens)

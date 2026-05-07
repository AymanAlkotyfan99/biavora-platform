"""Schema loader (Phase 13 / GAP-01).

Phase 13 changes:

* Schema cache is keyed by ``(database, user_id, dataset_scope)`` and
  carries a TTL (existing) AND a fingerprint (new). The fingerprint is a
  SHA-256 prefix of ``(table, column, type)`` triples so callers can
  detect drift even if the TTL has not yet expired.
* New ``invalidate_schema_cache`` and ``invalidate_all_schema_caches``
  helpers let downstream services (ETL, schema-refresh endpoint) drop
  a stale schema explicitly without restarting the service.
* ``schema_fingerprint`` is exposed publicly so the trace can carry it
  via ``schema_provenance``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import clickhouse_connect

from preprocessing_high.error_handler import (
    PreprocessHighInputError,
    PreprocessHighSchemaLoadError,
)
from preprocessing_high.schemas import HighPreprocessConfig, UserSchema
from shared.dataset_binding import (
    has_complete_dataset_context,
    normalize_dataset_context,
    validate_dataset_context,
)
from shared.pipeline_guards import dataset_scope_guard, is_technical_column_name
from shared.schema_filtering import filter_business_schema
from shared.schema_utils import is_date_type, unqualify_table_name


_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SCHEMA_CACHE: dict[str, tuple[float, "LoadedUserSchema"]] = {}
_SCHEMA_CACHE_LOCK = threading.Lock()


def schema_fingerprint(schema: UserSchema) -> str:
    """Return a deterministic SHA-256 prefix of the schema content.

    Phase 13 / GAP-01: the fingerprint lets the trace prove which schema
    version produced an answer. Two services that load schemas at slightly
    different times can compare fingerprints to detect drift.
    """

    digest = hashlib.sha256()
    for table in sorted(schema.get("tables", [])):
        digest.update(table.encode("utf-8"))
        digest.update(b"\0")
        for column in sorted(schema.get("columns", {}).get(table, []), key=lambda c: str(c.get("name", ""))):
            digest.update(str(column.get("name", "")).encode("utf-8"))
            digest.update(b"|")
            digest.update(str(column.get("type", "")).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()[:32]


def invalidate_schema_cache(*, user_id: str, database: Optional[str] = None) -> int:
    """Invalidate every cached schema for a user (and optional database).

    Returns the number of cache entries dropped. Phase 13 / GAP-01.
    """

    sanitized_user = _sanitize_user_id(user_id)
    database_prefix = f"{database}:" if database else ""
    expected_user_token = f":{sanitized_user}:"
    dropped = 0
    with _SCHEMA_CACHE_LOCK:
        for key in list(_SCHEMA_CACHE.keys()):
            if database_prefix and not key.startswith(database_prefix):
                continue
            if expected_user_token not in f":{key}:":
                continue
            del _SCHEMA_CACHE[key]
            dropped += 1
    return dropped


def invalidate_all_schema_caches() -> int:
    """Drop every cached schema. Returns the number of entries dropped."""

    with _SCHEMA_CACHE_LOCK:
        dropped = len(_SCHEMA_CACHE)
        _SCHEMA_CACHE.clear()
    return dropped


@dataclass(frozen=True)
class ColumnReference:
    table: str
    name: str
    type: str


@dataclass(frozen=True)
class LoadedUserSchema:
    user_id: str
    database: str
    schema: UserSchema
    columns_by_name: dict[str, list[ColumnReference]]
    date_columns_by_name: dict[str, list[ColumnReference]]

    def total_columns(self) -> int:
        return sum(len(cols) for cols in self.schema["columns"].values())


def _sanitize_user_id(user_id: str) -> str:
    if user_id is None:
        raise PreprocessHighInputError("user_id is required.")

    normalized = str(user_id).strip()
    if not normalized:
        raise PreprocessHighInputError("user_id is empty.")

    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", normalized)
    if not sanitized:
        raise PreprocessHighInputError("user_id is invalid after sanitization.")
    return sanitized


def _ensure_safe_identifier(identifier: str, *, field_name: str) -> str:
    if not identifier or not _SAFE_IDENTIFIER_PATTERN.fullmatch(identifier):
        raise PreprocessHighSchemaLoadError(
            f"{field_name} contains unsafe characters and cannot be used in ClickHouse query."
        )
    return identifier


def _resolve_database_name(user_id: str, config: HighPreprocessConfig) -> str:
    if config.user_database_template:
        try:
            database_name = config.user_database_template.format(user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            raise PreprocessHighSchemaLoadError(
                "PREPROCESS_HIGH_DATABASE_TEMPLATE is invalid."
            ) from exc
    else:
        database_name = config.clickhouse_default_database

    return _ensure_safe_identifier(database_name, field_name="database")


def _cache_key(user_id: str, database: str) -> str:
    return f"{database}:{user_id}"


def _build_clickhouse_client(config: HighPreprocessConfig, *, database: str):
    try:
        return clickhouse_connect.get_client(
            host=config.clickhouse_host,
            port=config.clickhouse_port,
            username=config.clickhouse_user,
            password=config.clickhouse_password,
            database=database,
        )
    except Exception as exc:  # noqa: BLE001
        raise PreprocessHighSchemaLoadError(
            "Failed to connect to ClickHouse for schema loading."
        ) from exc


def _fetch_user_schema_rows(
    *,
    config: HighPreprocessConfig,
    database: str,
) -> list[tuple[str, str, str]]:
    client = _build_clickhouse_client(config, database=database)
    query = (
        "SELECT table, name, type "
        "FROM system.columns "
        f"WHERE database = '{database}' "
        "ORDER BY table, position"
    )

    try:
        result = client.query(query)
    except Exception as exc:  # noqa: BLE001
        raise PreprocessHighSchemaLoadError("Failed to query schema from ClickHouse.") from exc

    rows = result.result_rows if hasattr(result, "result_rows") else []
    if not rows:
        raise PreprocessHighSchemaLoadError(
            f"No tables were found for database '{database}'."
        )
    return rows


def _build_loaded_schema(
    *,
    user_id: str,
    database: str,
    rows: list[tuple[str, str, str]],
    dataset_scope: dict[str, object] | None = None,
    strict_scope: bool = True,
) -> LoadedUserSchema:
    raw_columns: dict[str, list[dict[str, str]]] = {}
    for table_raw, column_raw, col_type_raw in rows:
        table_name = unqualify_table_name(str(table_raw))
        column_name = str(column_raw)
        column_type = str(col_type_raw)
        role = "technical" if is_technical_column_name(column_name) else "business"
        raw_columns.setdefault(table_name, []).append({"name": column_name, "type": column_type, "column_role": role})

    filtered_columns, _ = filter_business_schema(raw_columns)
    candidate_columns = filtered_columns if filtered_columns else raw_columns
    columns: dict[str, list[dict[str, str]]] = {}
    for table_name, table_columns in candidate_columns.items():
        business_columns = [
            column
            for column in table_columns
            if not is_technical_column_name(str(column.get("name", "")))
        ]
        if business_columns:
            columns[table_name] = business_columns

    if not columns:
        columns = candidate_columns

    normalized_scope = normalize_dataset_context(dataset_scope)
    if strict_scope and has_complete_dataset_context(normalized_scope):
        validated_scope = validate_dataset_context(normalized_scope)
    else:
        validated_scope = normalized_scope
    scoped_columns, _ = dataset_scope_guard(
        schema=columns,
        dataset_scope=validated_scope,
        selected_table=validated_scope.get("table_name", ""),
        strict=bool(strict_scope and has_complete_dataset_context(validated_scope)),
    )
    columns = scoped_columns
    tables = sorted(columns.keys())

    columns_by_name: dict[str, list[ColumnReference]] = {}
    date_columns_by_name: dict[str, list[ColumnReference]] = {}
    for table_name, table_columns in columns.items():
        for column in table_columns:
            column_name = str(column.get("name", "")).strip()
            column_type = str(column.get("type", "")).strip()
            if not column_name:
                continue

            reference = ColumnReference(table=table_name, name=column_name, type=column_type)
            columns_by_name.setdefault(column_name.lower(), []).append(reference)
            if is_date_type(column_type):
                date_columns_by_name.setdefault(column_name.lower(), []).append(reference)

    schema: UserSchema = {"tables": tables, "columns": columns}
    return LoadedUserSchema(
        user_id=user_id,
        database=database,
        schema=schema,
        columns_by_name=columns_by_name,
        date_columns_by_name=date_columns_by_name,
    )


def load_user_schema(
    *,
    user_id: str,
    config: HighPreprocessConfig,
    logger: logging.Logger,
    log_event: Callable[..., None],
    dataset_scope: dict[str, object] | None = None,
) -> LoadedUserSchema:
    sanitized_user_id = _sanitize_user_id(user_id)
    database = _resolve_database_name(sanitized_user_id, config)
    normalized_scope = normalize_dataset_context(dataset_scope)
    enforce_strict_scope = has_complete_dataset_context(normalized_scope)
    validated_scope = validate_dataset_context(normalized_scope) if enforce_strict_scope else normalized_scope
    scope_key = "|".join(
        sorted(
            f"{key}={value}"
            for key, value in validated_scope.items()
            if str(value).strip()
        )
    )
    key = f"{_cache_key(sanitized_user_id, database)}:{scope_key}"
    now = time.time()

    if config.schema_cache_ttl_seconds > 0:
        with _SCHEMA_CACHE_LOCK:
            cached = _SCHEMA_CACHE.get(key)
            if cached and (now - cached[0]) < config.schema_cache_ttl_seconds:
                log_event(
                    logger,
                    logging.INFO,
                    "Using cached schema for high preprocessing",
                    user_id=sanitized_user_id,
                    database=database,
                    table_count=len(cached[1].schema["tables"]),
                    column_count=cached[1].total_columns(),
                )
                return cached[1]

    rows = _fetch_user_schema_rows(config=config, database=database)
    loaded = _build_loaded_schema(
        user_id=sanitized_user_id,
        database=database,
        rows=rows,
        dataset_scope=validated_scope,
        strict_scope=enforce_strict_scope,
    )

    if config.schema_cache_ttl_seconds > 0:
        with _SCHEMA_CACHE_LOCK:
            _SCHEMA_CACHE[key] = (now, loaded)

    log_event(
        logger,
        logging.INFO,
        "Loaded user schema for high preprocessing",
        user_id=sanitized_user_id,
        database=database,
        table_count=len(loaded.schema["tables"]),
        column_count=loaded.total_columns(),
    )
    return loaded


def find_column_matches(
    *,
    loaded_schema: LoadedUserSchema,
    column_name: str,
    table_name: str | None = None,
) -> list[ColumnReference]:
    normalized_column = str(column_name or "").strip().lower()
    if not normalized_column:
        return []

    matches = loaded_schema.columns_by_name.get(normalized_column, [])
    if not table_name:
        return matches

    normalized_table = str(table_name).strip().split(".")[-1].lower()
    if not normalized_table:
        return matches

    return [match for match in matches if match.table.lower() == normalized_table]


def get_fallback_derivable_column(loaded_schema: LoadedUserSchema) -> ColumnReference | None:
    for references in loaded_schema.date_columns_by_name.values():
        if references:
            return references[0]
    # Heuristic fallback for datasets that store time keys as String
    # (for example `ds`) but still support time-granularity analytics.
    date_like_tokens = {"date", "day", "week", "month", "quarter", "year", "time", "timestamp"}
    for references in loaded_schema.columns_by_name.values():
        for reference in references:
            column_name = str(reference.name).strip().lower()
            if not column_name:
                continue
            if column_name == "ds":
                return reference
            tokens = set(re.findall(r"[a-z0-9]+", column_name.replace("_", " ")))
            if tokens & date_like_tokens:
                return reference
    return None

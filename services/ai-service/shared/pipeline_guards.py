from __future__ import annotations

import re
from typing import Any


_TECHNICAL_COLUMN_EXACT = {
    "_cleaned_at",
    "_loaded_at",
    "_batch_id",
    "_processed_at",
    "_ingested_at",
    "_updated_at",
    "_created_at",
    "_source_file",
    "_source_table",
    "_lineage_ts",
}

_TECHNICAL_COLUMN_HINTS = (
    "_clean",
    "_load",
    "_batch",
    "_process",
    "_ingest",
    "_lineage",
    "_metadata",
    "_etl",
)


def is_technical_column_name(column_name: str) -> bool:
    normalized = str(column_name or "").strip().lower()
    if not normalized:
        return False
    if normalized in _TECHNICAL_COLUMN_EXACT:
        return True
    if normalized.startswith("_"):
        return True
    return any(hint in normalized for hint in _TECHNICAL_COLUMN_HINTS)


def time_column_validator(*, selected_time_column: str, available_columns: list[str]) -> tuple[bool, str]:
    normalized = str(selected_time_column or "").strip()
    if not normalized:
        return False, "time_column_missing"
    if normalized not in available_columns:
        return False, "time_column_not_in_result"
    if is_technical_column_name(normalized):
        return False, "time_column_is_technical_metadata"
    return True, "time_column_valid"


def forecasting_validator(
    *,
    actual_points: int,
    minimum_points: int,
    spacing_ok: bool,
    spacing_reason: str,
) -> tuple[bool, str]:
    """Validate forecasting input.

    Phase 9 / CRIT-14: failures emit stable, machine-readable codes so the
    orchestrator can render an actionable message. The code prefix is
    appended to the human-readable message after a ``:`` so existing
    consumers that only inspect the human text keep working, while new
    consumers can match on the prefix.
    """

    if actual_points < max(0, minimum_points):
        return False, (
            f"forecast_too_few_points:Insufficient historical data for forecasting "
            f"(have={actual_points}, need={minimum_points})"
        )
    if not spacing_ok:
        return False, f"forecast_irregular_spacing:{spacing_reason or 'irregular spacing'}"
    return True, "forecasting_input_valid"


def dataset_scope_guard(
    *,
    schema: dict[str, list[dict[str, Any]]],
    dataset_scope: dict[str, Any] | None = None,
    selected_table: str = "",
    candidate_tables: list[str] | None = None,
    strict: bool = False,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    if not isinstance(schema, dict) or not schema:
        return {}, {
            "dataset_scope": dataset_scope or {},
            "selected_table": "",
            "selected_columns": [],
            "time_column_used": "",
            "reason_for_selection": "empty_schema",
            "scoped_table_count": 0,
        }

    scope_payload = dataset_scope if isinstance(dataset_scope, dict) else {}

    explicit_tables: set[str] = set()
    for key in ("table", "table_name", "dataset_table", "source_table"):
        value = str(scope_payload.get(key, "")).strip()
        if value:
            explicit_tables.add(value)

    tables_value = scope_payload.get("tables")
    if isinstance(tables_value, list):
        explicit_tables.update(str(item).strip() for item in tables_value if str(item).strip())

    selected = str(selected_table or "").strip()
    if selected:
        explicit_tables.add(selected)

    for candidate in (candidate_tables or []):
        normalized = str(candidate or "").strip()
        if normalized:
            explicit_tables.add(normalized)

    scope_tokens: set[str] = set()
    for key in ("dataset_id", "source_id", "workspace_id", "report_id"):
        value = str(scope_payload.get(key, "")).strip().lower()
        if value:
            scope_tokens.update(re.findall(r"[a-z0-9]+", value))

    def _matches_table(table_name: str) -> bool:
        normalized = str(table_name).strip()
        if not normalized:
            return False
        plain = normalized.split(".")[-1]
        explicit_plain = {str(tbl).strip().split(".")[-1].lower() for tbl in explicit_tables if str(tbl).strip()}
        explicit_normalized = {str(tbl).strip().lower() for tbl in explicit_tables if str(tbl).strip()}
        if explicit_tables and (
            normalized in explicit_tables
            or plain in explicit_tables
            or normalized.lower() in explicit_normalized
            or plain.lower() in explicit_normalized
            or plain.lower() in explicit_plain
        ):
            return True
        if scope_tokens:
            table_tokens = set(re.findall(r"[a-z0-9]+", plain.lower()))
            if table_tokens and scope_tokens.issubset(table_tokens):
                return True
            if table_tokens and len(scope_tokens & table_tokens) >= 2:
                return True
        return False

    scoped_schema = {
        table_name: columns
        for table_name, columns in schema.items()
        if _matches_table(table_name)
    }

    reason = "scope_filter_applied"
    if not scoped_schema and selected:
        # Align ETL / ClickHouse naming: ``table_name`` may be unqualified or use a
        # different database prefix than ``system.columns`` keys.
        selected_suffix = str(selected).strip().split(".")[-1].lower()
        for table_name, columns in schema.items():
            plain = str(table_name).split(".")[-1].lower()
            if plain == selected_suffix:
                scoped_schema = {table_name: columns}
                reason = "selected_table_suffix_fallback"
                break

    if not scoped_schema and strict:
        sample = sorted({str(t).split(".")[-1] for t in schema.keys()})[:40]
        raise ValueError(
            "Dataset-table mismatch: invalid ETL binding "
            f"(strict scope: no tables matched dataset_scope; "
            f"explicit_tables={sorted(explicit_tables)!r}; "
            f"selected_table={selected!r}; "
            f"clickhouse_table_suffixes_sample={sample!r})"
        )

    if not scoped_schema:
        sorted_tables = sorted(schema.keys())
        scoped_schema = {sorted_tables[0]: schema[sorted_tables[0]]}
        reason = "single_table_fallback_ranked"

    return scoped_schema, {
        "dataset_scope": scope_payload,
        "selected_table": next(iter(scoped_schema.keys()), ""),
        "selected_columns": [],
        "time_column_used": "",
        "reason_for_selection": reason,
        "scoped_table_count": len(scoped_schema),
        "scoped_tables": list(scoped_schema.keys()),
    }

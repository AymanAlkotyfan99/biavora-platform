from __future__ import annotations

from typing import Any


class DatasetBindingError(ValueError):
    pass


def normalize_identifier(value: object) -> str:
    """Strip whitespace and common SQL/ClickHouse quoting from identifiers."""

    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text.strip("`[]")


def normalize_dataset_context(payload: dict[str, Any] | None) -> dict[str, str]:
    source = payload if isinstance(payload, dict) else {}
    context = {
        "workspace_id": normalize_identifier(source.get("workspace_id", "")),
        "dataset_id": normalize_identifier(source.get("dataset_id", ""))
        or normalize_identifier(source.get("source_id", "")),
        "manager_id": normalize_identifier(source.get("manager_id", ""))
        or normalize_identifier(source.get("user_id", "")),
        "table_name": normalize_identifier(source.get("table_name", ""))
        or normalize_identifier(source.get("dataset_table", "")),
        "source_id": normalize_identifier(source.get("source_id", "")),
        "report_id": normalize_identifier(source.get("report_id", "")),
    }
    return context


def validate_dataset_context(context: dict[str, str]) -> dict[str, str]:
    required = ("workspace_id", "dataset_id", "manager_id", "table_name")
    missing = [field for field in required if not str(context.get(field, "")).strip()]
    if missing:
        raise DatasetBindingError(
            f"Dataset binding context is missing required fields: {', '.join(missing)}"
        )
    return context


def has_complete_dataset_context(context: dict[str, str] | None) -> bool:
    payload = context if isinstance(context, dict) else {}
    required = ("workspace_id", "dataset_id", "manager_id", "table_name")
    return all(str(payload.get(field, "")).strip() for field in required)

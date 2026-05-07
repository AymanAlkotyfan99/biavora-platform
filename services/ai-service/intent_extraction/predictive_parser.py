"""Deterministic predictive intent parser (Phase 5 / CRIT-14).

Phase 5 of the audit requires that forecasting intents NEVER bypass schema
validation: missing time/target columns must surface explicit, machine-readable
error codes (``forecast_missing_time_column`` /
``forecast_missing_target_column``) instead of throwing a generic ``ValueError``
that the orchestrator could only render as "unknown error".

The ``PredictiveSchemaError`` exception below carries that error code so the
orchestrator and the API layer can present a precise, actionable message to
the user.
"""

from __future__ import annotations

import re
from typing import Any

from shared.pipeline_guards import is_technical_column_name
from shared.schema_utils import is_date_type, is_numeric_type


class PredictiveSchemaError(ValueError):
    """Raised when a predictive question cannot be bound to schema columns.

    Phase 5 / CRIT-14: every predictive failure exposes a stable ``code`` so
    downstream consumers (preprocessing-high, orchestration, API) can branch
    deterministically and present a precise message to the user.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code or "").strip() or "predictive_schema_error"


FORECAST_MISSING_TIME_COLUMN = "forecast_missing_time_column"
FORECAST_MISSING_TARGET_COLUMN = "forecast_missing_target_column"


# Phase 9: pattern recognises ``next N day(s)|week(s)|month(s)|quarter(s)|year(s)``
# (and the ``for the next N ...`` / ``in N ...`` variants). Quarters are
# normalised to days downstream (1 quarter = 90 days) so the forecast grain
# is uniformly ``day``.
_HORIZON_PATTERN = re.compile(
    r"\b(?:next|for the next|in|over the next)\s+"
    r"(\d+)\s+"
    r"(day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
    flags=re.IGNORECASE,
)

_TIME_NAME_PRIORITY = (
    "ds",
    "date",
    "datetime",
    "timestamp",
    "order_date",
    "event_date",
    "created_at",
    "updated_at",
    "sales_date",
    "time",
)

_METADATA_TIME_EXACT = {
    "_extracted_at",
    "_loaded_at",
    "_processed_at",
    "_ingested_at",
    "_updated_at",
    "_created_at",
}

_METADATA_TIME_HINTS = (
    "_extract",
    "_load",
    "_process",
    "_ingest",
    "_lineage",
    "_pipeline",
    "_metadata",
    "_etl",
)

_TIME_NAME_HINTS = (
    "ds",
    "date",
    "datetime",
    "timestamp",
    "time",
    "_at",
)


def _tokenize(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", str(value or "").lower()))


def _parse_date_like(value: Any) -> bool:
    if value is None:
        return False
    raw = str(value).strip()
    if not raw:
        return False
    patterns = (
        r"^\d{4}-\d{2}-\d{2}$",
        r"^\d{4}/\d{2}/\d{2}$",
        r"^\d{1,2}/\d{1,2}/\d{4}$",
        r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$",
        r"^\d{4}-\d{2}$",
    )
    return any(re.match(pattern, raw) for pattern in patterns)


def _normalize_phrase(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _semantic_role_for_column(column: dict[str, Any]) -> str:
    name = str(column.get("name", "")).strip().lower()
    col_type = str(column.get("type", "")).strip()
    sample = column.get("sample")
    if _is_time_like_column(column) or _parse_date_like(sample):
        return "possible_time_column"
    if is_numeric_type(col_type):
        return "possible_metric_column"
    if any(token in name for token in ("id", "name", "category", "region", "segment")):
        return "possible_dimension_column"
    return "possible_dimension_column"


def _resolve_horizon_and_granularity(query: str) -> tuple[int, str]:
    """Resolve forecast horizon and grain from user phrasing."""

    lowered = str(query or "").lower()
    if "next weekly" in lowered or " weekly" in lowered:
        return 1, "week"
    match = _HORIZON_PATTERN.search(lowered)
    if not match:
        if "next week" in lowered:
            return 1, "week"
        if "next month" in lowered:
            return 1, "month"
        if "next quarter" in lowered:
            return 1, "quarter"
        if "next year" in lowered:
            return 1, "year"
        return 7, "day"

    raw_horizon = max(1, int(match.group(1)))
    unit = match.group(2).lower()
    if unit.startswith("week"):
        return raw_horizon, "week"
    if unit.startswith("month"):
        return raw_horizon, "month"
    if unit.startswith("quarter"):
        return raw_horizon, "quarter"
    if unit.startswith("year"):
        return raw_horizon, "year"
    return raw_horizon, "day"


def _best_table(schema: dict[str, list[dict[str, Any]]], query: str) -> str:
    question_tokens = _tokenize(query)
    best_table = ""
    best_score = -1
    for table_name, columns in schema.items():
        numeric_count = 0
        date_count = 0
        score = 0
        for column in columns:
            name = str(column.get("name", "")).strip()
            col_type = str(column.get("type", "")).strip()
            if is_numeric_type(col_type):
                numeric_count += 1
            if is_date_type(col_type):
                date_count += 1
            score += len(_tokenize(name) & question_tokens) * 3
            sample = column.get("sample")
            if _parse_date_like(sample):
                date_count += 1
        score += numeric_count
        score += date_count * 2
        if score > best_score:
            best_score = score
            best_table = table_name
    if not best_table:
        return sorted(schema.keys())[0]
    return best_table


def _is_time_like_column(column: dict[str, Any]) -> bool:
    col_type = str(column.get("type", "")).strip()
    if is_date_type(col_type):
        return True

    is_date_flag = column.get("is_date")
    if isinstance(is_date_flag, bool) and is_date_flag:
        return True

    name = str(column.get("name", "")).strip().lower()
    if not name:
        return False
    if any(hint in name for hint in _TIME_NAME_HINTS):
        return True
    return _parse_date_like(column.get("sample"))


def _best_time_column(columns: list[dict[str, Any]]) -> str:
    candidates: list[tuple[int, int, str]] = []
    for column in columns:
        name = str(column.get("name", "")).strip()
        if not name or not _is_time_like_column(column):
            continue
        lowered = name.lower()
        if is_technical_column_name(lowered):
            continue
        if lowered in _METADATA_TIME_EXACT:
            continue
        if lowered.startswith("_") and any(hint in lowered for hint in _METADATA_TIME_HINTS):
            continue
        priority_score = 0
        for idx, preferred in enumerate(_TIME_NAME_PRIORITY):
            if lowered == preferred:
                priority_score = len(_TIME_NAME_PRIORITY) + 5 - idx
                break
            if preferred in lowered:
                priority_score = len(_TIME_NAME_PRIORITY) - idx
                break
        if lowered.startswith("_"):
            priority_score -= 3
        candidates.append((priority_score, len(name), name))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _best_metric_column(columns: list[dict[str, Any]], query: str) -> str:
    question_tokens = _tokenize(query)
    best_metric = ""
    best_score = -1
    for column in columns:
        name = str(column.get("name", "")).strip()
        col_type = str(column.get("type", "")).strip()
        if not name or not is_numeric_type(col_type):
            continue
        if is_technical_column_name(name):
            continue
        col_tokens = _tokenize(name)
        score = len(col_tokens & question_tokens) * 4
        normalized_query = _normalize_phrase(query)
        normalized_name = _normalize_phrase(name)
        if normalized_name and normalized_name in normalized_query:
            score += 3
        if "number of orders" in normalized_query and ("order" in normalized_name):
            score += 5
        if "total sales" in normalized_query and any(t in normalized_name for t in ("total sales", "sales", "revenue")):
            score += 5
        if any(hint in name.lower() for hint in ("sales", "revenue", "profit", "amount", "total")):
            score += 2
        if score > best_score:
            best_score = score
            best_metric = name
    if best_metric:
        return best_metric
    for column in columns:
        name = str(column.get("name", "")).strip()
        col_type = str(column.get("type", "")).strip()
        if name and is_numeric_type(col_type):
            if is_technical_column_name(name):
                continue
            return name
    return ""


def parse_predictive_intent(*, query: str, schema: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Bind a predictive question to a schema-aware forecast spec.

    Phase 5 / CRIT-14: predictive routing must always go through schema
    validation. If a date column or a numeric target column cannot be
    resolved we raise :class:`PredictiveSchemaError` with a stable
    ``code`` (``forecast_missing_time_column`` or
    ``forecast_missing_target_column``) so the orchestrator can surface a
    precise, user-facing failure instead of an opaque "unknown error".
    """

    if not schema:
        raise PredictiveSchemaError(
            FORECAST_MISSING_TIME_COLUMN,
            "Cannot run a forecast: the dataset schema is empty.",
        )

    table = _best_table(schema, query)
    columns = [dict(col) for col in schema.get(table, [])]
    for col in columns:
        col["inferred_role"] = _semantic_role_for_column(col)
    time_column = _best_time_column(columns)
    metric = _best_metric_column(columns, query)
    horizon, granularity = _resolve_horizon_and_granularity(query)

    if not time_column:
        raise PredictiveSchemaError(
            FORECAST_MISSING_TIME_COLUMN,
            (
                "Forecasting requires a Date/DateTime column, but the selected dataset "
                f"'{table}' does not expose one. Add a time column or remove the forecast "
                "request to continue."
            ),
        )
    if not metric:
        raise PredictiveSchemaError(
            FORECAST_MISSING_TARGET_COLUMN,
            (
                "Forecasting requires a numeric target column (e.g., revenue, sales, count), "
                f"but the selected dataset '{table}' does not expose one."
            ),
        )

    return {
        "intent_type": "predictive",
        "intent": "forecast",
        "metrics": [metric],
        "metric_specs": [{"column": metric, "aggregation": "SUM", "alias": "value"}],
        "dimensions": [time_column],
        "filters": [],
        "time_range": "all_time",
        "aggregation": "SUM",
        "target_column": metric,
        "table": table,
        "order_by": [{"column": time_column, "direction": "ASC"}],
        "limit": None,
        "ranking": {"direction": None, "requested": False, "source": "predictive_parser"},
        "operations": ["projection", "forecasting"],
        "ambiguities": [],
        "metric": metric,
        "time_column": time_column,
        "forecast_date_column": time_column,
        "forecast_target_column": metric,
        "forecast_horizon": horizon,
        "horizon": horizon,
        "granularity": granularity,
        "time_grain": granularity,
        "time_granularity": granularity,
        "question_type": "predictive",
        "requires_forecast": True,
        "candidate_tables_scored": [
            {
                "table": tbl,
                "columns": [
                    {
                        "name": str(col.get("name", "")).strip(),
                        "type": str(col.get("type", "")).strip(),
                        "sample": col.get("sample"),
                        "inferred_role": _semantic_role_for_column(col),
                    }
                    for col in (cols or [])
                ],
            }
            for tbl, cols in schema.items()
        ],
        "selected_table_reason": "table_semantic_score_with_time_and_metric_signals",
        "detected_time_column": time_column,
        "detected_time_column_reason": "name_or_type_or_sample_date_like",
        "detected_value_column": metric,
        "detected_value_column_reason": "numeric_with_question_semantic_match",
        "sample_row_used": {
            str(col.get("name", "")).strip(): col.get("sample")
            for col in columns
            if str(col.get("name", "")).strip()
        },
        "horizon_reason": "parsed_from_next_time_expression_or_default",
        "granularity_reason": "predictive_parser_day_grain_policy",
    }


__all__ = [
    "FORECAST_MISSING_TARGET_COLUMN",
    "FORECAST_MISSING_TIME_COLUMN",
    "PredictiveSchemaError",
    "parse_predictive_intent",
]

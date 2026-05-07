from __future__ import annotations

import logging
import re
from typing import Any

from shared.chart_types import ChartType, normalize_chart_type


logger = logging.getLogger(__name__)

_TIME_TOKENS = ("date", "time", "period", "day", "week", "month", "quarter", "year", "ds")
_GEO_TOKENS = ("lat", "lng", "lon", "longitude", "latitude", "country", "state", "geo")
_SHARE_TOKENS = ("share", "ratio", "percent", "percentage", "contribution", "composition")
_DISTRIBUTION_TOKENS = ("distribution", "histogram", "spread")
_COMBO_TOKENS = ("line + bar", "line and bar", "combo", "mixed")
_STACKED_TOKENS = ("stacked", "stack")
_MAP_TOKENS = ("map", "geospatial", "geo", "location")
_TIME_SERIES_HINT_TOKENS = ("time_series", "time_grouping", "over time", "through time", "across time", "trend")


def _is_numeric_like(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return False
        return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", stripped))
    return False


def _extract_rows_and_columns(dataframe: Any) -> tuple[list[dict[str, Any]], list[Any]]:
    if isinstance(dataframe, dict):
        rows = dataframe.get("rows", [])
        columns = dataframe.get("columns", [])
        if isinstance(rows, list) and isinstance(columns, list):
            return [row for row in rows if isinstance(row, dict)], columns
    if isinstance(dataframe, list):
        rows = [row for row in dataframe if isinstance(row, dict)]
        return rows, list(rows[0].keys()) if rows else []
    return [], []


def _column_name(column: Any) -> str:
    if isinstance(column, dict):
        return str(column.get("name") or "").strip()
    return str(column or "").strip()


def _column_type(column: Any) -> str:
    if isinstance(column, dict):
        return str(column.get("type") or "").strip().lower()
    return ""


def _type_is_numeric(column_type: str) -> bool:
    lowered = str(column_type or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in ("int", "float", "decimal", "numeric", "double"))


def _column_profiles(
    rows: list[dict[str, Any]],
    columns: list[Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    names: list[str] = []
    raw_by_name: dict[str, Any] = {}
    for column in columns:
        name = _column_name(column)
        if not name:
            continue
        names.append(name)
        raw_by_name[name] = column

    if not names and rows:
        names = list(rows[0].keys())

    sample_rows = rows[:25]
    numeric_columns: list[str] = []
    time_columns: list[str] = []
    geo_columns: list[str] = []

    metadata_types = metadata.get("column_types", {}) if isinstance(metadata.get("column_types"), dict) else {}
    for name in names:
        lowered = name.lower()
        raw = raw_by_name.get(name)
        col_type = _column_type(raw)
        meta_type = str(metadata_types.get(name, "")).strip().lower()
        if any(token in lowered for token in _TIME_TOKENS) or meta_type in {"datetime", "date", "timestamp", "time"}:
            time_columns.append(name)
        if any(token in lowered for token in _GEO_TOKENS) or meta_type in {"geo", "geography", "location"}:
            geo_columns.append(name)
        if _type_is_numeric(col_type) or meta_type in {"numeric", "number", "integer", "float"}:
            numeric_columns.append(name)
            continue
        observed = [row.get(name) for row in sample_rows if row.get(name) is not None]
        if observed and all(_is_numeric_like(value) for value in observed):
            numeric_columns.append(name)

    categorical_columns = [name for name in names if name not in numeric_columns]
    return {
        "columns": names,
        "numeric_columns": numeric_columns,
        "time_columns": time_columns,
        "geo_columns": geo_columns,
        "categorical_columns": categorical_columns,
        "row_count": len(rows),
    }


def _intent_text(intent: dict[str, Any], metadata: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("intent", "intent_type", "analysis_mode", "query", "question", "user_intent"):
        value = intent.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip().lower())
    for key in ("query", "question"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip().lower())
    operations = intent.get("operations", [])
    if isinstance(operations, list):
        parts.extend(str(op).strip().lower() for op in operations if str(op).strip())
    return " ".join(parts)


def _metric_alias(metric: object) -> str:
    if isinstance(metric, dict):
        alias = str(metric.get("alias") or metric.get("column") or "").strip()
        if alias:
            return alias
    return str(metric or "").strip()


def _has_combo_intent(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    if any(token in normalized for token in _COMBO_TOKENS):
        return True
    return bool(
        re.search(r"\bline\b.*\bbars?\b", normalized)
        or re.search(r"\bbars?\b.*\bline\b", normalized)
    )


def _result(chart_type: str, confidence: float, reasoning: str, *, variant: str = "") -> dict[str, Any]:
    canonical = normalize_chart_type(chart_type, default=ChartType.TABLE.value)
    return {
        "chart_type": canonical,
        "type": canonical,  # Backward compatibility for old callers/tests.
        "confidence": max(0.0, min(1.0, float(confidence))),
        "reasoning": reasoning,
        "variant": variant,
    }


def recommend_chart(
    dataframe: Any = None,
    intent: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    data: Any = None,
) -> dict[str, Any]:
    """
    Structured chart recommendation engine.

    Backward compatibility:
    - recommend_chart(intent_dict)
    - recommend_chart(intent_dict, data_dict)
    - recommend_chart(dataframe=data, intent=intent, metadata=meta)
    """
    if data is not None and dataframe is None:
        dataframe = data

    if intent is None and isinstance(dataframe, dict) and any(
        key in dataframe for key in ("metrics", "dimensions", "intent", "operations", "analysis_mode")
    ):
        intent = dataframe
        dataframe = None
    elif isinstance(intent, dict) and isinstance(dataframe, dict) and any(
        key in dataframe for key in ("metrics", "dimensions", "intent", "operations", "analysis_mode")
    ) and any(key in intent for key in ("rows", "columns")):
        # Legacy positional style: recommend_chart(intent, data)
        dataframe, intent = intent, dataframe

    intent_payload = intent if isinstance(intent, dict) else {}
    metadata_payload = metadata if isinstance(metadata, dict) else {}
    rows, columns = _extract_rows_and_columns(dataframe)
    profile = _column_profiles(rows=rows, columns=columns, metadata=metadata_payload)

    row_count = profile["row_count"]
    numeric_columns = profile["numeric_columns"]
    time_columns = profile["time_columns"]
    geo_columns = profile["geo_columns"]
    categorical_columns = profile["categorical_columns"]

    metrics = intent_payload.get("metrics", []) if isinstance(intent_payload.get("metrics"), list) else []
    dimensions = intent_payload.get("dimensions", []) if isinstance(intent_payload.get("dimensions"), list) else []
    metric_names = [_metric_alias(metric) for metric in metrics if _metric_alias(metric)]
    breakout = metadata_payload.get("breakout") if isinstance(metadata_payload.get("breakout"), list) else []
    if not breakout:
        breakout = intent_payload.get("breakout") if isinstance(intent_payload.get("breakout"), list) else []
    breakout = [str(item).strip() for item in breakout if str(item).strip()]

    text = _intent_text(intent_payload, metadata_payload)
    has_share_intent = any(token in text for token in _SHARE_TOKENS)
    has_distribution_intent = any(token in text for token in _DISTRIBUTION_TOKENS)
    has_combo_intent = _has_combo_intent(text)
    has_stacked_intent = any(token in text for token in _STACKED_TOKENS)
    has_map_intent = any(token in text for token in _MAP_TOKENS)
    has_time_series_intent = any(token in text for token in _TIME_SERIES_HINT_TOKENS)

    if row_count == 0 and not profile["columns"]:
        if has_map_intent:
            return _result(ChartType.MAP.value, 0.62, "intent-only geospatial request")
        if "correlation" in text or "relationship" in text:
            return _result(ChartType.SCATTER.value, 0.72, "intent-only relationship request")
        if has_time_series_intent:
            if len(metrics) >= 2:
                return _result(ChartType.LINE_MULTI.value, 0.71, "intent-only time series multi metric")
            return _result(ChartType.LINE.value, 0.71, "intent-only time series request")
        if has_distribution_intent:
            return _result(ChartType.HISTOGRAM.value, 0.7, "intent-only distribution request")
        if len(metrics) >= 2 and dimensions:
            return _result(ChartType.BAR_GROUPED.value, 0.68, "intent-only category multi metric")
        if len(metrics) >= 1 and dimensions:
            return _result(ChartType.BAR.value, 0.68, "intent-only category metric")
        if len(metrics) == 1 and not dimensions:
            return _result(ChartType.CARD.value, 0.68, "intent-only single metric")
        return _result(ChartType.TABLE.value, 0.45, "empty dataset fallback")

    if row_count == 1 and len(profile["columns"]) == 1:
        return _result(ChartType.CARD.value, 0.97, "single scalar value")
    if row_count == 0:
        return _result(ChartType.TABLE.value, 0.45, "empty dataset fallback")

    metric_count = len(metric_names) if metric_names else len(numeric_columns)
    has_time = bool(time_columns)
    has_geo = bool(geo_columns)
    has_category = bool(categorical_columns)
    has_breakout = bool(breakout)

    # 1) Geo
    if has_geo and (has_map_intent or any(token in " ".join(profile["columns"]).lower() for token in ("lat", "lng", "longitude", "latitude", "country"))):
        return _result(ChartType.MAP.value, 0.94, "geo columns detected")

    # 2) Percentage/share/ratio
    if has_share_intent and has_category and metric_count >= 1:
        return _result(ChartType.PIE.value, 0.9, "percentage/share intent with category metric")

    # 3) Combo
    if has_time and metric_count >= 2 and has_combo_intent:
        return _result(ChartType.COMBO_LINE_BAR.value, 0.89, "time series with dual-role metrics")

    # 4) Stacked intent
    if has_stacked_intent and metric_count >= 1 and (has_category or has_time):
        return _result(ChartType.BAR_STACKED.value, 0.89, "explicit stacked intent")

    # 5) Distribution
    if has_distribution_intent and metric_count >= 1:
        return _result(ChartType.HISTOGRAM.value, 0.9, "distribution requires histogram")

    # 6) Time series
    if has_time and (metric_count >= 2 or has_breakout):
        return _result(ChartType.LINE_MULTI.value, 0.9, "time column with multiple metrics/series")
    if has_time and metric_count >= 1:
        return _result(ChartType.LINE.value, 0.9, "time column with single metric")

    # 7) Category-based
    if has_category and has_breakout and metric_count >= 1:
        return _result(ChartType.BAR_STACKED.value, 0.9, "category with breakout series")
    if has_category and metric_count >= 2:
        return _result(ChartType.BAR_GROUPED.value, 0.89, "category with multiple metrics")
    if has_category and metric_count >= 1:
        return _result(ChartType.BAR.value, 0.88, "category with single metric")

    # 8) Numeric-only fallback
    if len(numeric_columns) >= 2:
        if "correlation" in text or "relationship" in text or "comparison" in text:
            return _result(ChartType.SCATTER.value, 0.88, "numeric relationship fallback")
        return _result(ChartType.LINE_MULTI.value, 0.86, "numeric multi-series fallback")
    if len(numeric_columns) == 1 and row_count > 1:
        return _result(ChartType.BAR.value, 0.78, "single numeric variable fallback")
    if len(numeric_columns) == 1 and row_count == 1:
        return _result(ChartType.CARD.value, 0.85, "single numeric point")

    return _result(ChartType.TABLE.value, 0.55, "safe fallback for unsupported shape")

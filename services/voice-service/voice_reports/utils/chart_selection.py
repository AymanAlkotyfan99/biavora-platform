from __future__ import annotations

import re
from typing import Any

from voice_reports.constants import ChartType, normalize_chart_type


_TIME_COLUMN_TOKENS = ("date", "time", "timestamp", "period", "day", "week", "month", "quarter", "year")
_GEO_COLUMN_TOKENS = ("lat", "lng", "lon", "longitude", "latitude", "country", "city", "geo")
_RELATIONSHIP_INTENTS = {"correlation", "relationship"}
_DISTRIBUTION_INTENTS = {"distribution"}
_SHARE_TOKENS = {"share", "ratio", "percent", "percentage", "contribution"}
_COMBO_TOKENS = {"combo", "line + bar", "line and bar", "mixed"}


def _is_numeric_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", value.strip()))
    return False


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


def profile_result_shape(columns: list[Any], rows: list[Any]) -> dict[str, Any]:
    column_specs = [
        (raw_col, _column_name(raw_col))
        for raw_col in (columns or [])
        if _column_name(raw_col)
    ]
    normalized_columns = [name for _, name in column_specs]
    sample_rows = [row for row in (rows or []) if isinstance(row, dict)][:25]
    row_count = len(rows or [])
    numeric_columns: list[str] = []
    time_like_columns: list[str] = []
    geo_columns: list[str] = []

    for raw_column, col in column_specs:
        lowered = col.lower()
        if any(token in lowered for token in _TIME_COLUMN_TOKENS):
            time_like_columns.append(col)
        if any(token in lowered for token in _GEO_COLUMN_TOKENS):
            geo_columns.append(col)
        if _type_is_numeric(_column_type(raw_column)):
            numeric_columns.append(col)
            continue
        observed = [row.get(col) for row in sample_rows if col in row and row.get(col) is not None]
        if observed and all(_is_numeric_like(value) for value in observed):
            numeric_columns.append(col)

    has_category_value_shape = bool(row_count >= 1 and len(numeric_columns) >= 1 and len(normalized_columns) > len(numeric_columns))
    return {
        "row_count": row_count,
        "columns": normalized_columns,
        "numeric_columns": numeric_columns,
        "time_like_columns": time_like_columns,
        "geo_columns": geo_columns,
        "single_value": row_count == 1 and len(normalized_columns) == 1,
        "has_category_value_shape": has_category_value_shape,
    }


def extract_upstream_chart_type(
    *,
    chart_config: dict[str, Any] | None,
    pipeline_trace: dict[str, Any] | None,
) -> str:
    chart_payload = chart_config if isinstance(chart_config, dict) else {}
    trace_payload = pipeline_trace if isinstance(pipeline_trace, dict) else {}

    visualization_stage = trace_payload.get("visualization", {}) if isinstance(trace_payload.get("visualization"), dict) else {}
    final_output = visualization_stage.get("final_output", {}) if isinstance(visualization_stage.get("final_output"), dict) else {}
    for candidate in (
        final_output.get("selected_chart_type"),
        final_output.get("chart_type"),
        (
            final_output.get("visualization_payload_preview", {})
            if isinstance(final_output.get("visualization_payload_preview"), dict)
            else {}
        ).get("chart_type"),
        (
            final_output.get("visualization_payload_preview", {})
            if isinstance(final_output.get("visualization_payload_preview"), dict)
            else {}
        ).get("type"),
        visualization_stage.get("selected_chart_type"),
        visualization_stage.get("chart_type"),
    ):
        normalized = normalize_chart_type(str(candidate or "").strip(), default="")
        if normalized:
            return normalized

    upstream_chart = chart_payload.get("upstream_chart")
    if isinstance(upstream_chart, dict):
        candidate = (
            upstream_chart.get("selected_chart_type")
            or upstream_chart.get("chart_type")
            or upstream_chart.get("type")
        )
        normalized = normalize_chart_type(str(candidate or "").strip(), default="")
        if normalized:
            return normalized
    return ""


def infer_chart_with_reason(
    *,
    columns: list[Any],
    rows: list[Any],
    intent: dict[str, Any] | None,
    preferred_chart_type: str | None = None,
) -> dict[str, str]:
    intent_payload = intent if isinstance(intent, dict) else {}
    intent_name = str(intent_payload.get("intent", "")).strip().lower()
    analysis_mode = str(intent_payload.get("analysis_mode", "")).strip().lower()
    time_grouping_detected = bool(intent_payload.get("time_grouping_detected"))
    operations = {
        str(op).strip().lower()
        for op in (intent_payload.get("operations", []) or [])
        if str(op).strip()
    }
    metric_type = str(
        intent_payload.get("metric_type")
        or (
            intent_payload.get("chart", {}).get("metric_type")
            if isinstance(intent_payload.get("chart"), dict)
            else ""
        )
        or ""
    ).strip().lower()
    shape = profile_result_shape(columns=columns, rows=rows)
    row_count = shape["row_count"]
    numeric_count = len(shape["numeric_columns"])
    time_count = len(shape["time_like_columns"])
    geo_count = len(shape.get("geo_columns", []))
    has_category_value_shape = bool(shape.get("has_category_value_shape"))
    single_value = bool(shape["single_value"])
    dimensions = [
        str(dim).strip()
        for dim in (intent_payload.get("dimensions", []) or [])
        if str(dim).strip()
    ]
    metrics = intent_payload.get("metrics", []) if isinstance(intent_payload.get("metrics"), list) else []
    metric_count = len(metrics) if metrics else numeric_count
    breakout = intent_payload.get("breakout", []) if isinstance(intent_payload.get("breakout"), list) else []
    breakout = [str(item).strip() for item in breakout if str(item).strip()]
    text_blob = " ".join(
        [
            str(intent_payload.get("intent", "")).strip().lower(),
            str(intent_payload.get("analysis_mode", "")).strip().lower(),
            " ".join(str(op).strip().lower() for op in operations if str(op).strip()),
        ]
    )
    has_share_intent = any(token in text_blob for token in _SHARE_TOKENS) or metric_type in {"percentage", "percent", "ratio"}
    has_combo_intent = any(token in text_blob for token in _COMBO_TOKENS)

    if row_count == 0:
        return {"chart_type": ChartType.TABLE.value, "reasoning": "empty_result_set", "variant": ""}

    def _supports(chart_type: str) -> bool:
        normalized = normalize_chart_type(chart_type, default="")
        if not normalized:
            return False
        if normalized == ChartType.CARD.value:
            return single_value
        if normalized in {ChartType.LINE.value, ChartType.LINE_MULTI.value, ChartType.AREA.value}:
            return row_count >= 1 and time_count >= 1 and numeric_count >= 1
        if normalized == ChartType.SCATTER.value:
            return row_count > 1 and numeric_count >= 2 and not has_category_value_shape
        if normalized == ChartType.HISTOGRAM.value:
            return row_count > 1 and numeric_count >= 1 and not has_category_value_shape
        if normalized in {ChartType.BAR.value, ChartType.BAR_GROUPED.value, ChartType.BAR_STACKED.value, ChartType.PIE.value}:
            return row_count >= 1 and has_category_value_shape
        if normalized == ChartType.MAP.value:
            return row_count >= 1 and geo_count >= 1
        if normalized == ChartType.COMBO_LINE_BAR.value:
            return row_count >= 1 and time_count >= 1 and numeric_count >= 2
        if normalized == ChartType.TABLE.value:
            return True
        return False

    relationship_requested = (
        analysis_mode == "relationship"
        or intent_name in _RELATIONSHIP_INTENTS
        or "relationship" in operations
    )
    time_series_requested = (
        intent_name == "time_series"
        or time_grouping_detected
        or "time_grouping" in operations
    )
    distribution_requested = (
        analysis_mode == "distribution"
        or intent_name in _DISTRIBUTION_INTENTS
        or "distribution" in operations
    )
    category_comparison_requested = (
        intent_name in {"comparison", "ranking"}
        or "comparison" in operations
        or "grouping" in operations
    )

    recommended = ""
    reasoning = ""
    variant = ""

    if _supports(ChartType.MAP.value) and geo_count >= 1:
        recommended = ChartType.MAP.value
        reasoning = "geo_shape_detected"
    elif has_share_intent and has_category_value_shape and _supports(ChartType.PIE.value):
        recommended = ChartType.PIE.value
        reasoning = "share_ratio_intent"
    elif relationship_requested and _supports(ChartType.SCATTER.value):
        recommended = ChartType.SCATTER.value
        reasoning = "relationship_numeric_pair"
    elif has_combo_intent and _supports(ChartType.COMBO_LINE_BAR.value):
        recommended = ChartType.COMBO_LINE_BAR.value
        reasoning = "time_dual_metric_combo_intent"
    elif time_series_requested and metric_count >= 2 and _supports(ChartType.LINE_MULTI.value):
        recommended = ChartType.LINE_MULTI.value
        reasoning = "time_with_multiple_metrics"
    elif time_series_requested and _supports(ChartType.LINE.value):
        recommended = ChartType.LINE.value
        reasoning = "time_with_single_metric"
    elif time_count >= 1 and metric_count >= 2 and _supports(ChartType.LINE_MULTI.value):
        recommended = ChartType.LINE_MULTI.value
        reasoning = "time_like_shape_multi_metric"
    elif time_count >= 1 and _supports(ChartType.LINE.value):
        recommended = ChartType.LINE.value
        reasoning = "time_like_shape_single_metric"
    elif distribution_requested and _supports(ChartType.HISTOGRAM.value):
        recommended = ChartType.HISTOGRAM.value
        reasoning = "distribution_numeric_variable"
    elif category_comparison_requested and (breakout or len(dimensions) >= 2) and _supports(ChartType.BAR_STACKED.value):
        recommended = ChartType.BAR_STACKED.value
        reasoning = "category_with_breakout"
        variant = "stacked"
    elif category_comparison_requested and metric_count >= 2 and _supports(ChartType.BAR_GROUPED.value):
        recommended = ChartType.BAR_GROUPED.value
        reasoning = "category_with_multiple_metrics"
        variant = "grouped"
    elif has_category_value_shape and _supports(ChartType.BAR.value):
        recommended = ChartType.BAR.value
        reasoning = "category_with_single_metric"
    elif single_value and _supports(ChartType.CARD.value):
        recommended = ChartType.CARD.value
        reasoning = "single_scalar_value"

    # Preserve upstream chart when valid for the current shape.
    preferred_normalized = normalize_chart_type(preferred_chart_type, default="")
    if preferred_normalized and _supports(preferred_normalized):
        return {
            "chart_type": preferred_normalized,
            "reasoning": "upstream_preserved_validated",
            "variant": variant,
        }

    # Shape rules fallback.
    if not recommended:
        if _supports(ChartType.COMBO_LINE_BAR.value):
            recommended = ChartType.COMBO_LINE_BAR.value
            reasoning = "shape_fallback_time_dual_metric_combo"
        elif _supports(ChartType.LINE_MULTI.value):
            recommended = ChartType.LINE_MULTI.value
            reasoning = "shape_fallback_line_multi"
        elif _supports(ChartType.LINE.value):
            recommended = ChartType.LINE.value
            reasoning = "shape_fallback_line"
        elif _supports(ChartType.SCATTER.value):
            recommended = ChartType.SCATTER.value
            reasoning = "shape_fallback_scatter"
        elif _supports(ChartType.HISTOGRAM.value):
            recommended = ChartType.HISTOGRAM.value
            reasoning = "shape_fallback_histogram"
        elif _supports(ChartType.BAR.value):
            recommended = ChartType.BAR.value
            reasoning = "shape_fallback_bar"
        elif _supports(ChartType.CARD.value):
            recommended = ChartType.CARD.value
            reasoning = "shape_fallback_card"
        else:
            recommended = ChartType.TABLE.value
            reasoning = "safe_fallback_table"

    return {"chart_type": recommended, "reasoning": reasoning or "shape_and_intent_inference", "variant": variant}


def infer_chart_type(
    *,
    columns: list[Any],
    rows: list[Any],
    intent: dict[str, Any] | None,
    preferred_chart_type: str | None = None,
) -> str:
    return infer_chart_with_reason(
        columns=columns,
        rows=rows,
        intent=intent,
        preferred_chart_type=preferred_chart_type,
    ).get("chart_type", ChartType.TABLE.value)

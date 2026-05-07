import os
import re
import time
from typing import Any

from dagster import AssetExecutionContext, asset

from dagster_pipeline import ASSET_RETRY_POLICY, pipeline_failure_hook
from intent_extraction.error_handler import (
    classify_intent_extraction_error,
    decide_intent_extraction_action,
)
from intent_extraction.routing import (
    build_sql_from_intent,
)
from intent_extraction.schemas import IntentExtractionConfig
from shared.pipeline_trace import (
    attach_stage,
    build_pipeline_trace_template,
    finalize_trace,
    make_attempt,
    stage_payload,
    utc_now_iso,
)
from shared.confidence import pipeline_confidence, stage_confidence
from shared.chart_types import ChartType, normalize_chart_type
from shared.chart_contract import build_chart_contract_from_intent, validate_chart_sql_alignment
from shared.llm_chart_selector import recommend_chart_with_gemma
from shared.stage_contract import normalize_stage_status, stage_allows_progress
from shared.sql_review import get_last_query_service_auth_status, review_and_correct_sql


def _extract_result_preview(execution_result: Any, max_rows: int = 5) -> dict[str, Any]:
    if not isinstance(execution_result, dict):
        return {"preview_rows": [], "row_count": 0}

    rows = execution_result.get("rows", [])
    if not isinstance(rows, list):
        rows = []
    preview_rows = rows[:max_rows]
    row_count = execution_result.get("row_count")
    if row_count is None:
        row_count = len(rows)
    return {
        "preview_rows": preview_rows,
        "row_count": int(row_count or 0),
        "columns": execution_result.get("columns", []),
    }


def _single_value_result_shape(execution_result: Any) -> bool:
    if not isinstance(execution_result, dict):
        return False
    rows = execution_result.get("rows", [])
    if not isinstance(rows, list) or len(rows) != 1:
        return False
    first_row = rows[0]
    if not isinstance(first_row, dict):
        return False
    return len(first_row.keys()) == 1


def _is_numeric_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", value.strip()))
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _column_name(column: Any) -> str:
    if isinstance(column, dict):
        return str(column.get("name") or "").strip()
    return str(column or "").strip()


def _column_type(column: Any) -> str:
    if isinstance(column, dict):
        return str(column.get("type") or "").strip().lower()
    return ""


def _column_type_is_numeric(column_type: str) -> bool:
    lowered = str(column_type or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in ("int", "float", "decimal", "numeric", "double"))


def _result_shape_profile(execution_result: Any) -> dict[str, Any]:
    if not isinstance(execution_result, dict):
        return {
            "row_count": 0,
            "columns": [],
            "numeric_columns": [],
            "time_like_columns": [],
            "has_category_value_shape": False,
        }
    rows = execution_result.get("rows", [])
    columns = execution_result.get("columns", [])
    if not isinstance(rows, list):
        rows = []
    if not isinstance(columns, list):
        columns = []
    column_specs = [
        (raw_col, _column_name(raw_col))
        for raw_col in columns
        if _column_name(raw_col)
    ]
    normalized_columns = [name for _, name in column_specs]
    if not rows:
        return {
            "row_count": 0,
            "columns": normalized_columns,
            "numeric_columns": [],
            "time_like_columns": [],
            "has_category_value_shape": False,
        }

    sample_rows = [row for row in rows if isinstance(row, dict)][:25]
    numeric_columns: list[str] = []
    time_like_columns: list[str] = []
    for raw_col, col_name in column_specs:
        if not col_name:
            continue
        lowered = col_name.lower()
        if _column_type_is_numeric(_column_type(raw_col)):
            numeric_columns.append(col_name)
        else:
            observed = [row.get(col_name) for row in sample_rows if col_name in row and row.get(col_name) is not None]
            if observed and all(_is_numeric_value(value) for value in observed):
                numeric_columns.append(col_name)
        if lowered in {"ds", "date", "period", "timestamp", "datetime"} or any(
            token in lowered for token in ("date", "time", "month", "week", "year", "quarter")
        ):
            time_like_columns.append(col_name)

    row_count = int(execution_result.get("row_count") or len(rows))
    has_category_value_shape = bool(
        row_count >= 1
        and len(numeric_columns) >= 1
        and len(normalized_columns) > len(numeric_columns)
    )
    return {
        "row_count": row_count,
        "columns": normalized_columns,
        "numeric_columns": numeric_columns,
        "time_like_columns": time_like_columns,
        "has_category_value_shape": has_category_value_shape,
    }


def _normalize_chart_type(chart_type: str) -> str:
    return normalize_chart_type(chart_type, default="")


def _chart_request_hints(query_text: str) -> dict[str, bool]:
    normalized = str(query_text or "").strip().lower()
    if not normalized:
        return {
            "map": False,
            "pie": False,
            "combo": False,
            "area": False,
            "bar_stacked": False,
            "bar_grouped": False,
            "kpi": False,
        }
    return {
        "map": bool(re.search(r"\b(map|geo|geographic|location|region by map)\b", normalized)),
        "pie": bool(re.search(r"\b(pie|donut|share|percentage|composition|proportion)\b", normalized)),
        "combo": bool(
            re.search(r"\b(combo|line\s*\+\s*bar|line and bar|bars and line|mixed chart)\b", normalized)
        ),
        "area": bool(re.search(r"\b(area|area chart)\b", normalized)),
        "bar_stacked": bool(re.search(r"\b(stacked|stack)\b", normalized)),
        "bar_grouped": bool(re.search(r"\b(grouped|group by series|clustered)\b", normalized)),
        "kpi": bool(re.search(r"\b(kpi|single number|single value|metric card|number)\b", normalized)),
    }


def _looks_percentage_share_query(query_text: str) -> bool:
    normalized = str(query_text or "").strip().lower()
    if not normalized:
        return False
    return bool(re.search(r"\b(percentage|percent|share|distribution)\b", normalized))


def _intent_metric_type(intent_payload: dict[str, Any]) -> str:
    if not isinstance(intent_payload, dict):
        return ""
    metric_type = str(intent_payload.get("metric_type", "")).strip().lower()
    if metric_type:
        return metric_type
    chart_payload = intent_payload.get("chart") if isinstance(intent_payload.get("chart"), dict) else {}
    return str(chart_payload.get("metric_type", "")).strip().lower()


def _intent_chart_type(intent_payload: dict[str, Any]) -> str:
    if not isinstance(intent_payload, dict):
        return ""
    chart_payload = intent_payload.get("chart") if isinstance(intent_payload.get("chart"), dict) else {}
    return _normalize_chart_type(
        str(
            intent_payload.get("selected_chart_type")
            or intent_payload.get("chart_type")
            or chart_payload.get("type")
            or ""
        ).strip()
    )


def _query_for_chart_selection(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    candidates = [
        payload.get("query"),
        (payload.get("sql_generation_input", {}) if isinstance(payload.get("sql_generation_input"), dict) else {}).get("query"),
        (payload.get("validated_intent", {}) if isinstance(payload.get("validated_intent"), dict) else {}).get("query"),
        (payload.get("normalized_intent", {}) if isinstance(payload.get("normalized_intent"), dict) else {}).get("query"),
        (payload.get("extracted_intent", {}) if isinstance(payload.get("extracted_intent"), dict) else {}).get("query"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _shape_supports(chart_type: str, *, shape: dict[str, Any], single_value: bool) -> bool:
    normalized = _normalize_chart_type(chart_type)
    row_count = int(shape.get("row_count", 0) or 0)
    numeric_count = len(shape.get("numeric_columns", []))
    time_count = len(shape.get("time_like_columns", []))
    has_category_value_shape = bool(shape.get("has_category_value_shape"))
    if normalized == ChartType.CARD.value:
        return single_value
    if normalized in {ChartType.LINE.value, ChartType.LINE_MULTI.value, ChartType.AREA.value}:
        return row_count >= 1 and time_count >= 1 and numeric_count >= 1
    if normalized == ChartType.BAR_GROUPED.value:
        return row_count >= 1 and (has_category_value_shape or numeric_count >= 2)
    if normalized in {ChartType.BAR.value, ChartType.BAR_STACKED.value, ChartType.PIE.value}:
        return row_count >= 1 and has_category_value_shape
    if normalized == ChartType.MAP.value:
        columns = [str(col).strip().lower() for col in (shape.get("columns", []) or []) if str(col).strip()]
        geo_tokens = ("lat", "lng", "lon", "longitude", "latitude", "country", "state", "city", "geo", "location")
        return row_count >= 1 and any(any(token in col for token in geo_tokens) for col in columns)
    if normalized == ChartType.COMBO_LINE_BAR.value:
        return row_count >= 1 and time_count >= 1 and numeric_count >= 2
    if normalized == ChartType.TABLE.value:
        return row_count >= 0
    return False


def _validated_chart_choice(
    *,
    explicit_chart_type: str,
    metric_type: str,
    upstream_chart_type: str,
    shape: dict[str, Any],
    single_value: bool,
    relationship_requested: bool,
    time_series_requested: bool,
    distribution_requested: bool,
    ranking_dimension_shape: bool,
    hint_map_requested: bool,
    hint_pie_requested: bool,
    hint_combo_requested: bool,
    hint_area_requested: bool,
    hint_bar_stacked_requested: bool,
    hint_bar_grouped_requested: bool,
    hint_kpi_requested: bool,
) -> tuple[str, str]:
    explicit = _normalize_chart_type(explicit_chart_type)
    if explicit:
        return explicit, "explicit_chart_intent"

    upstream = _normalize_chart_type(upstream_chart_type)
    row_count = int(shape.get("row_count", 0) or 0)
    numeric_count = len(shape.get("numeric_columns", []))
    time_count = len(shape.get("time_like_columns", []))
    has_category_value_shape = bool(shape.get("has_category_value_shape"))
    metric_type_normalized = str(metric_type or "").strip().lower()

    explicit_hint_requested = any(
        (
            hint_map_requested,
            hint_pie_requested,
            hint_combo_requested,
            hint_area_requested,
            hint_bar_stacked_requested,
            hint_bar_grouped_requested,
            hint_kpi_requested,
        )
    )

    # Preserve explicit upstream chart only when the user did not explicitly ask for a chart family.
    if (
        not explicit_hint_requested
        and upstream
        and upstream != ChartType.TABLE.value
        and _shape_supports(upstream, shape=shape, single_value=single_value)
    ):
        return upstream, "upstream_preserved_validated"

    reason_prefix = f"adjusted_from_{upstream}:" if upstream and upstream != ChartType.TABLE.value else ""

    # Structured chart selection rules.
    if hint_kpi_requested and _shape_supports(ChartType.CARD.value, shape=shape, single_value=single_value):
        return ChartType.CARD.value, f"{reason_prefix}explicit_kpi_card"
    if hint_map_requested and _shape_supports(ChartType.MAP.value, shape=shape, single_value=single_value):
        return ChartType.MAP.value, f"{reason_prefix}explicit_map"
    if hint_pie_requested and _shape_supports(ChartType.PIE.value, shape=shape, single_value=single_value):
        return ChartType.PIE.value, f"{reason_prefix}explicit_pie"
    if hint_combo_requested and _shape_supports(ChartType.COMBO_LINE_BAR.value, shape=shape, single_value=single_value):
        return ChartType.COMBO_LINE_BAR.value, f"{reason_prefix}explicit_combo_line_bar"
    if hint_area_requested and _shape_supports(ChartType.AREA.value, shape=shape, single_value=single_value):
        return ChartType.AREA.value, f"{reason_prefix}explicit_area"
    if hint_bar_stacked_requested and _shape_supports(ChartType.BAR_STACKED.value, shape=shape, single_value=single_value):
        return ChartType.BAR_STACKED.value, f"{reason_prefix}explicit_stacked_bar"
    if hint_bar_grouped_requested and _shape_supports(ChartType.BAR_GROUPED.value, shape=shape, single_value=single_value):
        return ChartType.BAR_GROUPED.value, f"{reason_prefix}explicit_grouped_bar"
    if metric_type_normalized in {"percentage", "percent", "ratio"}:
        return ChartType.PIE.value, "Detected 'percentage share' -> pie chart"
    if relationship_requested and _shape_supports(ChartType.COMBO_LINE_BAR.value, shape=shape, single_value=single_value):
        return ChartType.COMBO_LINE_BAR.value, f"{reason_prefix}relationship_time_combo"
    if relationship_requested and _shape_supports(ChartType.LINE_MULTI.value, shape=shape, single_value=single_value):
        return ChartType.LINE_MULTI.value, f"{reason_prefix}relationship_multi_line"
    if time_series_requested and numeric_count >= 2 and _shape_supports(ChartType.LINE_MULTI.value, shape=shape, single_value=single_value):
        return ChartType.LINE_MULTI.value, f"{reason_prefix}time_series_multi_metric"
    if time_series_requested and distribution_requested and _shape_supports(ChartType.AREA.value, shape=shape, single_value=single_value):
        return ChartType.AREA.value, f"{reason_prefix}time_series_distribution_area"
    if time_series_requested and _shape_supports(ChartType.LINE.value, shape=shape, single_value=single_value):
        return ChartType.LINE.value, f"{reason_prefix}time_series_single_metric"
    if distribution_requested and _shape_supports(ChartType.BAR_GROUPED.value, shape=shape, single_value=single_value):
        return ChartType.BAR_GROUPED.value, f"{reason_prefix}distribution_grouped_bar"
    if (ranking_dimension_shape or has_category_value_shape) and numeric_count >= 2 and _shape_supports(ChartType.BAR_GROUPED.value, shape=shape, single_value=single_value):
        return ChartType.BAR_GROUPED.value, f"{reason_prefix}category_multi_metric_grouped_bar"
    if (ranking_dimension_shape or has_category_value_shape) and _shape_supports(ChartType.BAR.value, shape=shape, single_value=single_value):
        return ChartType.BAR.value, f"{reason_prefix}category_single_metric_bar"
    if _shape_supports(ChartType.CARD.value, shape=shape, single_value=single_value):
        return ChartType.CARD.value, f"{reason_prefix}single_value_card"

    # Shape-based fallback rules.
    if _shape_supports(ChartType.COMBO_LINE_BAR.value, shape=shape, single_value=single_value):
        return ChartType.COMBO_LINE_BAR.value, f"{reason_prefix}shape_fallback_combo_line_bar"
    if _shape_supports(ChartType.AREA.value, shape=shape, single_value=single_value):
        return ChartType.AREA.value, f"{reason_prefix}shape_fallback_area"
    if _shape_supports(ChartType.LINE_MULTI.value, shape=shape, single_value=single_value):
        return ChartType.LINE_MULTI.value, f"{reason_prefix}shape_fallback_line_multi"
    if _shape_supports(ChartType.LINE.value, shape=shape, single_value=single_value):
        return ChartType.LINE.value, f"{reason_prefix}shape_fallback_line"
    if _shape_supports(ChartType.BAR_GROUPED.value, shape=shape, single_value=single_value):
        return ChartType.BAR_GROUPED.value, f"{reason_prefix}shape_fallback_grouped_bar"
    if _shape_supports(ChartType.BAR.value, shape=shape, single_value=single_value):
        return ChartType.BAR.value, f"{reason_prefix}shape_fallback_bar"
    if _shape_supports(ChartType.PIE.value, shape=shape, single_value=single_value):
        return ChartType.PIE.value, f"{reason_prefix}shape_fallback_pie"
    if _shape_supports(ChartType.MAP.value, shape=shape, single_value=single_value):
        return ChartType.MAP.value, f"{reason_prefix}shape_fallback_map"
    if _shape_supports(ChartType.CARD.value, shape=shape, single_value=single_value):
        return ChartType.CARD.value, f"{reason_prefix}shape_fallback_card"
    if row_count == 0:
        return "", ""
    if numeric_count >= 1 or time_count >= 1:
        return ChartType.TABLE.value, "safe_fallback_table"
    return ChartType.TABLE.value, "safe_fallback_table"


def _ranking_with_dimension(intent_payload: dict[str, Any]) -> bool:
    ranking = intent_payload.get("ranking") if isinstance(intent_payload.get("ranking"), dict) else {}
    direction = str(ranking.get("direction", "")).strip().upper()
    if direction not in {"ASC", "DESC"}:
        return False
    dimensions = intent_payload.get("dimensions", []) if isinstance(intent_payload.get("dimensions"), list) else []
    return any(str(dim).strip() for dim in dimensions)


def _relationship_comparison_shape(intent_payload: dict[str, Any]) -> bool:
    if not isinstance(intent_payload, dict):
        return False
    operations = {
        str(op).strip().lower()
        for op in (intent_payload.get("operations", []) or [])
        if str(op).strip()
    }
    if "comparison" not in operations:
        return False
    dimensions = intent_payload.get("dimensions", []) if isinstance(intent_payload.get("dimensions"), list) else []
    if any(str(dim).strip() for dim in dimensions):
        return False

    metrics_payload = intent_payload.get("metrics", [])
    metric_count = 0
    if isinstance(metrics_payload, list):
        for metric in metrics_payload:
            if isinstance(metric, dict):
                column = str(metric.get("column", "")).strip()
                raw_aggregation = metric.get("aggregation")
                aggregation = str(raw_aggregation).strip().upper() if raw_aggregation is not None else ""
                if column and not aggregation:
                    metric_count += 1
            elif isinstance(metric, str) and metric.strip():
                metric_count += 1

    if metric_count >= 2:
        return True

    metric_specs_payload = intent_payload.get("metric_specs", [])
    if isinstance(metric_specs_payload, list):
        non_agg_specs = 0
        for metric in metric_specs_payload:
            if not isinstance(metric, dict):
                continue
            column = str(metric.get("column", "")).strip()
            raw_aggregation = metric.get("aggregation")
            aggregation = str(raw_aggregation).strip().upper() if raw_aggregation is not None else ""
            if column and not aggregation:
                non_agg_specs += 1
        if non_agg_specs >= 2:
            return True
    return False


def _sql_has_agg_limit_without_group_by(sql_query: str) -> bool:
    sql_upper = str(sql_query or "").upper()
    has_limit = " LIMIT " in f" {sql_upper} "
    has_group_by = " GROUP BY " in f" {sql_upper} "
    has_aggregate = any(token in sql_upper for token in ("SUM(", "AVG(", "COUNT(", "MIN(", "MAX("))
    return has_limit and has_aggregate and not has_group_by


def _time_grouping_intent(intent_payload: dict[str, Any]) -> bool:
    if not isinstance(intent_payload, dict):
        return False
    granularity = str(intent_payload.get("time_granularity", "")).strip().lower()
    detected = bool(intent_payload.get("time_grouping_detected"))
    if granularity in {"day", "week", "month", "quarter", "year"}:
        return True
    return detected


def _looks_predictive_query(query: str) -> bool:
    normalized = str(query or "").strip().lower()
    if not normalized:
        return False
    predictive_patterns = (
        r"\bforecast\b",
        r"\bpredict\b",
        r"\bfuture\b",
        r"\bupcoming\b",
        r"\bexpected\b",
        r"\bwhat will be\b",
        r"\btrend\b.*\bnext\b",
        r"\bnext\s+\d+\s+(day|days|week|weeks|month|months|year|years)\b",
    )
    return any(re.search(pattern, normalized) for pattern in predictive_patterns)


def _looks_time_series_query(query: str) -> bool:
    normalized = str(query or "").strip().lower()
    if not normalized:
        return False
    return bool(re.search(r"\b(per|by)\s+(day|week|month|quarter|year|hour)\b", normalized))


def _root_cause_for(stage: str, payload: dict[str, Any] | None = None) -> tuple[str, str, str]:
    stage_lower = str(stage or "").strip().lower()
    result_payload = payload or {}
    message = (
        str(result_payload.get("message") or "")
        or str(result_payload.get("error_message") or "")
        or f"Pipeline failed at stage '{stage_lower}'."
    )
    mapping = {
        "input_validation": "input",
        "transcription": "transcription",
        "preprocess": "preprocessing",
        "preprocessing_low": "preprocessing",
        "preprocessing_high": "schema",
        "intent_classification": "routing",
        "intent_extraction": "intent",
        "routing": "routing",
        "sql_generation": "sql_generation",
        "sql_review": "sql_validation",
        "sql_validation": "sql_validation",
        "query_execution": "query_execution",
        "visualization": "visualization",
        "forecasting": "visualization",
        "dagster_orchestration": "orchestration",
    }
    category = mapping.get(stage_lower, "unknown")
    recommended_fix = {
        "input": "Provide a non-empty analytical request with meaningful text.",
        "transcription": "Verify audio clarity, duration, and Whisper service health.",
        "preprocessing": "Review low-level normalization and check whether the request was reduced to empty content.",
        "schema": "Validate schema coverage for requested business terms or adjust metric/dimension names.",
        "routing": "Review classification/routing confidence and fallback route rules.",
        "intent": "Inspect extracted structured intent and resolve missing entities.",
        "sql_generation": "Inspect normalized intent and SQL compiler constraints.",
        "sql_validation": "Inspect SQL safety/review diagnostics and adjust unsupported operations.",
        "query_execution": "Verify ClickHouse connectivity, SQL correctness, and runtime limits.",
        "visualization": "Inspect chart-shape requirements and downstream visualization service health.",
        "orchestration": "Inspect Dagster step events, retries, and failed dependencies.",
        "unknown": "Inspect stage attempts and debug metadata to locate the first failing component.",
    }.get(category, "Inspect trace metadata and retry diagnostics.")
    return category, message, recommended_fix


def _to_trace_stage(
    *,
    status: str,
    result: dict[str, Any] | None,
    final_output: Any,
    fallback_errors: list[dict[str, Any]] | None = None,
    fallback_warnings: list[dict[str, Any]] | None = None,
    extra_debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = result or {}
    debug_metadata = payload.get("debug_metadata", {}) if isinstance(payload.get("debug_metadata"), dict) else {}
    if isinstance(payload, dict) and "confidence" in payload:
        debug_metadata = {**debug_metadata, "confidence": payload.get("confidence")}
    if extra_debug:
        debug_metadata = {**debug_metadata, **extra_debug}
    normalized_status = normalize_stage_status(
        status=status,
        degraded=bool(payload.get("degraded")),
    )

    return stage_payload(
        status=normalized_status,
        final_output=final_output,
        attempts=payload.get("attempts", []) if isinstance(payload.get("attempts"), list) else [],
        errors=(
            payload.get("errors", [])
            if isinstance(payload.get("errors"), list)
            else list(fallback_errors or [])
        ),
        warnings=(
            payload.get("warnings", [])
            if isinstance(payload.get("warnings"), list)
            else list(fallback_warnings or [])
        ),
        debug_metadata=debug_metadata,
        started_at=payload.get("started_at"),
        finished_at=payload.get("finished_at"),
    )


def _build_stage_failed(
    *,
    stage: str,
    message: str,
    transcription: dict[str, Any],
    preprocess: dict[str, Any],
    intent: dict[str, Any],
    routing: dict[str, Any],
    preprocess_high: dict[str, Any],
    intent_extraction: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "failed",
        "stage": stage,
        "message": message,
        "transcription": transcription,
        "preprocess": preprocess,
        "intent": intent,
        "routing": routing,
        "preprocess_high": preprocess_high,
        "intent_extraction": intent_extraction,
    }


def _validate_ir_contract(validated_intent: dict[str, Any]) -> tuple[bool, list[str]]:
    if not isinstance(validated_intent, dict):
        return False, ["validated_intent must be an object"]

    required_keys = [
        "intent",
        "operations",
        "table",
        "metrics",
        "dimensions",
        "filters",
        "aggregation",
        "ranking",
        "order_by",
        "limit",
        "ambiguities",
    ]
    missing = [key for key in required_keys if key not in validated_intent]
    if missing:
        return False, [f"Missing IR fields: {', '.join(missing)}"]

    if not isinstance(validated_intent.get("metrics"), list) or not validated_intent.get("metrics"):
        return False, ["IR must contain at least one metric"]
    if not isinstance(validated_intent.get("dimensions"), list):
        return False, ["IR field 'dimensions' must be a list"]
    if not isinstance(validated_intent.get("filters"), list):
        return False, ["IR field 'filters' must be a list"]
    if not isinstance(validated_intent.get("order_by"), list):
        return False, ["IR field 'order_by' must be a list"]
    if not isinstance(validated_intent.get("operations"), list):
        return False, ["IR field 'operations' must be a list"]
    if not isinstance(validated_intent.get("ranking"), dict):
        return False, ["IR field 'ranking' must be an object"]
    if not str(validated_intent.get("table", "")).strip():
        return False, ["IR field 'table' must be non-empty"]
    if not str(validated_intent.get("intent", "")).strip():
        return False, ["IR field 'intent' must be non-empty"]
    return True, []


def _table_suffix(table_name: str) -> str:
    return str(table_name or "").strip().split(".")[-1].lower()


def _enforce_etl_table_binding(
    *,
    bound_table: str,
    schema: dict[str, Any],
    validated_intent: dict[str, Any],
) -> tuple[bool, str]:
    normalized_bound = str(bound_table or "").strip()
    if not normalized_bound:
        return False, "Dataset binding context is missing required fields: table_name"
    if not isinstance(schema, dict) or not schema:
        return False, "Dataset-table mismatch: empty schema for ETL binding check"

    bound_suffix = _table_suffix(normalized_bound)
    matching_tables = [
        table_name
        for table_name in schema.keys()
        if _table_suffix(str(table_name)) == bound_suffix
    ]
    if len(matching_tables) > 1:
        exact = [t for t in matching_tables if str(t).strip().lower() == normalized_bound.lower()]
        if len(exact) == 1:
            matching_tables = exact
        else:
            matching_tables = [sorted(matching_tables, key=lambda x: str(x))[0]]

    if len(matching_tables) != 1:
        suffixes = sorted({_table_suffix(str(t)) for t in schema.keys()})[:30]
        return (
            False,
            "Dataset-table mismatch: bound table "
            f"{normalized_bound!r} (suffix={bound_suffix!r}) does not match exactly one schema table; "
            f"schema_suffixes_sample={suffixes!r}",
        )

    intent_table = str(validated_intent.get("table", "")).strip()
    if intent_table and _table_suffix(intent_table) != bound_suffix:
        return (
            False,
            "Cross-dataset access is not allowed: intent table "
            f"{intent_table!r} disagrees with bound table {normalized_bound!r}",
        )

    validated_intent["table"] = matching_tables[0]
    return True, ""


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def query_execution_asset(
    context: AssetExecutionContext,
    routing_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    if not stage_allows_progress(routing_asset.get("status"), degraded=bool(routing_asset.get("degraded"))):
        message = str(routing_asset.get("message") or "SQL generation skipped because routing did not allow progress.")
        attempts.append(
            make_attempt(
                attempt_number=1,
                input_payload={"routing_status": routing_asset.get("status")},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="upstream_stage_guard",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="upstream_rejected",
                error_message=message,
            )
        )
        return {
            "status": "skipped",
            "asset_role": "sql_ready_asset",
            "confidence": 0.0,
            "next_step": "stop",
            "intent_type": "invalid",
            "query": "",
            "validated_intent": {},
            "extracted_intent": {},
            "normalized_intent": {},
            "sql_query": "",
            "generated_sql": "",
            "reviewed_sql": "",
            "sql_review": {"approved": False, "reason": message, "corrected_sql": None},
            "execution_result": None,
            "error_type": "upstream_rejected",
            "action_taken": "stop",
            "sql_generation_failure_reason": message,
            "sql_validation_outcome": "skipped",
            "sql_review_outcome": "skipped",
            "safety_validation_outcome": "skipped",
            "sql_lifecycle": {
                "generated": "skipped",
                "normalized": "skipped",
                "validated": "skipped",
                "executed": "skipped",
                "status": "skipped",
            },
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "upstream_rejected", "message": message}],
            "debug_metadata": {
                "upstream_status": routing_asset.get("status"),
                "upstream_stage": "routing",
            },
            "upstream_status": routing_asset.get("status"),
            "upstream_stage": "routing",
        }

    normalized_query = str(routing_asset.get("query", "")).strip()
    normalized_schema = routing_asset.get("schema", {}) or {}
    validated_intent = routing_asset.get("validated_intent", {}) or {}
    debug_metadata = routing_asset.get("debug_metadata", {}) if isinstance(routing_asset.get("debug_metadata"), dict) else {}
    dataset_scope = debug_metadata.get("dataset_scope", {}) if isinstance(debug_metadata.get("dataset_scope"), dict) else {}
    bound_table = str(debug_metadata.get("bound_table", "")).strip() or str(dataset_scope.get("table_name", "")).strip()
    next_step = str(routing_asset.get("next_step", "metabase"))
    predictive_signal = (
        str(next_step).strip().lower() == "forecasting"
        or str(validated_intent.get("intent_type", "")).strip().lower() == "predictive"
        or str(validated_intent.get("question_type", "")).strip().lower() == "predictive"
        or bool(validated_intent.get("requires_forecast"))
    )
    if predictive_signal and isinstance(validated_intent, dict):
        validated_intent["intent_type"] = "predictive"
        validated_intent["question_type"] = "predictive"
        validated_intent["requires_forecast"] = True
        next_step = "forecasting"

    if not normalized_query:
        normalized_query = "show total records by date"
    if not isinstance(normalized_schema, dict):
        normalized_schema = {}
    if not isinstance(validated_intent, dict) or not validated_intent:
        validated_intent = {}

    binding_ok, binding_error = _enforce_etl_table_binding(
        bound_table=bound_table,
        schema=normalized_schema,
        validated_intent=validated_intent,
    )
    if not binding_ok:
        context.log.warning("Dataset binding guard failed; continuing in degraded mode | error=%s", binding_error)

    ir_is_valid, ir_contract_errors = _validate_ir_contract(validated_intent)
    if not ir_is_valid:
        message = "Intent contract is missing required fields: " + "; ".join(ir_contract_errors)
        context.log.error("IR contract validation failed; SQL generation stopped | errors=%s", ir_contract_errors)
        attempts.append(
            make_attempt(
                attempt_number=1,
                input_payload={"validated_intent": validated_intent},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="intent_contract_validator",
                duration_ms=0,
                validation_result={"is_valid": False, "errors": ir_contract_errors},
                error_type="intent_contract_invalid",
                error_message=message,
            )
        )
        return {
            "status": "failed",
            "asset_role": "sql_ready_asset",
            "confidence": 0.0,
            "next_step": next_step,
            "intent_type": routing_asset.get("intent_type", "analytical"),
            "query": normalized_query,
            "validated_intent": validated_intent,
            "extracted_intent": routing_asset.get("extracted_intent", {}),
            "normalized_intent": {},
            "sql_query": "",
            "generated_sql": "",
            "reviewed_sql": "",
            "sql_review": {"approved": False, "reason": message, "corrected_sql": None},
            "execution_result": None,
            "error_type": "intent_contract_invalid",
            "action_taken": "stop",
            "sql_generation_failure_reason": message,
            "sql_validation_outcome": "skipped",
            "sql_review_outcome": "skipped",
            "safety_validation_outcome": "skipped",
            "sql_lifecycle": {
                "generated": "skipped",
                "normalized": "skipped",
                "validated": "skipped",
                "executed": "skipped",
                "status": "skipped",
            },
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "intent_contract_invalid", "message": message}],
            "debug_metadata": {},
        }

    config = IntentExtractionConfig.from_env()
    retry_count = 0
    generated_sql_candidate = ""
    reviewed_sql_candidate = ""
    sql_review_payload: dict[str, Any] = {}
    review_status = "failed"

    _routing_debug = routing_asset.get("debug_metadata") if isinstance(routing_asset.get("debug_metadata"), dict) else {}
    _classification = _routing_debug.get("classification") if isinstance(_routing_debug.get("classification"), dict) else {}
    _sql_preprocess_hints = dict(_classification["preprocess_hints"]) if isinstance(_classification.get("preprocess_hints"), dict) else {}
    _dataset_scope = _routing_debug.get("dataset_scope") if isinstance(_routing_debug.get("dataset_scope"), dict) else {}
    _validate_workspace = str(_dataset_scope.get("workspace_id") or os.getenv("QUERY_SERVICE_WORKSPACE_ID", "") or "").strip()
    from shared.query_service_auth import require_query_service_bearer_token
    from shared.sql_review import (
        bind_query_service_validation_for_pipeline,
        reset_query_service_validation_for_pipeline,
    )

    _qval_handles = bind_query_service_validation_for_pipeline(
        workspace_id=_validate_workspace,
        bearer_token=require_query_service_bearer_token(),
    )
    try:
        while True:
            try:
                attempt_started_perf = time.perf_counter()
                _workspace_ch = str(
                    validated_intent.get("workspace_clickhouse_db") or os.getenv("CLICKHOUSE_DATABASE", "") or ""
                ).strip() or None
                normalized_intent, sql_query = build_sql_from_intent(
                    query=normalized_query,
                    intent=validated_intent,
                    schema=normalized_schema,
                    workspace_clickhouse_db=_workspace_ch,
                    preprocess_hints=_sql_preprocess_hints or None,
                )
                generated_sql_candidate = sql_query
                chart_contract = build_chart_contract_from_intent(
                    normalized_intent,
                    schema=normalized_schema,
                    user_text=normalized_query,
                    final_route=next_step,
                )
                sql_review = review_and_correct_sql(
                    question=normalized_query,
                    normalized_question=normalized_query,
                    schema=normalized_schema,
                    selected_table=str(normalized_intent.get("table", "")),
                    selected_columns=sorted(
                        {
                            metric.get("column")
                            for metric in normalized_intent.get("metrics", [])
                            if isinstance(metric, dict) and metric.get("column")
                        }
                        | {
                            dim
                            for dim in normalized_intent.get("dimensions", [])
                            if isinstance(dim, str) and dim
                        }
                    ),
                    chart_contract=chart_contract,
                    generated_sql=sql_query,
                    validated_intent=normalized_intent,
                    extracted_intent=routing_asset.get("extracted_intent", {}),
                )
                sql_review_payload = sql_review
                reviewed_sql = str(sql_review.get("reviewed_sql", "")).strip()
                reviewed_sql_candidate = reviewed_sql
                review_status = str(sql_review.get("status", "rejected")).strip().lower()
                if review_status == "rejected":
                    raise ValueError("; ".join([str(note) for note in sql_review.get("notes", []) if str(note).strip()]) or "SQL review rejected generated SQL.")

                if _ranking_with_dimension(normalized_intent) and _sql_has_agg_limit_without_group_by(reviewed_sql):
                    review_notes = (
                        sql_review_payload.get("notes", [])
                        if isinstance(sql_review_payload.get("notes"), list)
                        else []
                    )
                    reviewed_sql = sql_query
                    reviewed_sql_candidate = reviewed_sql
                    sql_review_payload = {
                        **sql_review_payload,
                        "status": "approved",
                        "reviewed_sql": reviewed_sql,
                        "notes": [
                            *[str(note) for note in review_notes if str(note).strip()],
                            "Applied ranking safety guard: restored compiler SQL with GROUP BY.",
                        ],
                        "reason_category": str(
                            sql_review_payload.get("reason_category", "ranking_group_by_guard")
                            or "ranking_group_by_guard"
                        ),
                    }
                    review_status = "ranking_group_by_guard"

                _align_errs = validate_chart_sql_alignment(
                    chart_type=str(chart_contract.get("chart_type") or ""),
                    sql=reviewed_sql,
                    intent=normalized_intent,
                )
                if _align_errs:
                    raise ValueError("; ".join(_align_errs))

                execution_result = None
                attempt_duration_ms = int((time.perf_counter() - attempt_started_perf) * 1000)
                attempts.append(
                    make_attempt(
                        attempt_number=len(attempts) + 1,
                        input_payload={
                            "query": normalized_query,
                            "validated_intent": validated_intent,
                            "next_step": next_step,
                        },
                        output_payload={
                            "generated_sql": sql_query,
                            "reviewed_sql": reviewed_sql,
                            "normalized_intent": normalized_intent,
                            "sql_review": sql_review,
                            "execution_preview": {"preview_rows": [], "row_count": 0, "columns": [], "status": "skipped"},
                        },
                        success=True,
                        retry_triggered=False,
                        model_or_method_used="build_sql_from_intent+review_and_correct_sql",
                        duration_ms=attempt_duration_ms,
                        validation_result={
                            "sql_validation_outcome": "passed",
                            "sql_review_outcome": review_status,
                            "safety_validation_outcome": "passed",
                        },
                    )
                )
                context.log.info(
                    "SQL ready asset completed | next_step=%s sql_chars=%s",
                    next_step,
                    len(reviewed_sql),
                )
                return {
                    "status": "success",
                    "asset_role": "sql_ready_asset",
                    "confidence": 0.9,
                    "next_step": next_step,
                    "intent_type": routing_asset.get("intent_type", "analytical"),
                    "query": normalized_query,
                    "validated_intent": validated_intent,
                    "extracted_intent": routing_asset.get("extracted_intent", {}),
                    "normalized_intent": normalized_intent,
                    "sql_query": reviewed_sql,
                    "generated_sql": sql_query,
                    "reviewed_sql": reviewed_sql,
                    "sql_review": sql_review,
                    "execution_result": execution_result,
                    "chart_contract": chart_contract,
                    "error_type": "none",
                    "action_taken": "proceed",
                    "sql_generation_input": {
                        "query": normalized_query,
                        "intent": validated_intent,
                        "schema_tables": list(normalized_schema.keys()),
                    },
                    "sql_validation_outcome": "passed",
                    "sql_review_outcome": review_status,
                    "safety_validation_outcome": "passed",
                    "sql_lifecycle": {
                        "generated": "generated",
                        "normalized": "normalized",
                        "validated": "validated",
                        "executed": "skipped",
                        "status": "sql_ready",
                    },
                    "referenced_tables": [normalized_intent.get("table")],
                    "referenced_columns": sorted(
                        {
                            metric.get("column")
                            for metric in normalized_intent.get("metrics", [])
                            if isinstance(metric, dict) and metric.get("column")
                        }
                        | {
                            dim
                            for dim in normalized_intent.get("dimensions", [])
                            if isinstance(dim, str) and dim
                        }
                        | {
                            flt.get("column")
                            for flt in normalized_intent.get("filters", [])
                            if isinstance(flt, dict) and flt.get("column")
                        }
                    ),
                    "result_preview": {"preview_rows": [], "row_count": 0, "columns": [], "status": "execution_delegated_to_query_service"},
                    "attempts": attempts,
                    "attempts_count": len(attempts),
                    "started_at": stage_started_at,
                    "finished_at": utc_now_iso(),
                    "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                    "warnings": [],
                    "errors": [],
                    "debug_metadata": {
                        "retry_count": retry_count,
                        "selected_table": normalized_intent.get("table", ""),
                        "selected_columns": sorted(
                            {
                                metric.get("column")
                                for metric in normalized_intent.get("metrics", [])
                                if isinstance(metric, dict) and metric.get("column")
                            }
                            | {
                                dim
                                for dim in normalized_intent.get("dimensions", [])
                                if isinstance(dim, str) and dim
                            }
                        ),
                        "time_column_used": str(normalized_intent.get("time_column", "")).strip(),
                        "dataset_scope": (
                            routing_asset.get("debug_metadata", {})
                            if isinstance(routing_asset.get("debug_metadata"), dict)
                            else {}
                        ).get("dataset_scope", {}),
                        "reason_for_selection": "sql_executed",
                        "auth_status": get_last_query_service_auth_status(),
                    },
                }
            except Exception as exc:  # noqa: BLE001
                exc_text = str(exc)
                exc_lower = exc_text.lower()
                auth_failure = "query_service_unauthorized" in exc_lower or "query_service_auth_not_configured" in exc_lower
                error_type = classify_intent_extraction_error(exc)
                if auth_failure:
                    error_type = "query_service_auth"
                action_taken = decide_intent_extraction_action(
                    error_type=error_type,
                    retry_count=retry_count,
                    config=config,
                )
                auth_status = get_last_query_service_auth_status()
                attempts.append(
                    make_attempt(
                        attempt_number=len(attempts) + 1,
                        input_payload={
                            "query": normalized_query,
                            "validated_intent": validated_intent,
                            "next_step": next_step,
                        },
                        output_payload={},
                        success=False,
                        retry_triggered=action_taken == "retry",
                        retry_reason=str(exc) if action_taken == "retry" else "",
                        model_or_method_used="build_sql_from_intent+review_and_correct_sql+sql_ready_asset",
                        duration_ms=0,
                        validation_result={
                            "sql_validation_outcome": "failed",
                            "sql_review_outcome": "failed",
                            "safety_validation_outcome": "failed",
                            "auth_status": auth_status,
                        },
                        error_type=error_type,
                        error_message=str(exc),
                    )
                )
                context.log.error(
                    "Query execution failed | error_type=%s action_taken=%s retry_count=%s error=%s",
                    error_type,
                    action_taken,
                    retry_count,
                    str(exc),
                )

                if action_taken == "retry":
                    retry_count += 1
                    continue

                user_safe = (
                    "Query execution failed due to authorization error between services."
                    if "query_service_unauthorized" in exc_lower
                    else (
                        "Query execution failed due to missing service authentication configuration."
                        if "query_service_auth_not_configured" in exc_lower
                        else ""
                    )
                )
                return {
                    "status": "failed",
                    "confidence": 0.0,
                    "next_step": next_step,
                    "intent_type": routing_asset.get("intent_type", "analytical"),
                    "query": normalized_query,
                    "validated_intent": validated_intent,
                    "extracted_intent": routing_asset.get("extracted_intent", {}),
                    "sql_query": "",
                    "generated_sql": generated_sql_candidate,
                    "reviewed_sql": reviewed_sql_candidate,
                    "sql_review": sql_review_payload,
                    "execution_result": None,
                    "error_type": error_type,
                    "action_taken": action_taken,
                    "sql_generation_input": {
                        "query": normalized_query,
                        "intent": validated_intent,
                    },
                    "sql_generation_failure_reason": exc_text,
                    "user_safe_message": user_safe or (
                        "SQL validation failed." if "sql" in exc_lower and "reject" in exc_lower else ""
                    ),
                    "sql_validation_outcome": "failed",
                    "sql_review_outcome": "failed",
                    "safety_validation_outcome": "failed",
                    "sql_lifecycle": {
                        "generated": "generated" if generated_sql_candidate else "missing",
                        "normalized": "generated" if generated_sql_candidate else "missing",
                        "validated": "failed",
                        "executed": "failed",
                        "status": "failed",
                    },
                    "attempts": attempts,
                    "attempts_count": len(attempts),
                    "started_at": stage_started_at,
                    "finished_at": utc_now_iso(),
                    "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                    "warnings": [],
                    "errors": [{"type": error_type, "message": exc_text}],
                    "debug_metadata": {
                        "retry_count": retry_count,
                        "action_taken": action_taken,
                        "auth_status": auth_status,
                        "execution_status": "failed",
                        "root_cause": exc_text,
                    },
                }

    finally:
        reset_query_service_validation_for_pipeline(_qval_handles)


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def visualization_asset(
    context: AssetExecutionContext,
    query_execution_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    next_step = str(query_execution_asset.get("next_step", "")).strip().lower()
    if next_step != "metabase" or not stage_allows_progress(query_execution_asset.get("status"), degraded=bool(query_execution_asset.get("degraded"))):
        reason = "route_not_selected" if next_step != "metabase" else "upstream_sql_not_ready"
        result = {
            "status": "skipped",
            "next_step": "metabase",
            "error_type": reason,
            "action_taken": "stop",
            "downstream_result": None,
            "attempts": [
                make_attempt(
                    attempt_number=1,
                    input_payload={"next_step": next_step, "sql_status": query_execution_asset.get("status")},
                    output_payload={},
                    success=False,
                    retry_triggered=False,
                    model_or_method_used="chart_contract_route_guard",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type=reason,
                    error_message="Chart recommendation skipped because analytical visualization route was not selected.",
                )
            ],
            "attempts_count": 1,
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [{"type": reason, "message": "Chart recommendation skipped."}],
            "errors": [],
            "debug_metadata": {
                "upstream_status": query_execution_asset.get("status"),
                "upstream_stage": "query_execution",
            },
            "reason_chart_not_generated": reason,
            "upstream_status": query_execution_asset.get("status"),
            "upstream_stage": "query_execution",
        }
    else:
        normalized_intent = query_execution_asset.get("normalized_intent", {}) if isinstance(query_execution_asset.get("normalized_intent"), dict) else {}
        upstream_contract = query_execution_asset.get("chart_contract") if isinstance(query_execution_asset.get("chart_contract"), dict) else {}
        chart_contract = build_chart_contract_from_intent(
            normalized_intent,
            user_text=str(query_execution_asset.get("query", "")),
            final_route=next_step,
            visualization=upstream_contract,
        )
        if isinstance(upstream_contract, dict) and upstream_contract:
            # Preserve upstream fields, but ensure required keys exist and lock is enforced.
            chart_contract = {
                **upstream_contract,
                **chart_contract,
            }
        selected_chart_type = normalize_chart_type(
            chart_contract.get("selected_chart_type") or chart_contract.get("chart_type"),
            default=ChartType.TABLE.value,
        )
        # Strict contract policy: ai-service MUST finalize the chart contract.
        # No delegation. No recommendation. No partial contract.
        result = {
            "status": "success",
            "confidence": float(chart_contract.get("chart_confidence", 0.75) or 0.75),
            "next_step": "metabase",
            "error_type": "none",
            "action_taken": "proceed",
            "downstream_result": None,
            "visualization_status": "finalized",
            "selected_chart_type": selected_chart_type,
            "reason_chart_selected": str(chart_contract.get("chart_reason", "chart_contract_recommended")),
            "reason_chart_not_generated": "",
            "chart_locked": True,
            "chart_selector_source": str(chart_contract.get("chart_source", "ai-service")),
            "chart_selector_model": "",
            "chart_selector_confidence": float(chart_contract.get("chart_confidence", 0.75) or 0.75),
            "chart_contract": {
                **(chart_contract if isinstance(chart_contract, dict) else {}),
                "chart_lock": True,
                "explicit_chart_lock": True,
                "locked": True,
            },
            "visualization_payload_preview": None,
            "attempts": [
                make_attempt(
                    attempt_number=1,
                    input_payload={"intent": normalized_intent},
                    output_payload={"chart_contract": chart_contract},
                    success=True,
                    retry_triggered=False,
                    model_or_method_used="build_chart_contract_from_intent",
                    duration_ms=0,
                    validation_result={"is_valid": True},
                )
            ],
            "attempts_count": 1,
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [],
            "debug_metadata": {"renderer": "visualization-service"},
        }
    context.log.info(
        "Chart contract recommendation completed | status=%s",
        result.get("status"),
    )
    return result


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def forecasting_asset(
    context: AssetExecutionContext,
    query_execution_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    next_step = str(query_execution_asset.get("next_step", "")).strip().lower()
    reason = "route_not_selected" if next_step != "forecasting" else "forecasting_delegated_to_voice_service"
    # Phase 9 / audit §12.2: when the route IS forecasting, the asset is
    # *delegated* to voice-service, not skipped. We keep ``skipped`` only
    # when the route isn't forecasting at all (so the asset really did no
    # work for this run).
    delegated = next_step == "forecasting"
    result = {
        "status": "delegated" if delegated else "skipped",
        "next_step": "forecasting",
        "error_type": reason,
        "action_taken": "stop" if not delegated else "delegate",
        "downstream_result": None,
        "attempts": [
            make_attempt(
                attempt_number=1,
                input_payload={"next_step": next_step, "sql_status": query_execution_asset.get("status")},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="forecasting_route_guard",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type=reason,
                error_message="Forecasting is executed by voice-service after query-service returns actual rows.",
            )
        ],
        "attempts_count": 1,
        "started_at": stage_started_at,
        "finished_at": utc_now_iso(),
        "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
        "warnings": [{"type": reason, "message": "Forecasting not run in ai-service."}],
        "errors": [],
        "debug_metadata": {"owner": "voice-service"},
        "reason_chart_not_generated": reason,
    }
    context.log.info(
        "Forecasting handoff stage completed | status=%s",
        result.get("status"),
    )
    return result


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def pipeline_result_asset(
    pipeline_request_asset: dict[str, Any],
    transcription_asset: dict[str, Any],
    preprocessing_low_asset: dict[str, Any],
    intent_classification_asset: dict[str, Any],
    preprocessing_high_asset: dict[str, Any],
    intent_extraction_asset: dict[str, Any],
    routing_asset: dict[str, Any],
    query_execution_asset: dict[str, Any],
    visualization_asset: dict[str, Any],
    forecasting_asset: dict[str, Any],
) -> dict[str, Any]:
    trace = build_pipeline_trace_template(request_metadata=pipeline_request_asset)

    attach_stage(
        trace,
        "transcription",
        _to_trace_stage(
            status=str(transcription_asset.get("status", "unknown")),
            result=transcription_asset,
            final_output={
                "status": transcription_asset.get("status"),
                "source": transcription_asset.get("source"),
                "text_preview": str(transcription_asset.get("text", ""))[:300],
                "error_type": transcription_asset.get("error_type"),
            },
        ),
    )
    attach_stage(
        trace,
        "preprocessing_low",
        _to_trace_stage(
            status=str(preprocessing_low_asset.get("status", "unknown")),
            result=preprocessing_low_asset,
            final_output={
                "original_text": preprocessing_low_asset.get("original_text", ""),
                "cleaned_text": preprocessing_low_asset.get("cleaned_text", ""),
                "spelling_corrected_text": preprocessing_low_asset.get("spelling_corrected_text", ""),
                "spelling_changes": preprocessing_low_asset.get("spelling_changes", []),
                "has_spelling_correction": preprocessing_low_asset.get("has_spelling_correction", False),
                "removed_filler_words": preprocessing_low_asset.get("removed_filler_words", []),
                "changes": preprocessing_low_asset.get("changes", {}),
                "correction_source": preprocessing_low_asset.get("correction_source", ""),
                "detected_changes": preprocessing_low_asset.get("detected_changes", []),
            },
        ),
    )
    classification_trace_payload = _to_trace_stage(
        status=str(intent_classification_asset.get("status", "unknown")),
        result=intent_classification_asset,
        final_output={
            "type": intent_classification_asset.get("classification_type") or intent_classification_asset.get("type"),
            "classification": intent_classification_asset.get("classification"),
            "reasoning": intent_classification_asset.get("classification_reason"),
            "confidence": intent_classification_asset.get("confidence"),
            "question_type": intent_classification_asset.get("question_type"),
            "requires_forecast": intent_classification_asset.get("requires_forecast"),
            "raw_model_response": intent_classification_asset.get("raw_model_response"),
            "route": (
                intent_classification_asset.get("debug_metadata", {})
                if isinstance(intent_classification_asset.get("debug_metadata"), dict)
                else {}
            ).get("route"),
        },
        extra_debug={
            "raw_classifier_output": intent_classification_asset.get("raw_classifier_output", {}),
        },
    )
    attach_stage(trace, "classification", classification_trace_payload)
    # Legacy alias for backwards compatibility with historical consumers.
    attach_stage(trace, "input_validation", classification_trace_payload)

    def _finalize_response(
        *,
        payload: dict[str, Any],
        overall_status: str,
        stage: str,
        final_route: str,
        final_user_message: str,
    ) -> dict[str, Any]:
        root_category, root_detail, recommended_fix = _root_cause_for(stage=stage, payload=payload)
        if overall_status in {"success", "degraded"}:
            root_category = "none"
            if overall_status == "degraded":
                reasons = payload.get("degradation_reasons", [])
                reasons_text = ", ".join([str(item) for item in reasons if str(item).strip()])
                root_detail = (
                    "Pipeline executed with degraded stages."
                    if not reasons_text
                    else f"Pipeline executed with degraded stages: {reasons_text}"
                )
                recommended_fix = "Review degraded stage reasons and restore full model/data availability."
            else:
                root_detail = "Pipeline executed successfully."
                recommended_fix = ""
        finalize_trace(
            trace,
            overall_status=overall_status,
            final_route=final_route,
            final_user_message=final_user_message,
            root_cause_category=root_category,
            root_cause_detail=root_detail,
            analyst_recommended_fix=recommended_fix,
        )
        payload["pipeline_trace"] = trace
        payload["overall_status"] = trace["overall_status"]
        payload["root_cause"] = trace["root_cause"]
        payload["final_route"] = final_route
        payload["final_user_message"] = final_user_message
        return payload

    def _final_output_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        """Return a compact, JSON-safe summary for trace final_response output."""
        return {
            "status": payload.get("status"),
            "stage": payload.get("stage"),
            "message": payload.get("message"),
            "final_route": payload.get("final_route"),
            "final_user_message": payload.get("final_user_message"),
        }

    def _mark_downstream_skipped(reason: str) -> None:
        for stage_name in (
            "predictive_intent",
            "intent_extraction",
            "analytical_intent",
            "sql_generation",
            "sql_review",
            "sql_validation",
            "query_execution",
            "visualization",
            "forecasting",
        ):
            attach_stage(
                trace,
                stage_name,
                stage_payload(
                    status="skipped",
                    final_output={"reason": reason},
                    attempts=[
                        make_attempt(
                            attempt_number=1,
                            input_payload={"reason": reason},
                            output_payload={},
                            success=False,
                            retry_triggered=False,
                            model_or_method_used="enforcement_guard",
                            duration_ms=0,
                            validation_result={"is_valid": False},
                            error_type="skipped_by_enforcement",
                            error_message=reason,
                        )
                    ],
                    errors=[],
                    warnings=[{"type": "skipped", "message": reason}],
                    debug_metadata={"skipped_by": "enforcement_guard"},
                ),
            )

    if not stage_allows_progress(transcription_asset.get("status"), degraded=bool(transcription_asset.get("degraded"))):
        payload = {
            "status": "failed",
            "stage": "transcription",
            "transcription": transcription_asset,
        }
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(
                status="failed",
                result=None,
                final_output=_final_output_snapshot(payload),
            ),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="transcription",
            final_route="stop",
            final_user_message="Transcription failed before analytical routing.",
        )

    if not stage_allows_progress(preprocessing_low_asset.get("status"), degraded=bool(preprocessing_low_asset.get("degraded"))):
        payload = {
            "status": "failed",
            "stage": "preprocess",
            "transcription": transcription_asset,
            "preprocess": preprocessing_low_asset,
        }
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="preprocessing_low",
            final_route="stop",
            final_user_message="Low preprocessing failed before analytical routing.",
        )

    if not stage_allows_progress(
        intent_classification_asset.get("status"),
        degraded=bool(intent_classification_asset.get("degraded")),
    ):
        payload = {
            "status": "failed",
            "stage": "intent_classification",
            "transcription": transcription_asset,
            "preprocess": preprocessing_low_asset,
            "intent": intent_classification_asset,
        }
        attach_stage(
            trace,
            "routing",
            _to_trace_stage(
                status="failed",
                result=intent_classification_asset,
                final_output={"message": "Intent classification stage failed."},
            ),
        )
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="intent_classification",
            final_route="stop",
            final_user_message="Input classification failed before analytical routing.",
        )

    if str(intent_classification_asset.get("classification", "")).strip().lower() in {
        "invalid_input",
        "conversational",
    }:
        payload = {
            "status": "rejected",
            "stage": "classification",
            "message": intent_classification_asset.get("classification_reason")
            or "Input was classified as non-analytical.",
            "transcription": transcription_asset,
            "preprocess": preprocessing_low_asset,
            "intent": intent_classification_asset,
        }
        attach_stage(
            trace,
            "routing",
            _to_trace_stage(
                status="rejected",
                result=intent_classification_asset,
                final_output={
                    "classification": intent_classification_asset.get("classification"),
                    "reason": intent_classification_asset.get("classification_reason"),
                },
            ),
        )
        attach_stage(
            trace,
            "preprocessing_high",
            _to_trace_stage(
                status="skipped",
                result=preprocessing_high_asset,
                final_output={
                    "message": "Schema preprocessing skipped because input was rejected by classification.",
                    "classification": intent_classification_asset.get("classification"),
                },
            ),
        )
        _mark_downstream_skipped("Pipeline stopped at input classification stage.")
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="rejected", result=None, final_output=_final_output_snapshot(payload)),
        )
        final_route = str(intent_classification_asset.get("classification", "stop"))
        return _finalize_response(
            payload=payload,
            overall_status="rejected",
            stage="classification",
            final_route=final_route,
            final_user_message=str(payload.get("message", "Input rejected before routing.")),
        )

    early_routing = (
        preprocessing_high_asset.get("routing", {})
        if isinstance(preprocessing_high_asset.get("routing"), dict)
        else {}
    )
    attach_stage(
        trace,
        "routing",
        _to_trace_stage(
            status=normalize_stage_status(
                early_routing.get("status", "unknown"),
                degraded=bool(early_routing.get("degraded")),
            ),
            result=early_routing,
            final_output={
                "route": early_routing.get("route"),
                "next_step": early_routing.get("next_step"),
                "next_stage": early_routing.get("next_stage"),
                "message": early_routing.get("message", ""),
                "reason": early_routing.get("reason", ""),
            },
        ),
    )

    attach_stage(
        trace,
        "preprocessing_high",
        _to_trace_stage(
            status=str(preprocessing_high_asset.get("status", "unknown")),
            result=preprocessing_high_asset,
            final_output={
                "final_query": preprocessing_high_asset.get("final_query", ""),
                "schema_valid": preprocessing_high_asset.get("schema_valid"),
                "schema_validation_status": preprocessing_high_asset.get("schema_validation_status"),
                "route": preprocessing_high_asset.get("route", ""),
                "skipped_schema_terms": preprocessing_high_asset.get("skipped_schema_terms", []),
                "unresolved_terms": preprocessing_high_asset.get("unresolved_terms", []),
                "unresolved_lexical_terms": preprocessing_high_asset.get("unresolved_lexical_terms", []),
                "unsupported_terms": preprocessing_high_asset.get("unsupported_terms", []),
                "original_terms": preprocessing_high_asset.get("original_terms", []),
                "corrected_terms": preprocessing_high_asset.get("corrected_terms", []),
                "term_resolutions": preprocessing_high_asset.get("term_resolutions", []),
                "selected_table": preprocessing_high_asset.get("selected_table", ""),
                "selected_columns": preprocessing_high_asset.get("selected_columns", []),
            },
        ),
    )

    if preprocessing_high_asset.get("status") == "rejected":
        payload = {
            "status": "rejected",
            "stage": "preprocessing_high",
            "message": preprocessing_high_asset.get(
                "message",
                "The requested column does not exist in your data.",
            ),
            "transcription": transcription_asset,
            "preprocess": preprocessing_low_asset,
            "intent": intent_classification_asset,
            "routing": preprocessing_high_asset.get("routing", {}),
            "preprocess_high": preprocessing_high_asset,
        }
        attach_stage(
            trace,
            "routing",
            _to_trace_stage(
                status="rejected",
                result=preprocessing_high_asset.get("routing", {}),
                final_output=preprocessing_high_asset.get("routing", {}),
            ),
        )
        _mark_downstream_skipped("Pipeline stopped after schema validation rejection.")
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="rejected", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="rejected",
            stage="preprocessing_high",
            final_route="stop",
            final_user_message=str(payload.get("message", "Schema-aware correction rejected the request.")),
        )

    if not stage_allows_progress(
        preprocessing_high_asset.get("status"),
        degraded=bool(preprocessing_high_asset.get("degraded")),
    ):
        payload = {
            "status": "failed",
            "stage": "preprocessing_high",
            "transcription": transcription_asset,
            "preprocess": preprocessing_low_asset,
            "intent": intent_classification_asset,
            "routing": preprocessing_high_asset.get("routing", {}),
            "preprocess_high": preprocessing_high_asset,
        }
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="preprocessing_high",
            final_route="stop",
            final_user_message="Schema-aware preprocessing failed before intent extraction.",
        )

    intent_trace_payload = _to_trace_stage(
        status=str(intent_extraction_asset.get("status", "unknown")),
        result=intent_extraction_asset,
        final_output={
            "intent_type": intent_extraction_asset.get("intent_type"),
            "next_step": intent_extraction_asset.get("next_step"),
            "query": intent_extraction_asset.get("query", ""),
            "schema_tables": list((intent_extraction_asset.get("schema", {}) or {}).keys()),
            "extracted_intent": intent_extraction_asset.get("extracted_intent", {}),
            "validated_intent": intent_extraction_asset.get("validated_intent", {}),
        },
        extra_debug={
            "llm_prompt": intent_extraction_asset.get("debug_metadata", {}).get("llm_prompt", ""),
            "llm_raw_output": intent_extraction_asset.get("debug_metadata", {}).get("llm_raw_output", ""),
        },
    )
    attach_stage(trace, "intent_extraction", intent_trace_payload)
    # Legacy alias.
    attach_stage(trace, "analytical_intent", intent_trace_payload)

    is_predictive_intent = str(intent_extraction_asset.get("intent_type", "")).strip().lower() == "predictive"
    if is_predictive_intent:
        attach_stage(
            trace,
            "predictive_intent",
            _to_trace_stage(
                status=str(intent_extraction_asset.get("status", "unknown")),
                result=intent_extraction_asset,
                final_output={
                    "intent_type": "predictive",
                    "metric": (intent_extraction_asset.get("extracted_intent", {}) or {}).get("metric", ""),
                    "time_column": (intent_extraction_asset.get("extracted_intent", {}) or {}).get("time_column", ""),
                    "horizon": (
                        (intent_extraction_asset.get("extracted_intent", {}) or {}).get("horizon")
                        or (intent_extraction_asset.get("extracted_intent", {}) or {}).get("forecast_horizon")
                    ),
                    "granularity": (intent_extraction_asset.get("extracted_intent", {}) or {}).get("granularity", ""),
                },
            ),
        )
    else:
        attach_stage(
            trace,
            "predictive_intent",
            stage_payload(
                status="skipped",
                final_output={"reason": "analytical_route_selected"},
                attempts=[],
                warnings=[],
                errors=[],
                debug_metadata={},
            ),
        )
    if not stage_allows_progress(
        intent_extraction_asset.get("status"),
        degraded=bool(intent_extraction_asset.get("degraded")),
    ):
        payload = {
            "status": "failed",
            "stage": "intent_extraction",
            "transcription": transcription_asset,
            "preprocess": preprocessing_low_asset,
            "intent": intent_classification_asset,
            "routing": routing_asset,
            "preprocess_high": preprocessing_high_asset,
            "intent_extraction": intent_extraction_asset,
        }
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="intent_extraction",
            final_route="stop",
            final_user_message="Intent extraction failed before SQL generation.",
        )

    attach_stage(
        trace,
        "routing",
        _to_trace_stage(
            status=str(routing_asset.get("status", "unknown")),
            result=routing_asset,
            final_output={
                "next_step": routing_asset.get("next_step"),
                "intent_type": routing_asset.get("intent_type"),
                "route_reason": routing_asset.get("reason", ""),
                "fallback_route": routing_asset.get("fallback_route", ""),
                "classification_route": (
                    (preprocessing_high_asset.get("routing", {}) if isinstance(preprocessing_high_asset.get("routing"), dict) else {})
                    .get("route", "")
                ),
            },
        ),
    )
    if not stage_allows_progress(routing_asset.get("status"), degraded=bool(routing_asset.get("degraded"))):
        payload = _build_stage_failed(
            stage="routing",
            message="Routing failed after intent extraction.",
            transcription=transcription_asset,
            preprocess=preprocessing_low_asset,
            intent=intent_classification_asset,
            routing=routing_asset,
            preprocess_high=preprocessing_high_asset,
            intent_extraction=intent_extraction_asset,
        )
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="routing",
            final_route="stop",
            final_user_message="Routing failed after analytical intent extraction.",
        )

    sql_lifecycle = (
        query_execution_asset.get("sql_lifecycle", {})
        if isinstance(query_execution_asset.get("sql_lifecycle"), dict)
        else {}
    )
    sql_generation_status = str(sql_lifecycle.get("status", "")).strip().lower()
    if not sql_generation_status:
        sql_generation_status = "executed" if query_execution_asset.get("sql_query") else "failed"
    if sql_generation_status in {"generated", "normalized", "validated", "executed", "sql_ready"}:
        sql_generation_status = "success"
    generated_sql_for_trace = str(
        query_execution_asset.get("reviewed_sql")
        or query_execution_asset.get("generated_sql")
        or query_execution_asset.get("sql_query", "")
        or ""
    ).strip()
    if generated_sql_for_trace and sql_generation_status in {"", "skipped"}:
        sql_generation_status = "success"
    if query_execution_asset.get("status") == "skipped" and not generated_sql_for_trace:
        sql_generation_status = "skipped"
    attach_stage(
        trace,
        "sql_generation",
        _to_trace_stage(
            status=sql_generation_status,
            result=query_execution_asset,
            final_output={
                "generated_sql": generated_sql_for_trace,
                "sql_lifecycle": sql_lifecycle,
                "historical_sql_only": str(routing_asset.get("next_step", "")).strip().lower() == "forecasting",
                "reason_sql_not_generated": query_execution_asset.get("sql_generation_failure_reason", ""),
                "raw_prompt_inputs": query_execution_asset.get("sql_generation_input", {}),
            },
        ),
    )
    attach_stage(
        trace,
        "sql_review",
        _to_trace_stage(
            status="success"
            if (
                query_execution_asset.get("sql_review_outcome") in {"approved", "corrected", "passed", "fallback_compiler"}
            )
            else ("skipped" if query_execution_asset.get("sql_review_outcome") == "skipped_for_forecasting" else (
                "skipped" if query_execution_asset.get("status") == "skipped" else "failed"
            )),
            result=query_execution_asset,
            final_output={
                "generated_sql": query_execution_asset.get("generated_sql", ""),
                "reviewed_sql": query_execution_asset.get("reviewed_sql", query_execution_asset.get("sql_query", "")),
                "sql_review_outcome": query_execution_asset.get("sql_review_outcome", "skipped"),
                "sql_review_notes": (
                    query_execution_asset.get("sql_review", {})
                    if isinstance(query_execution_asset.get("sql_review"), dict)
                    else {}
                ).get("notes", []),
                "sql_review_reason_category": (
                    query_execution_asset.get("sql_review", {})
                    if isinstance(query_execution_asset.get("sql_review"), dict)
                    else {}
                ).get("reason_category", ""),
            },
        ),
    )
    _qe_debug = query_execution_asset.get("debug_metadata") if isinstance(query_execution_asset.get("debug_metadata"), dict) else {}
    attach_stage(
        trace,
        "sql_validation",
        _to_trace_stage(
            status="success"
            if (
                query_execution_asset.get("sql_validation_outcome") == "passed"
            )
            else ("skipped" if query_execution_asset.get("status") == "skipped" else "failed"),
            result=query_execution_asset,
            final_output={
                "sql_validation_outcome": query_execution_asset.get("sql_validation_outcome", "skipped"),
                "sql_review_outcome": query_execution_asset.get("sql_review_outcome", "skipped"),
                "safety_validation_outcome": query_execution_asset.get("safety_validation_outcome", "skipped"),
                "auth_status": _qe_debug.get("auth_status", ""),
                "chart_validation_status": str(query_execution_asset.get("chart_validation_status", "") or ""),
            },
            extra_debug={
                "auth_status": _qe_debug.get("auth_status", ""),
                "execution_status": _qe_debug.get("execution_status", ""),
                "user_safe_message": str(query_execution_asset.get("user_safe_message") or ""),
            },
        ),
    )
    attach_stage(
        trace,
        "query_execution",
        _to_trace_stage(
            status=(
                "skipped"
                if query_execution_asset.get("asset_role") == "sql_ready_asset"
                else str(query_execution_asset.get("status", "unknown"))
            ),
            result=query_execution_asset,
            final_output={
                "execution_result": None,
                "reason": "execution_delegated_to_query_service"
                if query_execution_asset.get("asset_role") == "sql_ready_asset"
                else "",
                "result_preview": query_execution_asset.get("result_preview", {}),
                "referenced_tables": query_execution_asset.get("referenced_tables", []),
                "referenced_columns": query_execution_asset.get("referenced_columns", []),
            },
        ),
    )
    if not stage_allows_progress(query_execution_asset.get("status"), degraded=bool(query_execution_asset.get("degraded"))):
        qe_reason = str(query_execution_asset.get("sql_generation_failure_reason") or "").strip()
        qe_lower = qe_reason.lower()
        user_safe = str(query_execution_asset.get("user_safe_message") or "").strip()
        if not user_safe:
            if "query_service_unauthorized" in qe_lower:
                user_safe = "Query execution failed due to authorization error between services."
            elif "query_service_auth_not_configured" in qe_lower:
                user_safe = "Query execution failed due to missing service authentication configuration."
            elif not str(query_execution_asset.get("generated_sql") or query_execution_asset.get("sql_query") or "").strip():
                user_safe = "SQL generation failed."
            elif "query_service" in qe_lower and "valid" in qe_lower:
                user_safe = "SQL validation failed."
            else:
                user_safe = "Query execution failed."
        fail_message = user_safe or "Query execution failed."
        payload = _build_stage_failed(
            stage="query_execution",
            message=fail_message,
            transcription=transcription_asset,
            preprocess=preprocessing_low_asset,
            intent=intent_classification_asset,
            routing=routing_asset,
            preprocess_high=preprocessing_high_asset,
            intent_extraction=query_execution_asset,
        )
        payload["message"] = fail_message
        trace["user_safe_message"] = fail_message
        attach_stage(
            trace,
            "final_response",
            _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
        )
        return _finalize_response(
            payload=payload,
            overall_status="failed",
            stage="query_execution",
            final_route=str(routing_asset.get("next_step", "metabase")),
            final_user_message=fail_message,
        )

    next_step = str(routing_asset.get("next_step", "metabase")).strip().lower()
    if next_step == "metabase":
        attach_stage(
            trace,
            "forecasting",
            _to_trace_stage(
                status="skipped",
                result=forecasting_asset,
                final_output={
                    "forecast_status": "skipped",
                    "reason": "metabase_route_selected",
                },
            ),
        )
        attach_stage(
            trace,
            "visualization",
            _to_trace_stage(
                status=str(visualization_asset.get("status", "unknown")),
                result=visualization_asset,
                final_output={
                    "visualization_status": visualization_asset.get("visualization_status", visualization_asset.get("status")),
                    "selected_chart_type": visualization_asset.get("selected_chart_type", ""),
                    "reason_chart_selected": visualization_asset.get("reason_chart_selected", ""),
                    "reason_chart_not_generated": visualization_asset.get("reason_chart_not_generated", ""),
                    "chart_locked": bool(visualization_asset.get("chart_locked", False)),
                    "chart_selector_source": visualization_asset.get("chart_selector_source", ""),
                    "chart_selector_model": visualization_asset.get("chart_selector_model", ""),
                    "chart_selector_confidence": visualization_asset.get("chart_selector_confidence", 0.0),
                    "visualization_payload_preview": visualization_asset.get("visualization_payload_preview"),
                },
            ),
        )
        if not stage_allows_progress(visualization_asset.get("status"), degraded=bool(visualization_asset.get("degraded"))):
            payload = _build_stage_failed(
                stage="visualization",
                message="Visualization stage failed.",
                transcription=transcription_asset,
                preprocess=preprocessing_low_asset,
                intent=intent_classification_asset,
                routing=routing_asset,
                preprocess_high=preprocessing_high_asset,
                intent_extraction=query_execution_asset,
            )
            attach_stage(
                trace,
                "final_response",
                _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
            )
            return _finalize_response(
                payload=payload,
                overall_status="failed",
                stage="visualization",
                final_route=next_step,
                final_user_message="Visualization failed after query execution.",
            )
        downstream_result = visualization_asset.get("downstream_result")
    else:
        attach_stage(
            trace,
            "forecasting",
            _to_trace_stage(
                status=str(forecasting_asset.get("status", "unknown")),
                result=forecasting_asset,
                final_output={
                    "forecast_status": forecasting_asset.get("status"),
                    "next_step": forecasting_asset.get("next_step"),
                    "downstream_result": forecasting_asset.get("downstream_result"),
                },
            ),
        )
        predictive_visualization_payload = (
            (forecasting_asset.get("downstream_result", {}) if isinstance(forecasting_asset.get("downstream_result"), dict) else {})
            .get("visualization_payload")
        )
        attach_stage(
            trace,
            "visualization",
            _to_trace_stage(
                status=str(forecasting_asset.get("visualization_status", "success")),
                result=forecasting_asset,
                final_output={
                    "visualization_status": forecasting_asset.get("visualization_status", "success"),
                    "selected_chart_type": forecasting_asset.get("selected_chart_type", "line"),
                    "reason_chart_selected": forecasting_asset.get("reason_chart_selected", ""),
                    "reason_chart_not_generated": forecasting_asset.get("reason_chart_not_generated", ""),
                    "chart_locked": bool(forecasting_asset.get("chart_locked", False)),
                    "chart_selector_source": forecasting_asset.get("chart_selector_source", ""),
                    "chart_selector_model": forecasting_asset.get("chart_selector_model", ""),
                    "chart_selector_confidence": forecasting_asset.get("chart_selector_confidence", 0.0),
                    "visualization_payload_preview": predictive_visualization_payload,
                },
            ),
        )
        forecasting_delegated = (
            str(forecasting_asset.get("status", "")).strip().lower() == "skipped"
            and str(forecasting_asset.get("error_type", "")).strip().lower() == "forecasting_delegated_to_voice_service"
        )
        if not forecasting_delegated and not stage_allows_progress(forecasting_asset.get("status"), degraded=bool(forecasting_asset.get("degraded"))):
            payload = _build_stage_failed(
                stage="forecasting",
                message="Forecasting stage failed.",
                transcription=transcription_asset,
                preprocess=preprocessing_low_asset,
                intent=intent_classification_asset,
                routing=routing_asset,
                preprocess_high=preprocessing_high_asset,
                intent_extraction=query_execution_asset,
            )
            attach_stage(
                trace,
                "final_response",
                _to_trace_stage(status="failed", result=None, final_output=_final_output_snapshot(payload)),
            )
            return _finalize_response(
                payload=payload,
                overall_status="failed",
                stage="forecasting",
                final_route=next_step,
                final_user_message="Forecasting downstream stage failed.",
            )
        downstream_result = forecasting_asset.get("downstream_result")
        visualization_asset = {
            "status": "skipped" if forecasting_delegated else normalize_stage_status(
                forecasting_asset.get("visualization_status", forecasting_asset.get("status", "success")),
                degraded=bool(forecasting_asset.get("degraded")),
            ),
            "degraded": bool(forecasting_asset.get("degraded")),
            "degradation_reason": str(forecasting_asset.get("degradation_reason", "")).strip(),
            "next_step": "forecasting",
            "error_type": "none",
            "action_taken": "proceed",
            "downstream_result": predictive_visualization_payload
            if isinstance(predictive_visualization_payload, dict)
            else {
                "chart_type": "line",
                "mode": "forecasting_delegated_to_voice_service" if forecasting_delegated else "historical_only",
                "message": "Forecasting will run in voice-service." if forecasting_delegated else "Forecast unavailable",
                "series": [],
                "forecast_available": False,
                "fallback_reason": "" if forecasting_delegated else "missing_visualization_payload",
            },
            "visualization_status": "skipped" if forecasting_delegated else forecasting_asset.get("visualization_status", "success"),
            "selected_chart_type": forecasting_asset.get("selected_chart_type", "line"),
            "reason_chart_selected": forecasting_asset.get("reason_chart_selected", ""),
            "reason_chart_not_generated": forecasting_asset.get("reason_chart_not_generated", ""),
            "visualization_payload_preview": predictive_visualization_payload,
            "attempts": forecasting_asset.get("attempts", []),
            "attempts_count": forecasting_asset.get("attempts_count", 0),
            "warnings": forecasting_asset.get("warnings", []),
            "errors": forecasting_asset.get("errors", []),
            "debug_metadata": {
                "derived_from": "forecasting_asset",
                "forecast_meta": (
                    downstream_result.get("forecast_meta", {})
                    if isinstance(downstream_result, dict)
                    else {}
                ),
            },
        }

    intent_extraction_full = {
        "status": normalize_stage_status(
            query_execution_asset.get("status", "success"),
            degraded=bool(query_execution_asset.get("degraded")),
        ),
        "confidence": stage_confidence(query_execution_asset, base_success=0.9, base_degraded=0.55),
        "intent_type": query_execution_asset.get("intent_type", routing_asset.get("intent_type")),
        "sql_query": query_execution_asset.get("sql_query", ""),
        "next_step": next_step,
        "error_type": "none",
        "action_taken": "proceed",
        "extracted_intent": query_execution_asset.get("extracted_intent", {}),
        "normalized_intent": query_execution_asset.get("normalized_intent", {}),
        "execution_result": query_execution_asset.get("execution_result"),
        "downstream_result": downstream_result,
    }

    confidence_payload = pipeline_confidence(
        preprocessing_low=preprocessing_low_asset,
        classification=intent_classification_asset,
        preprocessing_high=preprocessing_high_asset,
        intent_extraction=intent_extraction_asset,
        query_execution=query_execution_asset,
        visualization=visualization_asset,
        forecasting=forecasting_asset,
    )

    payload = {
        "status": "degraded"
        if any(
            bool(stage_payload_obj.get("degraded"))
            for stage_payload_obj in (
                preprocessing_low_asset,
                intent_classification_asset,
                preprocessing_high_asset,
                intent_extraction_asset,
                visualization_asset,
                forecasting_asset,
            )
            if isinstance(stage_payload_obj, dict)
        )
        else "success",
        "degraded": any(
            bool(stage_payload_obj.get("degraded"))
            for stage_payload_obj in (
                preprocessing_low_asset,
                intent_classification_asset,
                preprocessing_high_asset,
                intent_extraction_asset,
                visualization_asset,
                forecasting_asset,
            )
            if isinstance(stage_payload_obj, dict)
        ),
        "degradation_reasons": [
            str(stage_payload_obj.get("degradation_reason", "")).strip()
            for stage_payload_obj in (
                preprocessing_low_asset,
                intent_classification_asset,
                preprocessing_high_asset,
                intent_extraction_asset,
                visualization_asset,
                forecasting_asset,
            )
            if isinstance(stage_payload_obj, dict) and str(stage_payload_obj.get("degradation_reason", "")).strip()
        ],
        "confidence": confidence_payload["score"],
        "confidence_breakdown": confidence_payload,
        "transcription": transcription_asset,
        "preprocess": preprocessing_low_asset,
        "intent": intent_classification_asset,
        "routing": routing_asset,
        "preprocess_high": preprocessing_high_asset,
        "intent_extraction": intent_extraction_full,
        "query_execution": query_execution_asset,
        "visualization": visualization_asset,
        "forecasting": forecasting_asset,
    }
    attach_stage(
        trace,
        "final_response",
        _to_trace_stage(
            status=str(payload.get("status", "success")),
            result=None,
            final_output={
                "status": payload.get("status", "success"),
                "next_step": next_step,
                "intent_type": intent_extraction_full.get("intent_type"),
                "sql_query": intent_extraction_full.get("sql_query"),
                "confidence": payload.get("confidence"),
            },
        ),
    )
    attach_stage(
        trace,
        "dagster_runtime",
        _to_trace_stage(
            status="pending",
            result={},
            final_output={"message": "Dagster runtime will be attached by job runner."},
        ),
    )
    return _finalize_response(
        payload=payload,
        overall_status=str(payload.get("status", "success")),
        stage="final_response",
        final_route=next_step,
        final_user_message=(
            "Pipeline completed with degraded stages."
            if payload.get("status") == "degraded"
            else "Pipeline completed successfully."
        ),
    )


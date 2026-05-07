from __future__ import annotations

from typing import Any

from bi_platform_shared.contracts.chart import ChartTypeEnum

from intent_extraction.error_handler import IntentExtractionSchemaMismatchError
from intent_extraction.schemas import StructuredIntent
from shared.schema_utils import is_numeric_type, unqualify_table_name


_VALID_AGGREGATIONS = {"SUM", "AVG", "COUNT", "MIN", "MAX"}
_VALID_FILTER_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "IN", "LIKE", "BETWEEN"}
_NON_AGGREGATED_COMPARISON_INTENTS = {"comparison", "correlation", "relationship"}
_PERCENTAGE_METRIC_TYPES = {"percentage", "percent", "ratio"}


def _allowed_chart_values() -> set[str]:
    """Phase 5 / CRIT-14: the chart taxonomy is sourced from
    ``ChartTypeEnum`` so adding a new chart in the shared contract
    automatically widens validation here without touching this module."""

    return {member.value for member in ChartTypeEnum}


def _resolve_table_name(
    *,
    requested_table: str,
    schema: dict[str, list[dict[str, Any]]],
    referenced_columns: set[str],
) -> str:
    if requested_table and requested_table in schema:
        return requested_table

    if requested_table:
        requested_unqualified = unqualify_table_name(requested_table).lower()
        matches = [
            table_name
            for table_name in schema.keys()
            if unqualify_table_name(table_name).lower() == requested_unqualified
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise IntentExtractionSchemaMismatchError(
                f"Ambiguous table '{requested_table}'. Matches: {', '.join(matches)}"
            )

    if not schema:
        raise IntentExtractionSchemaMismatchError("Schema is empty.")

    if referenced_columns:
        best_table = ""
        best_score = -1
        for table_name, columns in schema.items():
            column_names = {str(col.get("name", "")).strip() for col in columns}
            score = len(referenced_columns & column_names)
            if score > best_score:
                best_score = score
                best_table = table_name
        if best_table:
            return best_table

    # Deterministic fallback so routing can continue when table is omitted by model.
    return sorted(schema.keys())[0]


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _pick_default_metric(table_columns: list[dict[str, Any]]) -> str:
    for column in table_columns:
        col_name = str(column.get("name", "")).strip()
        if not col_name:
            continue
        if is_numeric_type(str(column.get("type", ""))):
            return col_name
    return "*"


def _normalize_limit_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            parsed = int(raw)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _derive_operations(
    *,
    metric_specs: list[dict[str, Any]],
    dimensions: list[str],
    filters: list[dict[str, Any]],
    order_by: list[dict[str, str]],
    limit: int | None,
) -> list[str]:
    operations: list[str] = ["projection"]
    if any(spec.get("aggregation") for spec in metric_specs):
        operations.append("aggregation")
    if dimensions:
        operations.append("grouping")
    if filters:
        operations.append("filtering")
    if order_by:
        operations.append("ranking")
    if limit:
        operations.append("limiting")
    if dimensions and len(metric_specs) > 1:
        operations.append("comparison")
    return operations


def _derive_primary_intent(operations: list[str]) -> str:
    if "ranking" in operations:
        return "ranking"
    if "aggregation" in operations and "grouping" in operations:
        return "aggregation"
    if "filtering" in operations:
        return "filtering"
    return "projection"


def _normalized_metric_type(intent: StructuredIntent) -> str:
    direct = str(intent.get("metric_type", "")).strip().lower()
    if direct in _PERCENTAGE_METRIC_TYPES:
        return "percentage"
    if direct in {"absolute", "count", "sum"}:
        return "absolute"
    chart_payload = intent.get("chart") if isinstance(intent.get("chart"), dict) else {}
    chart_metric_type = str(chart_payload.get("metric_type", "")).strip().lower()
    if chart_metric_type in _PERCENTAGE_METRIC_TYPES:
        return "percentage"
    if chart_metric_type in {"absolute", "count", "sum"}:
        return "absolute"
    return ""


def _normalized_chart_contract(intent: StructuredIntent, dimensions: list[str], metric_type: str) -> dict[str, Any]:
    chart_payload = intent.get("chart") if isinstance(intent.get("chart"), dict) else {}
    chart_type = (
        str(intent.get("selected_chart_type", "")).strip().lower()
        or str(intent.get("chart_type", "")).strip().lower()
        or str(chart_payload.get("type", "")).strip().lower()
    )
    group_by = str(chart_payload.get("group_by", "")).strip() or (dimensions[0] if dimensions else "")
    if metric_type == "percentage" and not chart_type:
        chart_type = "pie"
    chart_metric_type = str(chart_payload.get("metric_type", "")).strip().lower() or metric_type
    return {
        "type": chart_type or None,
        "metric_type": chart_metric_type or None,
        "group_by": group_by or None,
    }


def _infer_semantic_flags(intent: StructuredIntent, metric_type: str) -> dict[str, bool]:
    text_blob = " ".join(
        [
            str(intent.get("intent", "")).strip().lower(),
            str(intent.get("intent_type", "")).strip().lower(),
            str(metric_type or "").strip().lower(),
            " ".join(str(op).strip().lower() for op in (intent.get("operations", []) or []) if str(op).strip()),
        ]
    )
    is_percentage = metric_type == "percentage" or any(token in text_blob for token in ("percent", "percentage", "share", "ratio"))
    is_distribution = "distribution" in text_blob or "histogram" in text_blob or "frequency" in text_blob or "spread" in text_blob
    is_time_series = (
        bool(intent.get("time_grouping_detected"))
        or bool(intent.get("group_by_time"))
        or bool(intent.get("is_time_series"))
        or str(intent.get("time_granularity", "")).strip().lower() in {"hour", "day", "week", "month", "quarter", "year"}
        or "time_series" in text_blob
        or "trend" in text_blob
    )
    return {
        "is_percentage": bool(is_percentage),
        "is_distribution": bool(is_distribution),
        "is_time_series": bool(is_time_series),
    }


def _supports_hour_column_type(col_type: str) -> bool:
    normalized = str(col_type or "").strip().lower()
    return ("datetime" in normalized) or ("timestamp" in normalized) or ("time" in normalized and "date" in normalized)


def validate_structured_intent(
    *,
    intent: StructuredIntent,
    schema: dict[str, list[dict[str, Any]]],
) -> StructuredIntent:
    metrics = [str(item).strip() for item in intent.get("metrics", []) if str(item).strip()]
    dimensions = [str(item).strip() for item in intent.get("dimensions", []) if str(item).strip()]
    filters = intent.get("filters", []) or []
    metric_specs = intent.get("metric_specs", []) or []
    order_by = intent.get("order_by", []) or []
    limit = _normalize_limit_value(intent.get("limit"))
    target_column = str(intent.get("target_column", "")).strip()
    requested_table = str(intent.get("table", "")).strip()

    referenced_columns = set(metrics + dimensions)
    if target_column:
        referenced_columns.add(target_column)
    for flt in filters:
        if isinstance(flt, dict):
            column = str(flt.get("column", "")).strip()
            if column:
                referenced_columns.add(column)
    for metric in metric_specs:
        if isinstance(metric, dict):
            column = str(metric.get("column", "")).strip()
            if column:
                referenced_columns.add(column)
    for order_item in order_by:
        if isinstance(order_item, dict):
            column = str(order_item.get("column", "")).strip()
            if column:
                referenced_columns.add(column)

    resolved_table = _resolve_table_name(
        requested_table=requested_table,
        schema=schema,
        referenced_columns=referenced_columns,
    )
    table_columns = schema.get(resolved_table, [])
    if not table_columns:
        raise IntentExtractionSchemaMismatchError(
            f"Table '{resolved_table}' not found in schema."
        )

    column_map = {str(col.get("name", "")).strip(): col for col in table_columns}
    available_columns = set(column_map.keys())

    unknown_metrics = [metric for metric in metrics if metric != "*" and metric not in available_columns]
    unknown_dimensions = [dim for dim in dimensions if dim not in available_columns]
    unknown_filters = [
        str(flt.get("column", "")).strip()
        for flt in filters
        if isinstance(flt, dict)
        and str(flt.get("column", "")).strip()
        and str(flt.get("column", "")).strip() not in available_columns
    ]
    unknown_metric_specs = [
        str(metric.get("column", "")).strip()
        for metric in metric_specs
        if isinstance(metric, dict)
        and str(metric.get("column", "")).strip()
        and str(metric.get("column", "")).strip() != "*"
        and str(metric.get("column", "")).strip() not in available_columns
    ]

    if unknown_metrics or unknown_dimensions or unknown_filters or unknown_metric_specs:
        unknown_chunks: list[str] = []
        if unknown_metrics:
            unknown_chunks.append(f"metrics={unknown_metrics}")
        if unknown_dimensions:
            unknown_chunks.append(f"dimensions={unknown_dimensions}")
        if unknown_filters:
            unknown_chunks.append(f"filters={unknown_filters}")
        if unknown_metric_specs:
            unknown_chunks.append(f"metric_specs={unknown_metric_specs}")
        raise IntentExtractionSchemaMismatchError(
            "Schema mismatch for extracted intent columns: " + ", ".join(unknown_chunks)
        )

    if target_column and target_column != "*" and target_column not in available_columns:
        raise IntentExtractionSchemaMismatchError(
            f"Target column '{target_column}' does not exist in table '{resolved_table}'."
        )

    if not metrics and target_column:
        metrics = [target_column]
    if not metrics:
        metrics = [_pick_default_metric(table_columns)]

    metrics = _dedupe_preserve_order(metrics)
    dimensions = _dedupe_preserve_order(dimensions)

    aggregation = str(intent.get("aggregation", "")).strip().upper()
    if aggregation not in _VALID_AGGREGATIONS:
        aggregation = ""

    primary_metric = metrics[0] if metrics else ""

    normalized_filters: list[dict[str, Any]] = []
    for flt in filters:
        if not isinstance(flt, dict):
            continue
        column = str(flt.get("column", "")).strip()
        if not column:
            continue
        operator = str(flt.get("operator", "=")).strip().upper() or "="
        if operator not in _VALID_FILTER_OPERATORS:
            operator = "="
        normalized_filters.append(
            {
                "column": column,
                "operator": operator,
                "value": flt.get("value"),
            }
        )

    normalized_metric_specs: list[dict[str, Any]] = []
    for metric in metric_specs:
        if not isinstance(metric, dict):
            continue
        column = str(metric.get("column", "")).strip()
        if not column:
            continue
        aggregation_hint = str(metric.get("aggregation", "")).strip().upper() or None
        if aggregation_hint and aggregation_hint not in _VALID_AGGREGATIONS:
            aggregation_hint = None
        alias = metric.get("alias")
        alias_str = str(alias).strip() if isinstance(alias, str) and alias.strip() else None
        normalized_metric_specs.append(
            {
                "column": column,
                "aggregation": aggregation_hint,
                "alias": alias_str,
            }
        )

    if not aggregation and normalized_metric_specs:
        inferred_aggregations = [
            str(spec.get("aggregation", "")).strip().upper()
            for spec in normalized_metric_specs
            if str(spec.get("aggregation", "")).strip().upper() in _VALID_AGGREGATIONS
        ]
        if len(set(inferred_aggregations)) == 1 and inferred_aggregations:
            aggregation = inferred_aggregations[0]

    requested_intent = str(intent.get("intent", "")).strip().lower()
    requested_operations = {
        str(op).strip().lower()
        for op in (intent.get("operations", []) or [])
        if str(op).strip()
    }
    has_metric_aggregation_hints = bool(
        aggregation
        or any(
            str(spec.get("aggregation", "")).strip().upper() in _VALID_AGGREGATIONS
            for spec in normalized_metric_specs
            if isinstance(spec, dict)
        )
    )
    comparison_without_aggregation = (
        requested_intent in _NON_AGGREGATED_COMPARISON_INTENTS
        or "comparison" in requested_operations
    ) and len(metrics) >= 2 and not has_metric_aggregation_hints

    if not aggregation and not comparison_without_aggregation:
        aggregation = "SUM"
    if primary_metric == "*":
        aggregation = "COUNT"
    elif primary_metric:
        metric_type = str(column_map[primary_metric].get("type", ""))
        if aggregation in {"SUM", "AVG", "MIN", "MAX"} and not is_numeric_type(metric_type):
            aggregation = "COUNT"

    normalized_order_by: list[dict[str, str]] = []
    for order_item in order_by:
        if not isinstance(order_item, dict):
            continue
        column = str(order_item.get("column", "")).strip()
        if not column:
            continue
        direction = str(order_item.get("direction", "ASC")).strip().upper() or "ASC"
        if direction not in {"ASC", "DESC"}:
            direction = "ASC"
        normalized_order_by.append({"column": column, "direction": direction})

    normalized_limit = limit

    normalized_target = target_column or primary_metric
    normalized_metric_type = _normalized_metric_type(intent)
    chart_contract = _normalized_chart_contract(intent, dimensions, normalized_metric_type)
    if not normalized_metric_type:
        normalized_metric_type = str(chart_contract.get("metric_type") or "").strip().lower()
    allowed_chart_values = _allowed_chart_values()
    candidate_chart_type = (
        str(intent.get("selected_chart_type", "")).strip().lower()
        or str(intent.get("chart_type", "")).strip().lower()
        or str(chart_contract.get("type") or "").strip().lower()
    )
    selected_chart_type = candidate_chart_type if candidate_chart_type in allowed_chart_values else ""
    if not chart_contract.get("type") and selected_chart_type:
        chart_contract["type"] = selected_chart_type
    if normalized_metric_type == "percentage" and not selected_chart_type:
        selected_chart_type = ChartTypeEnum.PIE.value
        chart_contract["type"] = ChartTypeEnum.PIE.value
    if normalized_metric_type and not chart_contract.get("metric_type"):
        chart_contract["metric_type"] = normalized_metric_type
    time_granularity = str(intent.get("time_granularity", "")).strip().lower()
    time_column = str(intent.get("time_column", "")).strip()
    if time_granularity == "hour":
        candidate_time_column = time_column
        if not candidate_time_column:
            for col in table_columns:
                candidate_name = str(col.get("name", "")).strip()
                if not candidate_name:
                    continue
                if _supports_hour_column_type(str(col.get("type", ""))):
                    candidate_time_column = candidate_name
                    break
        if not candidate_time_column:
            raise IntentExtractionSchemaMismatchError("Granularity not supported: hour-level data not available")
        candidate_type = str(column_map.get(candidate_time_column, {}).get("type", ""))
        if not _supports_hour_column_type(candidate_type):
            raise IntentExtractionSchemaMismatchError("Granularity not supported: hour-level data not available")

    ranking_payload = intent.get("ranking") if isinstance(intent.get("ranking"), dict) else {}
    ranking_direction = str(ranking_payload.get("direction", "")).strip().upper()
    if ranking_direction not in {"ASC", "DESC"}:
        ranking_direction = ""

    if ranking_direction and not normalized_order_by:
        first_order_column = (
            (normalized_metric_specs[0].get("alias") if normalized_metric_specs else None)
            or (normalized_metric_specs[0].get("column") if normalized_metric_specs else None)
            or (metrics[0] if metrics else "")
        )
        if isinstance(first_order_column, str) and first_order_column.strip():
            normalized_order_by = [{"column": first_order_column.strip(), "direction": ranking_direction}]
    if ranking_direction and normalized_limit is None:
        normalized_limit = 1
    if normalized_limit is not None and not normalized_order_by and metrics:
        normalized_order_by = [{"column": metrics[0], "direction": "DESC"}]

    operations = intent.get("operations") if isinstance(intent.get("operations"), list) else []
    if not operations:
        operations = _derive_operations(
            metric_specs=normalized_metric_specs,
            dimensions=dimensions,
            filters=normalized_filters,
            order_by=normalized_order_by,
            limit=normalized_limit,
        )
    normalized_intent_name = str(intent.get("intent", "")).strip()
    if not normalized_intent_name:
        normalized_intent_name = _derive_primary_intent(operations)
    normalized_ranking = {
        "direction": ranking_direction or (normalized_order_by[0]["direction"] if normalized_order_by else None),
        "requested": bool(ranking_direction or normalized_order_by),
        "source": ranking_payload.get("source", "validation"),
    }
    semantic_flags = _infer_semantic_flags(intent, normalized_metric_type)
    operation_set = {str(op).strip().lower() for op in operations if str(op).strip()}
    relationship_semantic = "relationship" in operation_set or requested_intent in {"correlation", "relationship"}
    if semantic_flags["is_distribution"] or "distribution" in operation_set:
        selected_chart_type = ChartTypeEnum.HISTOGRAM.value
        chart_contract["type"] = ChartTypeEnum.HISTOGRAM.value
    elif semantic_flags["is_percentage"] and selected_chart_type == ChartTypeEnum.PIE.value:
        chart_contract["type"] = ChartTypeEnum.PIE.value
    elif semantic_flags["is_time_series"] and len(metrics) > 1:
        selected_chart_type = ChartTypeEnum.LINE_MULTI.value
        chart_contract["type"] = ChartTypeEnum.LINE_MULTI.value
    elif semantic_flags["is_time_series"]:
        selected_chart_type = ChartTypeEnum.LINE.value
        chart_contract["type"] = ChartTypeEnum.LINE.value
    elif relationship_semantic:
        selected_chart_type = ChartTypeEnum.SCATTER.value
        chart_contract["type"] = ChartTypeEnum.SCATTER.value
    else:
        selected_chart_type = selected_chart_type or (
            ChartTypeEnum.PIE.value if semantic_flags["is_percentage"] else ""
        )

    chart_lock = bool(intent.get("chart_lock", False))
    explicit_chart_lock = bool(intent.get("explicit_chart_lock", False))
    if relationship_semantic or (
        semantic_flags["is_time_series"] and len(metrics) > 1
    ) or semantic_flags["is_percentage"] or semantic_flags["is_distribution"]:
        chart_lock = True
        explicit_chart_lock = True

    x_axis = dimensions[0] if dimensions else ""
    y_axis = [
        metric.get("alias") or metric.get("column")
        for metric in normalized_metric_specs
        if isinstance(metric, dict) and (metric.get("alias") or metric.get("column"))
    ]
    if relationship_semantic and len(metrics) >= 2:
        x_axis = metrics[0]
        y_axis = [metrics[1]]
    if semantic_flags["is_time_series"] and len(metrics) > 1:
        x_axis = str(intent.get("time_dimension_alias") or "date")
        y_axis = [
            metric.get("alias") or metric.get("column")
            for metric in normalized_metric_specs
            if isinstance(metric, dict) and (metric.get("alias") or metric.get("column"))
        ]

    return {
        "intent_type": intent["intent_type"],
        "intent": normalized_intent_name,
        "metrics": metrics,
        "metric_specs": normalized_metric_specs,
        "dimensions": dimensions,
        "filters": normalized_filters,
        "time_range": str(intent.get("time_range", "all_time")).strip() or "all_time",
        "aggregation": aggregation,
        "target_column": normalized_target,
        "table": resolved_table,
        "order_by": normalized_order_by,
        "limit": normalized_limit,
        "time_granularity": time_granularity,
        "time_column": time_column,
        "time_grouping_detected": bool(
            time_granularity in {"hour", "day", "week", "month", "quarter", "year"}
            or intent.get("time_grouping_detected")
            or intent.get("group_by_time")
        ),
        "ranking": normalized_ranking,
        "operations": operations,
        "ambiguities": intent.get("ambiguities") if isinstance(intent.get("ambiguities"), list) else [],
        "chart": chart_contract,
        "metric_type": normalized_metric_type,
        "selected_chart_type": selected_chart_type,
        "chart_type": selected_chart_type,
        "final_chart_type": selected_chart_type,
        "chart_lock": chart_lock,
        "explicit_chart_lock": explicit_chart_lock,
        "chart_reason": str(intent.get("chart_reason", "")).strip(),
        "chart_reason_code": str(intent.get("chart_reason_code", "")).strip() or "intent_validation_default",
        "x_axis": x_axis,
        "y_axis": y_axis,
        **semantic_flags,
    }

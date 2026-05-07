from __future__ import annotations

import copy
import re
from typing import Any

from shared.analytical_time_semantics import apply_deterministic_analytical_time_repair, question_requests_analytical_time
from shared.query_planner import normalize_analytical_intent
from shared.schema_utils import is_date_type, is_numeric_type


TIME_TOKENS = (
    "over time",
    "by date",
    "through time",
    "across time",
    "across periods",
    "time series",
    "trend",
    "trends",
    "progression",
    "progressions",
    "chronological",
    "timeline",
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "yearly",
    "annually",
    "month over month",
    "year over year",
    "mom",
    "yoy",
    "each day",
    "each week",
    "each month",
    "each quarter",
    "each year",
)
MONTH_TOKENS = ("by month", "across months", "monthly", "per month", "month over month")
WEEK_TOKENS = ("by week", "across weeks", "weekly", "per week")
DAY_TOKENS = ("by day", "across days", "daily", "per day")
YEAR_TOKENS = ("by year", "across years", "yearly", "annual", "annually", "per year")
RELATIONSHIP_TOKENS = ("relationship", "correlation", "association", "between", " versus ", " vs ", " relate ")
DISTRIBUTION_TOKENS = ("distribution", "distributed", "histogram", "spread", "frequency")
COMPARISON_TOKENS = ("compare", "comparison", "compared", "versus", " vs ", "across")
RANKING_TOKENS = (
    "top",
    "bottom",
    "highest",
    "lowest",
    "largest",
    "smallest",
    "most",
    "least",
    "best",
    "worst",
)
PERCENTAGE_TOKENS = ("share", "percentage", "percent", "contribution", "proportion")
GROUPING_TOKENS = (" by ", " across ", " per ", "for each", "in each")

_EXPLICIT_CHART_PATTERNS: tuple[tuple[str, str], ...] = (
    ("scatter plot", "scatter"),
    ("scatter chart", "scatter"),
    ("scatter", "scatter"),
    ("pie chart", "pie"),
    ("pie", "pie"),
    ("line chart", "line"),
    ("line", "line"),
    ("bar chart", "bar"),
    ("bar", "bar"),
    ("histogram", "histogram"),
    ("table", "table"),
    ("card", "card"),
    ("kpi", "card"),
)


def _question_has_any(question: str, tokens: tuple[str, ...]) -> bool:
    lowered = f" {str(question or '').strip().lower()} "
    return any(token in lowered for token in tokens)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        cleaned = str(item or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def _metric_columns(intent: dict[str, Any]) -> list[str]:
    metrics = intent.get("metrics") if isinstance(intent.get("metrics"), list) else []
    result: list[str] = []
    for metric in metrics:
        if isinstance(metric, dict):
            column = str(metric.get("column", "")).strip()
        else:
            column = str(metric or "").strip()
        if column and column != "*" and column not in result:
            result.append(column)
    return result


def _as_metric_specs(metrics: list[dict[str, Any]], fallback_aggregation: str | None) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        column = str(metric.get("column", "")).strip()
        if not column:
            continue
        aggregation = metric.get("aggregation") if metric.get("aggregation") is not None else fallback_aggregation
        specs.append(
            {
                "column": column,
                "aggregation": aggregation,
                "alias": metric.get("alias"),
            }
        )
    return specs


def _sql_has_group_by(sql: str) -> bool:
    return bool(re.search(r"\bGROUP\s+BY\b", str(sql or ""), flags=re.IGNORECASE))


def _schema_column_info(schema: dict[str, list[dict[str, Any]]] | None) -> dict[str, Any]:
    info: dict[str, Any] = {
        "all": [],
        "numeric": [],
        "time": [],
        "categorical": [],
        "lookup": {},
        "table_by_column": {},
    }
    if not isinstance(schema, dict):
        return info

    for table_name, columns in schema.items():
        if not isinstance(columns, list):
            continue
        for column in columns:
            if not isinstance(column, dict):
                continue
            name = str(column.get("name", "")).strip()
            if not name:
                continue
            if name not in info["all"]:
                info["all"].append(name)
            info["lookup"].setdefault(name.lower(), name)
            info["lookup"].setdefault(name.lower().replace("_", " "), name)
            info["table_by_column"].setdefault(name, str(table_name))

            column_type = str(column.get("type", "")).strip()
            lowered_name = name.lower()
            is_time_col = bool(
                is_date_type(column_type)
                or lowered_name in {"ds", "date", "timestamp", "created_at", "order_date"}
                or lowered_name.endswith(("_date", "_time", "_at"))
                or any(token in lowered_name for token in ("date", "time", "week", "month", "year"))
            )
            is_numeric_col = bool(is_numeric_type(column_type))

            if is_numeric_col and name not in info["numeric"]:
                info["numeric"].append(name)
            if is_time_col and name not in info["time"]:
                info["time"].append(name)
            if not is_numeric_col and not is_time_col and name not in info["categorical"]:
                info["categorical"].append(name)

    return info


def _resolve_selected_columns(selected_columns: list[str] | None, schema_info: dict[str, Any]) -> list[str]:
    resolved: list[str] = []
    for item in selected_columns or []:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        if cleaned in schema_info.get("all", []):
            resolved.append(cleaned)
            continue
        mapped = schema_info.get("lookup", {}).get(cleaned.lower())
        if mapped:
            resolved.append(mapped)
            continue
        mapped = schema_info.get("lookup", {}).get(cleaned.lower().replace("_", " "))
        if mapped:
            resolved.append(mapped)
    return _dedupe(resolved)


def _question_mentions_column(question: str, column_name: str) -> bool:
    q = f" {str(question or '').strip().lower()} "
    normalized = str(column_name or "").strip().lower()
    if not normalized:
        return False
    spaced = normalized.replace("_", " ")
    return bool(
        re.search(rf"\b{re.escape(normalized)}\b", q)
        or re.search(rf"\b{re.escape(spaced)}\b", q)
    )


def _infer_time_grain(question: str, default: str = "") -> str:
    if _question_has_any(question, MONTH_TOKENS):
        return "month"
    if _question_has_any(question, WEEK_TOKENS):
        return "week"
    if _question_has_any(question, DAY_TOKENS):
        return "day"
    if _question_has_any(question, YEAR_TOKENS):
        return "year"
    if _question_has_any(question, TIME_TOKENS):
        return default or "day"
    return default


def _infer_explicit_chart_request(question: str) -> str:
    lowered = f" {str(question or '').strip().lower()} "
    for token, chart_type in _EXPLICIT_CHART_PATTERNS:
        if token in lowered:
            return chart_type
    return ""


def _pick_time_column(intent: dict[str, Any], schema_info: dict[str, Any], selected_columns: list[str]) -> str:
    current = str(intent.get("time_column", "")).strip()
    if current:
        return current

    for col in selected_columns:
        if col in schema_info.get("time", []):
            return col

    preferred = ["ds", "date", "order_date", "timestamp", "created_at"]
    time_columns = schema_info.get("time", [])
    for token in preferred:
        for col in time_columns:
            if col.lower() == token:
                return col
    return time_columns[0] if time_columns else ""


def _pick_group_dimension(intent: dict[str, Any], schema_info: dict[str, Any], selected_columns: list[str]) -> str:
    dimensions = [str(dim).strip() for dim in (intent.get("dimensions") if isinstance(intent.get("dimensions"), list) else []) if str(dim).strip()]
    if dimensions:
        return dimensions[0]

    for col in selected_columns:
        if col in schema_info.get("categorical", []):
            return col

    categorical = schema_info.get("categorical", [])
    return categorical[0] if categorical else ""


def _ensure_metric_specs(
    intent: dict[str, Any],
    *,
    aggregated: bool,
    aggregation: str = "SUM",
) -> None:
    metric_columns = _metric_columns(intent)
    specs = intent.get("metric_specs") if isinstance(intent.get("metric_specs"), list) else []
    specs_by_column: dict[str, dict[str, Any]] = {}
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        column = str(spec.get("column", "")).strip()
        if not column:
            continue
        specs_by_column[column] = dict(spec)

    repaired_specs: list[dict[str, Any]] = []
    for column in metric_columns:
        spec = specs_by_column.get(column, {"column": column})
        if aggregated and not spec.get("aggregation") and column != "*":
            spec["aggregation"] = aggregation
            spec["alias"] = spec.get("alias") or f"{aggregation.lower()}_{column}"
        if not aggregated and spec.get("aggregation") in {"", None}:
            spec["aggregation"] = None
            spec["alias"] = spec.get("alias") or column
        repaired_specs.append(spec)

    intent["metric_specs"] = repaired_specs
    if aggregated:
        intent["aggregation"] = intent.get("aggregation") or aggregation


def _chart_for_intent(intent: dict[str, Any], question: str = "") -> str:
    metrics = _metric_columns(intent)
    operations = {
        str(op).strip().lower()
        for op in (intent.get("operations", []) if isinstance(intent.get("operations"), list) else [])
        if str(op).strip()
    }
    is_time = bool(intent.get("time_grouping_detected") or intent.get("is_time_series") or intent.get("time_granularity"))
    is_distribution = bool(intent.get("is_distribution") or "distribution" in operations or _question_has_any(question, DISTRIBUTION_TOKENS))
    is_relationship = bool("relationship" in operations or "correlation" in str(intent.get("intent", "")).lower())
    is_relationship = is_relationship or (
        _question_has_any(question, RELATIONSHIP_TOKENS)
        and len(metrics) >= 2
        and not is_time
    )
    is_percentage = bool(intent.get("is_percentage") or str(intent.get("metric_type", "")).strip().lower() == "percentage")
    dimensions = intent.get("dimensions") if isinstance(intent.get("dimensions"), list) else []

    explicit_chart = _infer_explicit_chart_request(question)
    if explicit_chart:
        return explicit_chart

    if is_relationship:
        return "scatter"
    if is_distribution:
        return "pie" if is_percentage else "histogram"
    if is_time and len(metrics) > 1:
        return "line_multi"
    if is_time:
        return "line"
    if dimensions and metrics:
        if is_percentage:
            return "pie"
        if len(metrics) > 1:
            return "bar_grouped"
        return "bar"
    if len(metrics) == 1 and not dimensions:
        return "card"
    return "table"


def recover_intent_from_question(
    *,
    question: str,
    schema: dict[str, list[dict[str, Any]]],
    raw_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_analytical_intent(question=question, raw_intent=raw_intent or {}, schema=schema)
    metrics = [m for m in normalized.get("metrics", []) if isinstance(m, dict)]
    metric_columns = [str(m.get("column", "")).strip() for m in metrics if str(m.get("column", "")).strip()]
    aggregation = str(normalized.get("aggregation") or "").strip().upper() or None
    if normalized.get("time_grouping_detected") and not aggregation:
        aggregation = "SUM"
        for metric in metrics:
            if isinstance(metric, dict) and not metric.get("aggregation") and metric.get("column") != "*":
                metric["aggregation"] = "SUM"
                metric["alias"] = metric.get("alias") or f"sum_{metric.get('column')}"
    recovered = {
        **(raw_intent or {}),
        "intent_type": "analytical",
        "intent": normalized.get("intent", "projection"),
        "table": normalized.get("table", ""),
        "metrics": metric_columns or ["*"],
        "metric_specs": _as_metric_specs(metrics, aggregation),
        "dimensions": normalized.get("dimensions", []) or [],
        "filters": normalized.get("filters", []) or [],
        "aggregation": normalized.get("aggregation"),
        "target_column": metric_columns[0] if metric_columns else "*",
        "order_by": normalized.get("order_by", []) or [],
        "limit": normalized.get("limit"),
        "ranking": normalized.get("ranking", {}) if isinstance(normalized.get("ranking"), dict) else {},
        "operations": normalized.get("operations", []) if isinstance(normalized.get("operations"), list) else [],
        "time_granularity": normalized.get("time_granularity", ""),
        "time_column": normalized.get("time_column", ""),
        "time_grouping_detected": bool(normalized.get("time_grouping_detected")),
        "time_dimension_expression": normalized.get("time_dimension_expression", ""),
        "time_dimension_alias": normalized.get("time_dimension_alias", ""),
        "is_time_series": bool(normalized.get("is_time_series") or normalized.get("time_grouping_detected")),
        "is_distribution": bool(normalized.get("is_distribution")),
        "is_percentage": bool(normalized.get("is_percentage")),
        "metric_type": normalized.get("metric_type", ""),
        "x_axis": normalized.get("x_axis", ""),
        "y_axis": normalized.get("y_axis", []),
        "chart_reason_code": "semantic_contract_recovery",
        "chart_reason": "semantic contract recovered intent from question",
    }
    chart_type = _chart_for_intent(recovered, question)
    recovered["selected_chart_type"] = chart_type
    recovered["chart_type"] = chart_type
    recovered["final_chart_type"] = chart_type
    recovered["chart"] = {
        "type": chart_type,
        "metric_type": recovered.get("metric_type") or None,
        "group_by": recovered.get("x_axis") or None,
    }
    return recovered


def validate_semantic_contract(
    *,
    question: str,
    intent: dict[str, Any],
    schema: dict[str, list[dict[str, Any]]] | None = None,
    sql: str = "",
    chart_type: str = "",
    preprocess_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_snapshot = copy.deepcopy(intent or {})
    repaired = dict(intent or {})
    _hints = preprocess_hints if isinstance(preprocess_hints, dict) else {}
    oq = str(_hints.get("original_user_question") or _hints.get("original_query_for_intent") or "").strip()
    base_q = str(question or "").strip()
    semantic_q = base_q
    if question_requests_analytical_time(oq):
        semantic_q = oq
    elif question_requests_analytical_time(base_q):
        semantic_q = base_q
    combined_for_columns = f"{base_q} {oq}".strip()
    input_metrics_are_objects = any(
        isinstance(item, dict)
        for item in (repaired.get("metrics") if isinstance(repaired.get("metrics"), list) else [])
    )
    repairs: list[str] = []

    schema_info = _schema_column_info(schema or {})
    selected_columns = _resolve_selected_columns(
        (preprocess_hints or {}).get("selected_columns") if isinstance(preprocess_hints, dict) else [],
        schema_info,
    )

    recovered: dict[str, Any] = {}
    if schema:
        try:
            recovered = recover_intent_from_question(question=semantic_q, schema=schema, raw_intent=repaired)
        except Exception:
            recovered = {}

    if recovered:
        recovered_metrics = _metric_columns(recovered)
        current_metrics = _metric_columns(repaired)
        if len(recovered_metrics) > len(current_metrics):
            repaired.update(recovered)
            repairs.append("recovered_missing_metrics_from_rules")
        if recovered.get("time_grouping_detected") and not repaired.get("time_grouping_detected"):
            repaired.update(recovered)
            repairs.append("recovered_time_grouping_from_rules")

    question_lower = f" {semantic_q.lower()} "
    combined_lower = f" {combined_for_columns.lower()} "
    current_metrics = _metric_columns(repaired)

    # Rule A + preprocessing-high preservation: if selected numeric columns are explicitly mentioned, keep them.
    required_metrics: list[str] = list(current_metrics)
    for candidate in selected_columns + schema_info.get("numeric", []):
        if candidate not in schema_info.get("numeric", []):
            continue
        if _question_mentions_column(combined_lower, candidate) and candidate not in required_metrics:
            required_metrics.append(candidate)
            repairs.append(f"added_missing_metric:{candidate}")

    if " and " in combined_lower and len(required_metrics) == 1:
        for candidate in selected_columns:
            if candidate in schema_info.get("numeric", []) and candidate not in required_metrics:
                required_metrics.append(candidate)
                repairs.append(f"added_conjunctive_metric:{candidate}")
            if len(required_metrics) >= 2:
                break

    relationship_requested = _question_has_any(combined_for_columns, RELATIONSHIP_TOKENS)
    qlower = question_lower
    time_regex = bool(
        re.search(r"\b(per|by)\s+(day|week|month|quarter|year|hour)\b", combined_lower)
        or re.search(r"\b(from|between)\s+\d{4}\b", combined_lower)
    )
    time_requested = bool(_question_has_any(semantic_q, TIME_TOKENS) or _infer_time_grain(semantic_q) or time_regex)
    if relationship_requested and not time_requested and len(required_metrics) < 2:
        for candidate in selected_columns + schema_info.get("numeric", []):
            if candidate in required_metrics:
                continue
            required_metrics.append(candidate)
            repairs.append(f"added_relationship_metric:{candidate}")
            if len(required_metrics) >= 2:
                break

    if required_metrics:
        repaired["metrics"] = _dedupe(required_metrics)
        repaired["target_column"] = repaired["metrics"][0]

    operations = repaired.get("operations") if isinstance(repaired.get("operations"), list) else []
    operation_set = {str(op).strip().lower() for op in operations if str(op).strip()}

    # Global normalization: predictive language always forces predictive intent.
    predictive_phrase = bool(
        re.search(r"\b(predict|forecast|projection for next|next\s+\d+\s+(day|week|month|quarter|year))\b", combined_lower)
    )
    if predictive_phrase or bool(repaired.get("requires_forecast")):
        repaired["intent_type"] = "predictive"
        repaired["question_type"] = "predictive"
        repaired["requires_forecast"] = True
        repairs.append("forced_predictive_intent")

    # Rules B/C/D/E + selected time column preservation.
    inferred_grain = _infer_time_grain(semantic_q, str(repaired.get("time_granularity", "")).strip().lower())
    if time_requested:
        time_column = _pick_time_column(repaired, schema_info, selected_columns)
        if time_column:
            repaired["time_column"] = time_column
            repaired["time_dimension"] = "ds"
            repaired["group_by_time"] = True
            if inferred_grain:
                repaired["time_granularity"] = inferred_grain
            repaired["time_grouping_detected"] = True
            repaired["is_time_series"] = True
            repaired["time_dimension_alias"] = str(repaired.get("time_dimension_alias") or "date")
            if "time_grouping" not in operation_set:
                operations.append("time_grouping")
                operation_set.add("time_grouping")
            if "grouping" not in operation_set:
                operations.append("grouping")
                operation_set.add("grouping")
            repaired["order_by"] = [{"column": str(repaired.get("time_dimension_alias") or "date"), "direction": "ASC"}]
            repairs.append("enforced_time_grouping")

    # Rule G + K/L safeguards for percentage/share semantics.
    percentage_requested = _question_has_any(combined_for_columns, PERCENTAGE_TOKENS)
    explicit_pie_requested = _infer_explicit_chart_request(combined_for_columns) == "pie"
    grouping_requested = any(token in combined_lower for token in GROUPING_TOKENS)
    if percentage_requested:
        repaired["metric_type"] = "percentage"
        repaired["is_percentage"] = True
        if "distribution" not in operation_set:
            operations.append("distribution")
            operation_set.add("distribution")
        if grouping_requested and not repaired.get("time_grouping_detected"):
            dimension = _pick_group_dimension(repaired, schema_info, selected_columns)
            if dimension:
                dimensions = repaired.get("dimensions") if isinstance(repaired.get("dimensions"), list) else []
                if dimension not in dimensions:
                    dimensions.append(dimension)
                    repaired["dimensions"] = _dedupe(dimensions)
                    repairs.append(f"added_percentage_grouping_dimension:{dimension}")
        if explicit_pie_requested:
            repaired["selected_chart_type"] = "pie"
            repaired["chart_type"] = "pie"
            repairs.append("explicit_pie_chart_preserved")

    # Rule F (scatter) unless time semantics are clearly requested.
    if relationship_requested and not time_requested:
        repaired["intent"] = "correlation"
        repaired["analysis_mode"] = "relationship"
        if "relationship" not in operation_set:
            operations.append("relationship")
            operation_set.add("relationship")
        if "comparison" not in operation_set:
            operations.append("comparison")
            operation_set.add("comparison")
        if len(_metric_columns(repaired)) >= 2:
            metrics = _metric_columns(repaired)
            repaired["x_axis"] = metrics[0]
            repaired["y_axis"] = [metrics[1]]
        repaired["selected_chart_type"] = "scatter"
        repaired["chart_type"] = "scatter"
        repaired["chart_lock"] = True
        repaired["explicit_chart_lock"] = True
        repairs.append("enforced_relationship_scatter_contract")

    if _question_has_any(combined_for_columns, COMPARISON_TOKENS) and "comparison" not in operation_set:
        operations.append("comparison")
        operation_set.add("comparison")

    if _question_has_any(combined_for_columns, DISTRIBUTION_TOKENS):
        repaired["is_distribution"] = True
        if "distribution" not in operation_set:
            operations.append("distribution")
            operation_set.add("distribution")

    # Intent normalization rule-set: distribution cannot be percentage or time-series.
    if repaired.get("is_distribution"):
        repaired["is_percentage"] = False
        repaired["metric_type"] = "distribution"
        repaired["is_time_series"] = False
        repaired["time_grouping_detected"] = False
        repaired["group_by_time"] = False
        repaired["time_granularity"] = ""
        repaired["aggregation"] = None
        repairs.append("distribution_forced_non_percentage_non_timeseries")

    # Ensure aggregation specs for grouped/time output.
    grouped_or_time = bool(
        repaired.get("time_grouping_detected")
        or repaired.get("group_by_time")
        or repaired.get("dimensions")
    )
    should_aggregate = grouped_or_time and not (relationship_requested and not time_requested)
    _ensure_metric_specs(repaired, aggregated=should_aggregate, aggregation="SUM")

    metrics_now = _metric_columns(repaired)
    if should_aggregate and metrics_now and "aggregation" not in operation_set:
        operations.append("aggregation")
        operation_set.add("aggregation")
    if len(metrics_now) > 1 and "multi_metric" not in operation_set:
        operations.append("multi_metric")
        operation_set.add("multi_metric")

    explicit_chart_request = _infer_explicit_chart_request(combined_for_columns)
    required_chart = _chart_for_intent(repaired, semantic_q)

    # Rule I/J/K + explicit request precedence.
    if explicit_chart_request:
        required_chart = explicit_chart_request
        repairs.append(f"preserved_explicit_chart_request:{explicit_chart_request}")

    if (
        (repaired.get("time_grouping_detected") or repaired.get("group_by_time") or repaired.get("is_time_series"))
        and len(metrics_now) > 1
        and required_chart not in {"scatter", "pie", "histogram", "table"}
    ):
        required_chart = "line_multi"
    elif (
        (repaired.get("time_grouping_detected") or repaired.get("group_by_time") or repaired.get("is_time_series"))
        and len(metrics_now) == 1
        and required_chart not in {"scatter", "pie", "histogram", "table"}
    ):
        required_chart = "line"

    if (
        (repaired.get("time_grouping_detected") or repaired.get("group_by_time") or repaired.get("is_time_series"))
        and required_chart == "scatter"
    ):
        required_chart = "line_multi" if len(metrics_now) > 1 else "line"
        repairs.append("blocked_scatter_under_time_series")

    if len(metrics_now) > 1 and required_chart in {"pie", "card"}:
        required_chart = "line_multi" if (repaired.get("is_time_series") or repaired.get("time_grouping_detected")) else "bar_grouped"
        repairs.append("blocked_pie_or_card_for_multi_metric")

    if (repaired.get("is_time_series") or repaired.get("group_by_time")) and required_chart == "table":
        required_chart = "line_multi" if len(metrics_now) > 1 else "line"
        repairs.append("blocked_table_for_time_series")

    # Rule L: block non-scalar semantics from collapsing to card.
    non_scalar_semantic = bool(
        relationship_requested
        or time_requested
        or grouping_requested
        or percentage_requested
        or _question_has_any(combined_for_columns, COMPARISON_TOKENS)
        or _question_has_any(combined_for_columns, DISTRIBUTION_TOKENS)
    )
    if non_scalar_semantic and required_chart == "card":
        if repaired.get("time_grouping_detected"):
            required_chart = "line_multi" if len(metrics_now) > 1 else "line"
        elif repaired.get("dimensions"):
            required_chart = "bar"
        elif relationship_requested and len(metrics_now) >= 2:
            required_chart = "scatter"
        else:
            required_chart = "table"
        repairs.append("prevented_non_scalar_card_collapse")

    # Percentage with grouping must never be histogram.
    if repaired.get("is_percentage") and (repaired.get("dimensions") or repaired.get("time_grouping_detected")):
        if required_chart == "histogram":
            required_chart = "pie" if not repaired.get("time_grouping_detected") else "bar_grouped"
            repairs.append("blocked_histogram_for_percentage_grouping")

    repaired["operations"] = operations
    repaired["selected_chart_type"] = required_chart
    repaired["chart_type"] = required_chart
    repaired["final_chart_type"] = required_chart
    if relationship_requested or (
        (repaired.get("time_grouping_detected") or repaired.get("group_by_time") or repaired.get("is_time_series"))
        and len(metrics_now) > 1
    ) or percentage_requested or repaired.get("is_distribution"):
        repaired["chart_lock"] = True
        repaired["explicit_chart_lock"] = True
    else:
        repaired["explicit_chart_lock"] = bool(explicit_chart_request) or bool(repaired.get("explicit_chart_lock"))
        repaired["chart_lock"] = bool(repaired.get("chart_lock")) or bool(repaired.get("explicit_chart_lock"))

    chart_payload = repaired.get("chart") if isinstance(repaired.get("chart"), dict) else {}
    repaired_chart = {
        **chart_payload,
        "type": required_chart,
        "metric_type": str(repaired.get("metric_type") or chart_payload.get("metric_type") or "") or None,
        "group_by": chart_payload.get("group_by")
        or repaired.get("x_axis")
        or (
            "date"
            if (repaired.get("time_grouping_detected") or repaired.get("group_by_time"))
            else None
        ),
    }

    if required_chart in {"line", "line_multi"}:
        repaired.setdefault("x_axis", str(repaired.get("time_dimension_alias") or "date"))
        metric_aliases = [
            str(spec.get("alias") or spec.get("column") or "").strip()
            for spec in (repaired.get("metric_specs") if isinstance(repaired.get("metric_specs"), list) else [])
            if isinstance(spec, dict)
        ]
        repaired["y_axis"] = _dedupe([alias for alias in metric_aliases if alias])
    elif required_chart == "scatter" and len(metrics_now) >= 2:
        repaired["x_axis"] = str(repaired.get("x_axis") or metrics_now[0])
        repaired["y_axis"] = [str((repaired.get("y_axis") or [metrics_now[1]])[0])]
    elif required_chart == "pie":
        group_col = str(repaired.get("x_axis") or (repaired.get("dimensions") or ["period"])[0]).strip()
        metric_aliases = [
            str(spec.get("alias") or "").strip()
            for spec in (repaired.get("metric_specs") if isinstance(repaired.get("metric_specs"), list) else [])
            if isinstance(spec, dict)
        ]
        preferred_value = "percentage_share" if "percentage_share" in metric_aliases else (metric_aliases[0] if metric_aliases else (f"sum_{metrics_now[0]}" if metrics_now else "value"))
        repaired["x_axis"] = group_col
        repaired["y_axis"] = [preferred_value]
        repaired_chart["label_column"] = group_col
        repaired_chart["value_column"] = preferred_value

    repaired["chart"] = repaired_chart

    if repaired.get("is_time_series") and sql and not _sql_has_group_by(sql):
        repaired.setdefault("semantic_contract_errors", []).append("time_intent_sql_missing_group_by")

    corrected_chart_input = chart_type or repaired.get("selected_chart_type") or repaired.get("chart_type")
    if required_chart != corrected_chart_input:
        repairs.append(f"chart_forced_{required_chart}")

    repaired["semantic_contract"] = {
        "valid": not repaired.get("semantic_contract_errors"),
        "corrections": list(dict.fromkeys(repairs)),
        "required_chart_type": required_chart,
        "raw_intent": raw_snapshot,
        "repaired_intent": copy.deepcopy(repaired),
        "trace": {
            "question": question,
            "semantic_question": semantic_q,
            "original_user_question": oq,
            "selected_columns_hint": selected_columns,
            "time_requested": time_requested,
            "relationship_requested": relationship_requested,
            "percentage_requested": percentage_requested,
            "explicit_chart_request": explicit_chart_request,
        },
    }

    if input_metrics_are_objects and isinstance(repaired.get("metric_specs"), list):
        repaired["metrics"] = [
            {
                "column": spec.get("column"),
                "aggregation": spec.get("aggregation"),
                "alias": spec.get("alias"),
            }
            for spec in repaired["metric_specs"]
            if isinstance(spec, dict) and spec.get("column")
        ]

    repaired = apply_deterministic_analytical_time_repair(
        intent=repaired,
        question=semantic_q,
        schema=schema,
        preprocess_hints=preprocess_hints,
    )
    return repaired

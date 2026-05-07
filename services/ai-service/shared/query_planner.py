
import re
from typing import Any

from shared.schema_filtering import is_technical_table_name
from shared.schema_utils import (
    build_table_metadata,
    is_technical_column_name,
    is_date_type,
    is_numeric_type,
    tokenize,
    unqualify_table_name,
)


DESC_RANK_KEYWORDS = (
    "highest",
    "largest",
    "most",
    "top",
    "maximum",
    "max",
    "best",
    "greatest",
    "biggest",
)
ASC_RANK_KEYWORDS = (
    "lowest",
    "smallest",
    "least",
    "bottom",
    "minimum",
    "min",
    "worst",
)

AVG_KEYWORDS = ("average", "avg", "mean")
COUNT_KEYWORDS = ("count", "how many")
SUM_KEYWORDS = ("sum", "total of", "in total", "overall total", "total")
MAX_KEYWORDS = ("maximum", "max")
MIN_KEYWORDS = ("minimum", "min")

VALID_AGGREGATIONS = {"SUM", "AVG", "COUNT", "MIN", "MAX"}
VALID_FILTER_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "IN", "LIKE", "BETWEEN"}

RATE_LIKE_TOKENS = ("rate", "ratio", "percent", "percentage", "pct", "share")
AVG_LIKE_TOKENS = ("avg", "average", "mean", "median")
ADDITIVE_HINT_TOKENS = ("total", "count", "population", "amount", "sales", "revenue", "cost", "profit")
IDENTIFIER_LIKE_TOKENS = ("id", "code", "uuid", "key", "number", "num")
BUSINESS_METRIC_HINT_TOKENS = (
    "sales",
    "total_sales",
    "revenue",
    "orders",
    "order_count",
    "customers",
    "customer_count",
    "quantity",
    "amount",
)
ROW_COUNT_INTENT_PATTERNS = (
    r"\brow count\b",
    r"\bcount rows\b",
    r"\bcount records\b",
    r"\bcount of rows\b",
    r"\bcount of records\b",
    r"\bnumber of rows\b",
    r"\bnumber of records\b",
    r"\bhow many rows\b",
    r"\bhow many records\b",
)
TIME_GRANULARITY_EXPRESSIONS = {
    "hour": "toStartOfHour({column})",
    "day": "toDate({column})",
    "week": "toStartOfWeek({column})",
    "month": "toStartOfMonth({column})",
    "quarter": "toStartOfQuarter({column})",
    "year": "toYear({column})",
}
TIME_GRANULARITY_TERMS = {"hour", "day", "week", "month", "quarter", "year"}
GROUPING_WORDS = {
    "day",
    "days",
    "week",
    "weeks",
    "month",
    "months",
    "year",
    "years",
    "region",
    "regions",
    "category",
    "categories",
}
RELATIONSHIP_KEYWORDS = (
    "relationship",
    "correlation",
    "associate",
    "association",
    "impact",
    "effect",
    "influence",
    "compare",
    "comparison",
    "compared",
    "versus",
    " vs ",
)
DISTRIBUTION_KEYWORDS = ("distribution", "distributed", "histogram", "spread", "frequency")

NUMERIC_FILTER_PATTERNS = [
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s+(?:is\s+)?(?:above|over|greater than|more than|higher than)\s+(-?\d+(?:\.\d+)?)\b",
        "operator": ">",
        "captures_operator": False,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s+(?:is\s+)?(?:below|under|less than|fewer than|lower than)\s+(-?\d+(?:\.\d+)?)\b",
        "operator": "<",
        "captures_operator": False,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s*>\s*(-?\d+(?:\.\d+)?)\b",
        "operator": ">",
        "captures_operator": False,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s*<\s*(-?\d+(?:\.\d+)?)\b",
        "operator": "<",
        "captures_operator": False,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s*(>=|=>)\s*(-?\d+(?:\.\d+)?)\b",
        "operator": ">=",
        "captures_operator": True,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s*(<=|=<)\s*(-?\d+(?:\.\d+)?)\b",
        "operator": "<=",
        "captures_operator": True,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s*(=|==)\s*(-?\d+(?:\.\d+)?)\b",
        "operator": "=",
        "captures_operator": True,
    },
    {
        "pattern": r"\b([a-z_][a-z0-9_ ]+?)\s+(?:is\s+)?(?:not equal to|not equals|!=)\s+(-?\d+(?:\.\d+)?)\b",
        "operator": "!=",
        "captures_operator": False,
    },
]

BETWEEN_FILTER_PATTERNS = [
    r"\b([a-z_][a-z0-9_ ]+?)\s+between\s+(-?\d+(?:\.\d+)?)\s+and\s+(-?\d+(?:\.\d+)?)\b",
    r"\b([a-z_][a-z0-9_ ]+?)\s+from\s+(-?\d+(?:\.\d+)?)\s+to\s+(-?\d+(?:\.\d+)?)\b",
]

TEXT_FILTER_PATTERNS = [
    r"\b(?:where|with)\s+([a-z_][a-z0-9_ ]+?)\s+(?:is|equals|equal to|=)\s+['\"]?([a-z0-9_ -]+?)['\"]?(?:\b|$)",
    r"\b([a-z_][a-z0-9_ ]+?)\s+(?:is|equals|equal to|=)\s+['\"]?([a-z0-9_ -]+?)['\"]?(?:\b|$)",
    r"\bin\s+the\s+([a-z0-9_ -]+?)\s+([a-z_][a-z0-9_ ]+?)(?:\b|$)",
]

TEXT_CONTAINS_PATTERNS = [
    r"\b([a-z_][a-z0-9_ ]+?)\s+contains\s+['\"]?([a-z0-9_ -]+?)['\"]?(?:\b|$)",
    r"\b([a-z_][a-z0-9_ ]+?)\s+like\s+['\"]?([a-z0-9_ -%]+?)['\"]?(?:\b|$)",
]

LANGUAGE_STOP_TOKENS = {
    "a",
    "an",
    "all",
    "and",
    "are",
    "as",
    "at",
    "between",
    "by",
    "compare",
    "compared",
    "comparison",
    "do",
    "does",
    "day",
    "days",
    "for",
    "from",
    "give",
    "had",
    "has",
    "have",
    "how",
    "in",
    "is",
    "list",
    "me",
    "month",
    "months",
    "of",
    "on",
    "or",
    "over",
    "please",
    "quarter",
    "quarters",
    "relationship",
    "show",
    "the",
    "to",
    "trend",
    "trends",
    "versus",
    "vs",
    "was",
    "week",
    "weeks",
    "were",
    "what",
    "when",
    "where",
    "which",
    "with",
    "year",
    "years",
}


DERIVED_METRIC_PATTERNS = [
    {
        "aliases": ("average order value", "aov"),
        "numerator_tokens": ("sales", "revenue", "amount"),
        "denominator_tokens": ("orders", "order"),
        "alias": "average_order_value",
    },
    {
        "aliases": ("conversion rate", "conversion"),
        "numerator_tokens": ("orders", "conversions"),
        "denominator_tokens": ("customers", "visitors", "users", "leads"),
        "alias": "conversion_rate",
    },
    {
        "aliases": ("revenue per customer", "sales per customer"),
        "numerator_tokens": ("revenue", "sales", "amount"),
        "denominator_tokens": ("customers", "customer"),
        "alias": "revenue_per_customer",
    },
    {
        "aliases": ("average basket size", "basket size"),
        "numerator_tokens": ("items", "quantity", "units"),
        "denominator_tokens": ("orders", "order"),
        "alias": "average_basket_size",
    },
]


def build_schema_metadata(schema: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for table, columns in schema.items():
        normalized_columns = []
        for col in columns:
            col_type = col.get("type", "")
            col_name = str(col.get("name", "")).strip()
            if not col_name or is_technical_column_name(col_name):
                continue
            inferred_is_date = bool(is_date_type(col_type) or _looks_temporal_column_name(col_name))
            normalized_columns.append(
                {
                    "name": col_name,
                    "type": col_type,
                    "is_numeric": col.get("is_numeric", is_numeric_type(col_type)),
                    "is_date": col.get("is_date", inferred_is_date),
                    "is_dimension": col.get(
                        "is_dimension",
                        not is_numeric_type(col_type) and not inferred_is_date,
                    ),
                }
            )
        metadata[table] = build_table_metadata(normalized_columns)
    return metadata


def _looks_temporal_column_name(column_name: str) -> bool:
    lowered = str(column_name or "").strip().lower()
    if not lowered:
        return False
    if lowered in {"ds", "date", "timestamp", "created_at"}:
        return True
    return bool(
        lowered.endswith(("_at", "_date", "_time"))
        or any(token in lowered for token in ("date", "time", "timestamp", "day", "week", "month", "year"))
    )


def _is_relationship_question(question_lower: str) -> bool:
    normalized = str(question_lower or "").strip().lower()
    if any(keyword in f" {normalized} " for keyword in RELATIONSHIP_KEYWORDS):
        return True
    return bool(
        re.search(r"\b(?:relationship|correlation|association)\s+(?:of|between)\b", normalized)
        or re.search(r"\bcompare\s+.+?\s+(?:and|with|to|against|vs|versus)\s+.+", normalized)
    )


def _is_distribution_question(question_lower: str) -> bool:
    normalized = str(question_lower or "").strip().lower()
    return any(keyword in normalized for keyword in DISTRIBUTION_KEYWORDS)


def _resolve_numeric_hint(hint: str, table_meta: dict[str, Any], ambiguities: list[dict[str, Any]]) -> str | None:
    numeric_columns = table_meta.get("numeric_columns", [])
    if not numeric_columns:
        return None
    return _resolve_column_name_with_ambiguity(
        candidate=hint,
        columns=[table_meta["column_map"][c] for c in numeric_columns],
        context="metric",
        ambiguities=ambiguities,
    )


def _derive_metric_by_token_groups(
    *,
    table_meta: dict[str, Any],
    ambiguities: list[dict[str, Any]],
    numerator_tokens: tuple[str, ...],
    denominator_tokens: tuple[str, ...],
    alias: str,
) -> dict[str, Any] | None:
    numerator_column = None
    denominator_column = None

    for token in numerator_tokens:
        numerator_column = _resolve_numeric_hint(token, table_meta, ambiguities)
        if numerator_column:
            break
    for token in denominator_tokens:
        denominator_column = _resolve_numeric_hint(token, table_meta, ambiguities)
        if denominator_column:
            break

    if not numerator_column or not denominator_column:
        return None
    if numerator_column == denominator_column:
        return None

    return {
        "column": numerator_column,
        "aggregation": "SUM",
        "alias": alias,
        "formula": {
            "type": "ratio",
            "numerator": {"column": numerator_column, "aggregation": "SUM"},
            "denominator": {"column": denominator_column, "aggregation": "SUM"},
            "safe_division": True,
        },
    }


def _infer_derived_metric(
    *,
    question_lower: str,
    table_meta: dict[str, Any],
    ambiguities: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for pattern in DERIVED_METRIC_PATTERNS:
        aliases = pattern.get("aliases", ())
        if not any(alias in question_lower for alias in aliases):
            continue
        derived = _derive_metric_by_token_groups(
            table_meta=table_meta,
            ambiguities=ambiguities,
            numerator_tokens=tuple(pattern.get("numerator_tokens", ())),
            denominator_tokens=tuple(pattern.get("denominator_tokens", ())),
            alias=str(pattern.get("alias", "derived_metric")).strip() or "derived_metric",
        )
        if derived:
            return derived

    per_match = re.search(r"\b([a-z_][a-z0-9_ ]+?)\s+per\s+([a-z_][a-z0-9_ ]+?)\b", question_lower)
    if per_match:
        denominator_hint = per_match.group(2).strip().lower()
        if denominator_hint not in TIME_GRANULARITY_TERMS:
            numerator_hint = per_match.group(1).strip()
            numerator_column = _resolve_numeric_hint(numerator_hint, table_meta, ambiguities)
            denominator_column = _resolve_numeric_hint(denominator_hint, table_meta, ambiguities)
            if numerator_column and denominator_column and numerator_column != denominator_column:
                return {
                    "column": numerator_column,
                    "aggregation": "SUM",
                    "alias": f"{numerator_column}_per_{denominator_column}",
                    "formula": {
                        "type": "ratio",
                        "numerator": {"column": numerator_column, "aggregation": "SUM"},
                        "denominator": {"column": denominator_column, "aggregation": "SUM"},
                        "safe_division": True,
                    },
                }
    return None


def _infer_relationship_metrics(
    *,
    question: str,
    table_meta: dict[str, Any],
    ambiguities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    all_columns = table_meta["columns"]
    numeric_columns = table_meta["numeric_columns"]
    if not numeric_columns:
        return []

    resolved: list[str] = []
    relation_match = re.search(
        r"\bbetween\s+([a-z_][a-z0-9_ ]+?)\s+and\s+([a-z_][a-z0-9_ ]+)",
        question.lower(),
    )
    if not relation_match:
        relation_match = re.search(
            r"\bcompare\s+([a-z_][a-z0-9_ ]+?)\s+(?:and|with|to|against|vs|versus)\s+([a-z_][a-z0-9_ ]+)",
            question.lower(),
        )
    if relation_match:
        candidates = [_clean_metric_hint(relation_match.group(1).strip()), _clean_metric_hint(relation_match.group(2).strip())]
        for candidate in candidates:
            mapped = _resolve_column_name_with_ambiguity(
                candidate=candidate,
                columns=[table_meta["column_map"][c] for c in numeric_columns],
                context="metric",
                ambiguities=ambiguities,
            )
            if mapped and mapped not in resolved:
                resolved.append(mapped)

    if len(resolved) < 2:
        for hint in _extract_metric_hints_from_question(question):
            mapped = _resolve_column_name_with_ambiguity(
                candidate=hint,
                columns=[table_meta["column_map"][c] for c in numeric_columns],
                context="metric",
                ambiguities=ambiguities,
            )
            if mapped and mapped not in resolved:
                resolved.append(mapped)
            if len(resolved) >= 2:
                break

    if len(resolved) < 2:
        scored = sorted(
            numeric_columns,
            key=lambda col: _score_metric_column(col, tokenize(question)),
            reverse=True,
        )
        for col in scored[:2]:
            if col not in resolved:
                resolved.append(col)
            if len(resolved) >= 2:
                break

    if len(resolved) < 2:
        return []

    return [
        {"column": resolved[0], "aggregation": None, "alias": resolved[0]},
        {"column": resolved[1], "aggregation": None, "alias": resolved[1]},
    ]


def normalize_analytical_intent(
    *,
    question: str,
    raw_intent: dict[str, Any],
    schema: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    if not schema:
        raise ValueError("Schema is empty; cannot plan query")

    schema_metadata = build_schema_metadata(schema)
    ambiguities: list[dict[str, Any]] = []

    table = _resolve_table(question, raw_intent, schema_metadata, ambiguities=ambiguities)
    if not table:
        raise ValueError("Could not resolve target table from schema")

    table_meta = schema_metadata[table]
    question_lower = question.lower()
    relationship_requested = _is_relationship_question(question_lower)
    distribution_requested = _is_distribution_question(question_lower)

    dimensions = _infer_dimensions(question, raw_intent, table_meta, ambiguities=ambiguities)
    time_granularity = _infer_time_granularity(question_lower)
    time_column = _select_time_column(table_meta) if time_granularity else ""
    time_dimension_expression = ""
    time_dimension_alias = ""
    time_grouping_detected = bool(time_granularity and time_column)
    if time_granularity == "hour" and not _supports_hour_granularity(table_meta=table_meta, column_name=time_column):
        raise ValueError("Granularity not supported: hour-level data not available")
    if time_grouping_detected:
        time_dimension_alias = "date"
        time_dimension_expression = _time_dimension_expression(
            table_meta=table_meta,
            column_name=time_column,
            granularity=time_granularity,
        )
        # Time-series intent takes precedence over generic "compare X and Y" phrasing.
        # Without this, prompts like "compare sales and orders per week" can be
        # misrouted into relationship/scatter semantics and lose the time axis.
        relationship_requested = False
        if time_column not in dimensions:
            dimensions = [time_column, *dimensions]
            ambiguities.append(
                {
                    "type": "dimension_inference",
                    "message": f"Time grouping detected ({time_granularity}); auto-selected time dimension.",
                    "candidates": [time_column],
                    "selected_dimension": time_column,
                    "resolution": "auto_selected_dimension",
                }
            )

    question_rank_direction = _detect_rank_direction(question_lower)
    ranking = _infer_ranking(question_lower=question_lower, raw_intent=raw_intent)
    explicit_top_n_requested = bool(ranking.get("explicit_limit_requested"))
    if (time_grouping_detected or relationship_requested) and not explicit_top_n_requested and not question_rank_direction:
        ranking["direction"] = None
        ranking["limit"] = None
        ranking["implied_limit"] = None
        ranking["source"] = "time_series_or_relationship_override"
    limit = ranking["limit"]
    ranking_requested = bool(ranking.get("direction")) or isinstance(limit, int)
    overall_total_requested = _is_overall_total_request(question_lower)

    if ranking_requested and not dimensions and not relationship_requested:
        auto_dimension = _auto_select_ranking_dimension(
            table_meta=table_meta,
            ambiguities=ambiguities,
        )
        if auto_dimension:
            dimensions = [auto_dimension]

    filters = _normalize_filters(question, raw_intent, table_meta, ambiguities=ambiguities)
    if not filters:
        year_filter = _infer_year_filter(question_lower, table_meta)
        if year_filter:
            filters.append(year_filter)

    source_grain_matches_requested = _source_grain_matches_requested(
        table_meta=table_meta,
        time_column=time_column,
        time_granularity=time_granularity,
        time_grouping_detected=time_grouping_detected,
    )
    time_rollup_required = bool(time_grouping_detected and not source_grain_matches_requested)

    metrics = _infer_metrics(
        question=question,
        raw_intent=raw_intent,
        table_meta=table_meta,
        dimensions=dimensions,
        ranking=ranking,
        ambiguities=ambiguities,
        relationship_requested=relationship_requested,
        distribution_requested=distribution_requested,
        preserve_time_grain_metric=bool(time_grouping_detected and source_grain_matches_requested),
    )
    if not metrics:
        metrics = [{"column": "*", "aggregation": "COUNT", "alias": _metric_alias("COUNT", "*")}]

    if relationship_requested:
        dimensions = []
        ranking_requested = False
        ranking["direction"] = None
        ranking["source"] = "relationship_override"
        limit = None

    order_by = _normalize_order_by(
        raw_intent,
        table_meta,
        metric_aliases=[metric["alias"] for metric in metrics if metric.get("alias")],
    )

    if ranking["direction"] and not order_by:
        primary_metric_alias = metrics[0]["alias"]
        order_by = [{"column": primary_metric_alias, "direction": ranking["direction"]}]
        if not limit:
            limit = ranking["implied_limit"] or 1
    elif limit and not order_by and metrics:
        primary_metric_alias = metrics[0]["alias"]
        order_by = [{"column": primary_metric_alias, "direction": "DESC"}]
    if (time_grouping_detected or relationship_requested) and not explicit_top_n_requested and not ranking.get("direction"):
        limit = None
    if time_grouping_detected and not ranking["direction"]:
        order_by = [{"column": time_dimension_alias or "date", "direction": "ASC"}]
    if relationship_requested:
        order_by = []

    operations = _derive_operations(
        metrics=metrics,
        dimensions=dimensions,
        filters=filters,
        order_by=order_by,
        limit=limit,
        ranking_requested=bool(ranking.get("direction")) or explicit_top_n_requested,
        relationship_requested=relationship_requested,
        distribution_requested=distribution_requested,
        time_grouping_detected=time_grouping_detected,
    )
    primary_intent = _infer_primary_intent(
        operations=operations,
        relationship_requested=relationship_requested,
        distribution_requested=distribution_requested,
        time_grouping_detected=time_grouping_detected,
    )
    if time_grouping_detected and not ranking_requested:
        primary_intent = "time_series"
        if "time_grouping" not in operations:
            operations.append("time_grouping")
        operations = [op for op in operations if op != "ranking"]
    elif ranking_requested:
        primary_intent = "ranking"
    if relationship_requested and "comparison" not in operations:
        operations.append("comparison")
    ambiguities = _normalize_dimension_ambiguities(ambiguities)

    aggregations = {str(metric.get("aggregation") or "").upper() for metric in metrics if metric.get("aggregation")}
    if len(aggregations) == 1:
        aggregation_summary: str | None = next(iter(aggregations))
    elif len(aggregations) > 1:
        aggregation_summary = "MIXED"
    else:
        aggregation_summary = None
    metric_columns = [str(metric.get("column", "")).strip() for metric in metrics if isinstance(metric, dict) and str(metric.get("column", "")).strip() and str(metric.get("column", "")).strip() != "*"]
    y_axis = [str(metric.get("alias") or metric.get("column") or "").strip() for metric in metrics if isinstance(metric, dict) and str(metric.get("alias") or metric.get("column") or "").strip()]
    is_percentage = any(token in question_lower for token in ("share", "percentage", "percent", "contribution", "proportion", "part of total"))
    is_distribution = distribution_requested or any(token in question_lower for token in ("distribution", "spread", "frequency", "histogram"))
    geo_requested = any(token in question_lower for token in ("country", "city", "region", "state", "location", "latitude", "longitude", "lat", "lon"))
    selected_chart_type = "table"
    if time_grouping_detected and len(metric_columns) > 1:
        selected_chart_type = "line_multi"
    elif time_grouping_detected and metric_columns:
        selected_chart_type = "line"
    elif geo_requested and dimensions:
        selected_chart_type = "map"
    elif relationship_requested and len(metric_columns) >= 2 and not time_grouping_detected:
        selected_chart_type = "scatter"
    elif is_distribution:
        selected_chart_type = "histogram"
    elif is_percentage:
        selected_chart_type = "pie"
    elif dimensions and metric_columns:
        selected_chart_type = "bar"
    elif len(metric_columns) == 1 and not dimensions:
        selected_chart_type = "card"
    x_axis = (time_dimension_alias or "date") if time_grouping_detected else (dimensions[0] if dimensions else "")

    return {
        "intent_type": "analytical",
        "table": unqualify_table_name(table),
        "intent": primary_intent,
        "operations": operations,
        "dimensions": dimensions,
        "metrics": metrics,
        "filters": filters,
        "aggregation": aggregation_summary,
        "ranking": {
            "direction": ranking["direction"],
            "requested": bool(ranking["direction"]),
            "source": ranking["source"],
        },
        "order_by": order_by,
        "limit": limit,
        "time_granularity": time_granularity,
        "time_column": time_column,
        "time_grouping_detected": time_grouping_detected,
        "source_grain_matches_requested": source_grain_matches_requested,
        "time_rollup_required": time_rollup_required,
        "time_dimension_expression": time_dimension_expression,
        "time_dimension_alias": time_dimension_alias,
        "explicit_top_n_requested": explicit_top_n_requested,
        "ambiguities": ambiguities,
        "kpi_allowed_without_dimension": overall_total_requested,
        "row_count_requested": _is_explicit_row_count_request(question_lower),
        "analysis_mode": "relationship" if relationship_requested else "distribution" if distribution_requested else "",
        "reasoning_version": "semantic_ir_v1",
        "selected_chart_type": selected_chart_type,
        "chart_type": selected_chart_type,
        "final_chart_type": selected_chart_type,
        "explicit_chart_lock": False,
        "x_axis": x_axis,
        "y_axis": y_axis,
        "is_time_series": bool(time_grouping_detected),
        "is_percentage": bool(is_percentage),
        "is_distribution": bool(is_distribution),
        "metric_type": "percentage" if is_percentage else "absolute",
        "chart_reason": "deterministic chart selection from normalized analytical intent",
        "chart_reason_code": "deterministic_chart_selection",
    }


def _is_overall_total_request(question_lower: str) -> bool:
    if not question_lower:
        return False
    if "overall total" in question_lower or "overall" in question_lower:
        return True
    if "in total" in question_lower and not re.search(r"\b(by|per|across|for each|in each)\b", question_lower):
        return True
    return False


def _infer_time_granularity(question_lower: str) -> str:
    normalized = str(question_lower or "").strip().lower()
    if not normalized:
        return ""
    explicit_patterns = (
        (r"\b(?:per|by|across|for each|in each|grouped by)\s+hours?\b", "hour"),
        (r"\b(?:per|by|across|for each|in each|grouped by)\s+days?\b", "day"),
        (r"\b(?:per|by|across|for each|in each|grouped by)\s+weeks?\b", "week"),
        (r"\b(?:per|by|across|for each|in each|grouped by)\s+months?\b", "month"),
        (r"\b(?:per|by|across|for each|in each|grouped by)\s+quarters?\b", "quarter"),
        (r"\b(?:per|by|across|for each|in each|grouped by)\s+years?\b", "year"),
    )
    for pattern, granularity in explicit_patterns:
        if re.search(pattern, normalized):
            return granularity

    if _is_trend_over_time_question(normalized):
        return "day"

    # Soft inference when time concepts are present without explicit "per".
    soft_patterns = (
        (r"\bhourly\b|\bhours?\b", "hour"),
        (r"\bdaily\b|\bdays?\b", "day"),
        (r"\bdate\b|\btime\b", "day"),
        (r"\bweekly\b|\bweeks?\b", "week"),
        (r"\bmonthly\b|\bmonths?\b", "month"),
        (r"\bquarterly\b|\bquarters?\b", "quarter"),
        (r"\byearly\b|\byears?\b|\bannual\b|\bannually\b", "year"),
    )
    for pattern, granularity in soft_patterns:
        if re.search(pattern, normalized):
            return granularity
    return ""


def _is_trend_over_time_question(question_lower: str) -> bool:
    normalized = str(question_lower or "").strip().lower()
    if not normalized:
        return False
    trend_terms = (
        r"\btrend\b",
        r"\btrends\b",
        r"\bchanged?\b",
        r"\bchange over\b",
        r"\bevolv(?:e|ed|ing)\b",
        r"\bover time\b",
        r"\bthrough time\b",
        r"\bacross time\b",
        r"\btime series\b",
    )
    has_trend_language = any(re.search(pattern, normalized) for pattern in trend_terms)
    has_time_axis = bool(
        re.search(r"\bover\s+time\b|\bthrough\s+time\b|\bacross\s+time\b|\btime\s+series\b", normalized)
        or re.search(r"\bby\s+(?:date|time|day|week|month|quarter|year)\b", normalized)
    )
    return has_trend_language and has_time_axis


def _select_time_column(table_meta: dict[str, Any]) -> str:
    date_columns = [str(col).strip() for col in table_meta.get("date_columns", []) if str(col).strip()]
    if not date_columns:
        return ""
    ranked_dates = sorted(
        date_columns,
        key=lambda col: (_time_column_priority(col), col.lower()),
    )
    return ranked_dates[0] if ranked_dates else ""


def _time_dimension_expression(*, table_meta: dict[str, Any], column_name: str, granularity: str) -> str:
    template = TIME_GRANULARITY_EXPRESSIONS.get(granularity, "")
    if not template or not column_name:
        return ""
    column_meta = table_meta.get("column_map", {}).get(column_name, {})
    column_type = str(column_meta.get("type", "")).strip().lower()
    normalized_column = column_name
    string_like_type = (
        "string" in column_type
        or "fixedstring" in column_type
        or "varchar" in column_type
        or "char" in column_type
    )
    if string_like_type:
        parsed_expr = _string_time_parse_expr(column_name)
        if granularity == "day":
            return f"toDate({parsed_expr})"
        normalized_column = parsed_expr
    if granularity == "hour":
        if string_like_type:
            normalized_column = _string_time_parse_expr(column_name)
        elif "date" in column_type and "datetime" not in column_type and "timestamp" not in column_type:
            normalized_column = f"toDateTime({column_name})"
    return template.format(column=normalized_column)


def _string_time_parse_expr(column_name: str) -> str:
    return (
        f"coalesce("
        f"parseDateTimeBestEffortUSOrNull({column_name}), "
        f"parseDateTimeBestEffortOrNull({column_name})"
        f")"
    )


def _source_grain_matches_requested(
    *,
    table_meta: dict[str, Any],
    time_column: str,
    time_granularity: str,
    time_grouping_detected: bool,
) -> bool:
    """
    Infer whether the selected time column is already at the requested analysis grain.

    This is intentionally schema-based and table-agnostic: Date columns are already
    day-grain, while explicit week/month/quarter/year columns can satisfy matching
    rollups without re-aggregating. Datetime/timestamp columns do not count as
    day-grain because multiple rows per day are common.
    """
    if not time_grouping_detected or not time_column or not time_granularity:
        return False

    column_meta = table_meta.get("column_map", {}).get(time_column, {})
    column_type = str(column_meta.get("type", "")).strip().lower()
    column_name = str(time_column or "").strip().lower()

    if time_granularity == "day":
        if "datetime" in column_type or "timestamp" in column_type:
            return False
        if column_type.startswith("date") or column_name in {"ds", "date", "day"}:
            return True
        return column_name.endswith("_date") or column_name.endswith("_day")

    grain_name_markers = {
        "week": ("week",),
        "month": ("month", "yyyy_mm", "year_month"),
        "quarter": ("quarter",),
        "year": ("year",),
    }
    markers = grain_name_markers.get(time_granularity, ())
    return any(marker in column_name for marker in markers)


def _supports_hour_granularity(*, table_meta: dict[str, Any], column_name: str) -> bool:
    if not column_name:
        return False
    column_meta = table_meta.get("column_map", {}).get(column_name, {})
    column_type = str(column_meta.get("type", "")).strip().lower()
    if not column_type:
        return False
    return ("datetime" in column_type) or ("timestamp" in column_type) or ("time" in column_type and "date" in column_type)


def _normalize_dimension_ambiguities(ambiguities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not ambiguities:
        return []
    has_auto = any(
        isinstance(item, dict) and str(item.get("resolution", "")).strip() == "auto_selected_dimension"
        for item in ambiguities
    )
    if not has_auto:
        return ambiguities
    normalized: list[dict[str, Any]] = []
    for item in ambiguities:
        if not isinstance(item, dict):
            continue
        if str(item.get("resolution", "")).strip() == "auto_selected_dimension":
            normalized.append(item)
    return normalized


def _time_column_priority(column_name: str) -> int:
    lowered = str(column_name or "").strip().lower()
    if lowered in {"ds", "date", "timestamp", "created_at"}:
        return 0
    if lowered.endswith("_at") or lowered.endswith("_date") or lowered.endswith("_time"):
        return 1
    if any(token in lowered for token in ("date", "time", "timestamp", "day", "week", "month", "year")):
        return 2
    return 3


def _categorical_column_priority(column_name: str) -> int:
    lowered = str(column_name or "").strip().lower()
    preferred = ("region", "product", "category", "city")
    for idx, token in enumerate(preferred):
        if token == lowered or lowered.startswith(f"{token}_") or lowered.endswith(f"_{token}"):
            return idx
    if any(token in lowered for token in preferred):
        return len(preferred)
    return len(preferred) + 1


def _auto_select_ranking_dimension(
    *,
    table_meta: dict[str, Any],
    ambiguities: list[dict[str, Any]],
) -> str | None:
    date_columns = [str(col).strip() for col in table_meta.get("date_columns", []) if str(col).strip()]
    dimension_columns = [str(col).strip() for col in table_meta.get("dimension_columns", []) if str(col).strip()]

    if date_columns:
        ranked_dates = sorted(
            date_columns,
            key=lambda col: (_time_column_priority(col), col.lower()),
        )
        chosen = ranked_dates[0]
        ambiguities.append(
            {
                "type": "dimension_inference",
                "message": "Ranking requested without explicit dimension; auto-selected time dimension.",
                "candidates": ranked_dates[:3],
                "selected_dimension": chosen,
                "resolution": "auto_selected_dimension",
            }
        )
        return chosen

    if dimension_columns:
        ranked_dims = sorted(
            dimension_columns,
            key=lambda col: (_categorical_column_priority(col), col.lower()),
        )
        chosen = ranked_dims[0]
        ambiguities.append(
            {
                "type": "dimension_inference",
                "message": "Ranking requested without explicit dimension; auto-selected categorical dimension.",
                "candidates": ranked_dims[:3],
                "selected_dimension": chosen,
                "resolution": "auto_selected_dimension",
            }
        )
        return chosen

    return None
def _resolve_table(
    question: str,
    raw_intent: dict[str, Any],
    schema_metadata: dict[str, dict[str, Any]],
    *,
    ambiguities: list[dict[str, Any]],
) -> str | None:
    if len(schema_metadata.keys()) == 1:
        return next(iter(schema_metadata.keys()))

    requested = (raw_intent.get("table") or "").strip()
    if requested in schema_metadata and not is_technical_table_name(requested):
        return requested
    if requested:
        requested_unqualified = unqualify_table_name(requested).lower()
        unqualified_matches = [
            table
            for table in schema_metadata.keys()
            if unqualify_table_name(table).lower() == requested_unqualified
            and not is_technical_table_name(table)
        ]
        if len(unqualified_matches) == 1:
            return unqualified_matches[0]
        if len(unqualified_matches) > 1:
            ambiguities.append(
                {
                    "type": "table_resolution",
                    "message": f"Table name '{requested}' matched multiple schema tables.",
                    "candidates": unqualified_matches,
                    "resolution": unqualified_matches[0],
                }
            )
            return unqualified_matches[0]

    question_tokens = tokenize(question)
    referenced_columns = set()

    for metric in _iter_raw_metric_candidates(raw_intent):
        column = metric[0]
        if column:
            referenced_columns.add(column)
    for dim in raw_intent.get("dimensions", []) or []:
        if isinstance(dim, str):
            referenced_columns.add(dim)
    for flt in raw_intent.get("filters", []) or []:
        if isinstance(flt, dict) and flt.get("column"):
            referenced_columns.add(flt["column"])
    for order in raw_intent.get("order_by", []) or []:
        if isinstance(order, dict) and order.get("column"):
            referenced_columns.add(order["column"])

    scored_tables: list[tuple[str, int]] = []
    for table, table_meta in schema_metadata.items():
        score = 0
        if is_technical_table_name(table):
            score -= 25

        table_tokens = tokenize(unqualify_table_name(table))
        score += len(table_tokens & question_tokens) * 3

        for candidate in referenced_columns:
            if _resolve_column_name(candidate, table_meta["columns"]):
                score += 4

        for col in table_meta["columns"]:
            if tokenize(col["name"]) & question_tokens:
                score += 1

        if requested and requested.lower() in table.lower():
            score += 5

        scored_tables.append((table, score))

    scored_tables.sort(key=lambda item: item[1], reverse=True)
    if not scored_tables:
        return None

    if len(scored_tables) > 1 and scored_tables[0][1] == scored_tables[1][1]:
        ambiguities.append(
            {
                "type": "table_resolution",
                "message": "Multiple tables had equivalent semantic relevance.",
                "candidates": [scored_tables[0][0], scored_tables[1][0]],
                "resolution": scored_tables[0][0],
            }
        )

    return scored_tables[0][0]


def _resolve_column_name(candidate: str, columns: list[dict[str, Any]]) -> str | None:
    if not candidate:
        return None

    candidate_clean = candidate.strip()
    candidate_lower = candidate_clean.lower()

    exact = [c["name"] for c in columns if c["name"].lower() == candidate_lower]
    if exact:
        return exact[0]

    normalized_target = candidate_lower.replace(" ", "_")
    exact_normalized = [c["name"] for c in columns if c["name"].lower() == normalized_target]
    if exact_normalized:
        return exact_normalized[0]
    if normalized_target.endswith("s"):
        singular = normalized_target[:-1]
        singular_match = [c["name"] for c in columns if c["name"].lower() == singular]
        if singular_match:
            return singular_match[0]

    target_tokens = _expand_tokens(tokenize(candidate_clean))
    best = None
    best_score = 0

    for col in columns:
        col_name = col["name"]
        col_tokens = _expand_tokens(tokenize(col_name))
        overlap = len(target_tokens & col_tokens)
        if overlap > best_score:
            best_score = overlap
            best = col_name

    return best if best_score > 0 else None


def _resolve_column_name_with_ambiguity(
    *,
    candidate: str,
    columns: list[dict[str, Any]],
    context: str,
    ambiguities: list[dict[str, Any]],
) -> str | None:
    candidate_tokens = _expand_tokens(tokenize(candidate))
    if not candidate_tokens:
        return _resolve_column_name(candidate, columns)

    scored: list[tuple[str, int]] = []
    for col in columns:
        overlap = len(candidate_tokens & _expand_tokens(tokenize(col["name"])))
        if overlap > 0:
            scored.append((col["name"], overlap))

    if scored:
        scored.sort(key=lambda item: item[1], reverse=True)
        if len(scored) > 1 and scored[0][1] == scored[1][1]:
            ambiguities.append(
                {
                    "type": "column_resolution",
                    "message": f"Ambiguous {context} phrase '{candidate}'.",
                    "candidates": [scored[0][0], scored[1][0]],
                    "resolution": scored[0][0],
                }
            )
            return scored[0][0]

    return _resolve_column_name(candidate, columns)


def _expand_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for token in list(tokens):
        if token.endswith("ies") and len(token) > 4:
            expanded.add(token[:-3] + "y")
        if token.endswith("s") and len(token) > 3:
            expanded.add(token[:-1])
    return expanded


def _detect_rank_direction(question_lower: str) -> str | None:
    has_desc = any(re.search(rf"\b{re.escape(keyword)}\b", question_lower) for keyword in DESC_RANK_KEYWORDS)
    has_asc = any(re.search(rf"\b{re.escape(keyword)}\b", question_lower) for keyword in ASC_RANK_KEYWORDS)
    if has_desc and has_asc:
        # In mixed phrasing (e.g. "top ... worst"), explicit low-end terms should win.
        return "ASC"
    if has_desc:
        return "DESC"
    if has_asc:
        return "ASC"
    return None


def _extract_limit(question_lower: str, raw_intent: dict[str, Any]) -> tuple[int | None, bool]:
    patterns = (
        r"\btop\s+(\d+)\b",
        r"\bbottom\s+(\d+)\b",
        r"\bfirst\s+(\d+)\b",
        r"\blast\s+(\d+)\b",
        r"\blimit(?:ed)?\s+(?:to\s+)?(\d+)\b",
        r"\b(\d+)\s+\w+\s+with\s+(?:the\s+)?(?:highest|lowest|largest|smallest|best|worst)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, question_lower)
        if match:
            value = int(match.group(1))
            if value > 0:
                return value, True

    raw_limit = raw_intent.get("limit")
    if isinstance(raw_limit, int) and raw_limit > 0:
        return raw_limit, False
    return None, False


def _infer_ranking(*, question_lower: str, raw_intent: dict[str, Any]) -> dict[str, Any]:
    direction = _detect_rank_direction(question_lower)
    source = "query"

    raw_order = raw_intent.get("order_by") or []
    if isinstance(raw_order, list) and raw_order:
        first = raw_order[0] if isinstance(raw_order[0], dict) else {}
        raw_direction = str(first.get("direction", "")).strip().upper()
        if raw_direction in {"ASC", "DESC"}:
            direction = raw_direction
            source = "raw_intent"

    limit, explicit_limit_requested = _extract_limit(question_lower, raw_intent)
    implied_limit = 1 if direction and limit is None else None

    return {
        "direction": direction,
        "limit": limit,
        "implied_limit": implied_limit,
        "source": source,
        "explicit_limit_requested": explicit_limit_requested,
    }
def _detect_explicit_aggregation(question_lower: str) -> str | None:
    if any(k in question_lower for k in AVG_KEYWORDS):
        return "AVG"
    if any(k in question_lower for k in COUNT_KEYWORDS):
        return "COUNT"
    if any(k in question_lower for k in SUM_KEYWORDS):
        return "SUM"
    if any(k in question_lower for k in MAX_KEYWORDS):
        return "MAX"
    if any(k in question_lower for k in MIN_KEYWORDS):
        return "MIN"
    return None


def _is_rate_like(column_name: str) -> bool:
    col_lower = (column_name or "").lower()
    return any(token in col_lower for token in RATE_LIKE_TOKENS)


def _is_avg_like(column_name: str) -> bool:
    col_lower = (column_name or "").lower()
    return any(token in col_lower for token in AVG_LIKE_TOKENS)


def _looks_additive(column_name: str) -> bool:
    col_lower = (column_name or "").lower()
    return any(token in col_lower for token in ADDITIVE_HINT_TOKENS)


def _looks_identifier_like(column_name: str) -> bool:
    col_lower = (column_name or "").lower()
    return any(token in col_lower for token in IDENTIFIER_LIKE_TOKENS)


def _is_business_metric_column(column_name: str) -> bool:
    col_lower = (column_name or "").lower()
    return any(token in col_lower for token in BUSINESS_METRIC_HINT_TOKENS)


def _is_explicit_row_count_request(question_lower: str) -> bool:
    normalized = str(question_lower or "").strip().lower()
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in ROW_COUNT_INTENT_PATTERNS)


def _aggregation_for_ranking(column_name: str, question_lower: str, has_dimensions: bool) -> str | None:
    explicit = _detect_explicit_aggregation(question_lower)
    if explicit:
        if (
            explicit == "COUNT"
            and has_dimensions
            and _is_business_metric_column(column_name)
            and not _is_explicit_row_count_request(question_lower)
        ):
            return "SUM"
        return explicit
    if _is_rate_like(column_name) or _is_avg_like(column_name):
        return "AVG"
    if has_dimensions:
        return "SUM"
    return None


def _has_grouping_intent(question_lower: str) -> bool:
    return bool(
        re.search(
            r"\b(by|per|across|for each|in each|top|bottom|highest|lowest|largest|smallest|best|worst)\b",
            question_lower,
        )
    )


def _metric_alias(aggregation: str | None, column: str) -> str:
    safe_column = column.replace(".", "_")
    if column == "*":
        safe_column = "rows"
    if not aggregation:
        return safe_column
    return f"{aggregation.lower()}_{safe_column}"


def _score_metric_column(column_name: str, question_tokens: set[str]) -> int:
    col_tokens = tokenize(column_name)
    score = len(col_tokens & question_tokens) * 4

    if "_id" in column_name.lower() or _looks_identifier_like(column_name):
        score -= 2
    if _is_rate_like(column_name):
        score += 1
    if _looks_additive(column_name):
        score += 1

    return score


def _extract_metric_hints_from_question(question: str) -> list[str]:
    question_lower = question.lower()
    hints: list[str] = []

    select_match = re.search(
        r"\b(?:show|list|display|give|compare|what is|what are|which)\s+(.+?)(?:\s+\bby\b|\s+\bwhere\b|\s+\bin\b|\s+\bwith\b|$)",
        question_lower,
    )
    if select_match:
        projected_part = select_match.group(1)
        projected_part = re.sub(
            r"\b(the|a|an|all|total|overall|top\s+\d+|bottom\s+\d+|trend|relationship|between|over\s+time)\b",
            " ",
            projected_part,
        )
        for chunk in re.split(r"\band\b|,", projected_part):
            hint = _clean_metric_hint(chunk.strip())
            if hint and hint not in {"the", "a", "an"}:
                hints.append(hint)

    by_match = re.search(
        r"\bby\s+([a-z_][a-z0-9_ ]+?)(?:\s+\bwhere\b|\s+\bwith\b|\s+\bin\b|$)",
        question_lower,
    )
    if by_match:
        for chunk in re.split(r"\band\b|,", by_match.group(1)):
            hint = _clean_metric_hint(chunk.strip())
            if hint:
                hints.append(hint)

    rank_metric_match = re.search(
        r"\b(?:highest|lowest|largest|smallest|best|worst)\s+([a-z_][a-z0-9_ ]+)\b",
        question_lower,
    )
    if rank_metric_match:
        hint = _clean_metric_hint(rank_metric_match.group(1).strip())
        if hint:
            hints.append(hint)

    return hints


def _iter_raw_metric_candidates(raw_intent: dict[str, Any]) -> list[tuple[str, str | None]]:
    results: list[tuple[str, str | None]] = []

    for metric in raw_intent.get("metric_specs", []) or []:
        if not isinstance(metric, dict):
            continue
        column = str(metric.get("column", "")).strip()
        aggregation = str(metric.get("aggregation", "")).strip().upper() or None
        if column:
            results.append((column, aggregation))

    for metric in raw_intent.get("metrics", []) or []:
        if isinstance(metric, dict):
            column = str(metric.get("column", "")).strip()
            aggregation = str(metric.get("aggregation", "")).strip().upper() or None
            if column:
                results.append((column, aggregation))
        elif isinstance(metric, str):
            metric_clean = metric.strip()
            if metric_clean:
                results.append((metric_clean, None))

    return results


def _infer_metrics(
    *,
    question: str,
    raw_intent: dict[str, Any],
    table_meta: dict[str, Any],
    dimensions: list[str],
    ranking: dict[str, Any],
    ambiguities: list[dict[str, Any]],
    relationship_requested: bool,
    distribution_requested: bool,
    preserve_time_grain_metric: bool = False,
) -> list[dict[str, Any]]:
    question_lower = question.lower()
    if relationship_requested:
        relationship_metrics = _infer_relationship_metrics(
            question=question,
            table_meta=table_meta,
            ambiguities=ambiguities,
        )
        if relationship_metrics:
            return relationship_metrics

    derived_metric = _infer_derived_metric(
        question_lower=question_lower,
        table_meta=table_meta,
        ambiguities=ambiguities,
    )
    if derived_metric:
        return [derived_metric]

    question_tokens = tokenize(question)
    explicit_agg = _detect_explicit_aggregation(question_lower)
    grouping_intent = _has_grouping_intent(question_lower) or bool(dimensions)
    row_count_request = _is_explicit_row_count_request(question_lower)

    numeric_columns = table_meta["numeric_columns"]
    all_columns = table_meta["columns"]

    if distribution_requested:
        # Distribution should project one numeric series without aggregation.
        distribution_column = None
        for hint in _extract_metric_hints_from_question(question):
            distribution_column = _resolve_column_name_with_ambiguity(
                candidate=hint,
                columns=[table_meta["column_map"][c] for c in numeric_columns],
                context="metric",
                ambiguities=ambiguities,
            )
            if distribution_column:
                break
        if not distribution_column and numeric_columns:
            scored = sorted(
                numeric_columns,
                key=lambda col: _score_metric_column(col, question_tokens),
                reverse=True,
            )
            distribution_column = scored[0]
        if distribution_column:
            return [{"column": distribution_column, "aggregation": None, "alias": distribution_column}]

    metric_candidates: list[tuple[str, str | None]] = []
    seen_columns: set[str] = set()

    for raw_column, raw_agg in _iter_raw_metric_candidates(raw_intent):
        resolved = _resolve_column_name_with_ambiguity(
            candidate=raw_column,
            columns=all_columns,
            context="metric",
            ambiguities=ambiguities,
        )
        if resolved and resolved not in seen_columns:
            metric_candidates.append((resolved, raw_agg))
            seen_columns.add(resolved)

    resolved_any_hints: list[str] = []
    for hint in _extract_metric_hints_from_question(question):
        resolved_numeric = _resolve_column_name_with_ambiguity(
            candidate=hint,
            columns=[table_meta["column_map"][c] for c in numeric_columns],
            context="metric",
            ambiguities=ambiguities,
        )
        resolved = resolved_numeric or _resolve_column_name_with_ambiguity(
            candidate=hint,
            columns=all_columns,
            context="metric",
            ambiguities=ambiguities,
        )
        if resolved:
            resolved_any_hints.append(resolved)
        if resolved and resolved not in seen_columns and resolved in numeric_columns:
            metric_candidates.append((resolved, None))
            seen_columns.add(resolved)

    raw_metric_candidates = _iter_raw_metric_candidates(raw_intent)
    has_grouping_words = any(re.search(rf"\b{re.escape(word)}\b", question_lower) for word in GROUPING_WORDS)
    ranking_requested = bool(ranking.get("direction")) or isinstance(ranking.get("limit"), int)

    if explicit_agg == "COUNT" and not metric_candidates:
        entity_match = re.search(r"\bhow many\s+([a-z_][a-z0-9_ ]*)\b", question_lower)
        if entity_match:
            entity = entity_match.group(1).strip().split(" ")[0]
            metric_column = _resolve_column_name(entity, all_columns)
            if metric_column:
                metric_candidates.append((metric_column, None))
        if not metric_candidates and row_count_request:
            metric_candidates.append(("*", "COUNT"))

    if not metric_candidates:
        if resolved_any_hints and explicit_agg is None:
            for resolved_hint in resolved_any_hints:
                if resolved_hint not in seen_columns:
                    metric_candidates.append((resolved_hint, None))
                    seen_columns.add(resolved_hint)
        if numeric_columns:
            scored = sorted(
                numeric_columns,
                key=lambda col: _score_metric_column(col, question_tokens),
                reverse=True,
            )
            if not metric_candidates:
                metric_candidates.append((scored[0], None))
        else:
            if (
                not metric_candidates
                and row_count_request
                and not ranking_requested
                and not has_grouping_words
                and not raw_metric_candidates
            ):
                metric_candidates.append(("*", "COUNT"))

    metrics: list[dict[str, Any]] = []
    for metric_column, raw_agg in metric_candidates:
        aggregation: str | None = explicit_agg
        if preserve_time_grain_metric and aggregation in {"SUM", "AVG"}:
            aggregation = None

        if (
            aggregation == "COUNT"
            and metric_column != "*"
            and metric_column in numeric_columns
            and _is_business_metric_column(metric_column)
            and not row_count_request
        ):
            aggregation = "SUM"

        if aggregation is None and ranking.get("direction"):
            aggregation = _aggregation_for_ranking(
                metric_column,
                question_lower,
                has_dimensions=bool(dimensions),
            )

        if aggregation is None and raw_agg in VALID_AGGREGATIONS:
            aggregation = raw_agg
            if preserve_time_grain_metric and aggregation in {"SUM", "AVG"}:
                aggregation = None
            if (
                raw_agg == "SUM"
                and explicit_agg is None
                and (_is_rate_like(metric_column) or _is_avg_like(metric_column))
            ):
                aggregation = "AVG" if ranking.get("direction") else None

        if aggregation is None:
            if metric_column == "*":
                aggregation = "COUNT"
            elif _is_rate_like(metric_column) or _is_avg_like(metric_column):
                aggregation = "AVG" if ranking.get("direction") else None
            elif grouping_intent:
                if preserve_time_grain_metric and metric_column in numeric_columns:
                    aggregation = None
                elif _looks_additive(metric_column):
                    aggregation = "SUM"
                elif _looks_identifier_like(metric_column):
                    aggregation = "COUNT"
                elif metric_column in numeric_columns:
                    aggregation = "SUM"
                else:
                    aggregation = None
            else:
                aggregation = None

        if (
            aggregation == "COUNT"
            and metric_column != "*"
            and metric_column in numeric_columns
            and _is_business_metric_column(metric_column)
            and not row_count_request
        ):
            aggregation = "SUM"

        if aggregation and aggregation != "COUNT" and metric_column not in numeric_columns:
            if numeric_columns:
                resolved_numeric = _resolve_column_name(
                    metric_column,
                    [table_meta["column_map"][c] for c in numeric_columns],
                )
                if resolved_numeric:
                    metric_column = resolved_numeric
                else:
                    aggregation = None
            else:
                aggregation = None

        if aggregation == "COUNT" and not metric_column:
            metric_column = "*"

        alias = _metric_alias(aggregation, metric_column)
        metrics.append({"column": metric_column, "aggregation": aggregation, "alias": alias})

    return metrics
def _clean_dimension_phrase(phrase: str) -> str:
    tokens = [t for t in re.findall(r"[a-z0-9_]+", phrase.lower()) if t not in LANGUAGE_STOP_TOKENS]
    return " ".join(tokens[:4])


def _clean_metric_hint(phrase: str) -> str:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9_]+", str(phrase or "").lower())
        if token not in LANGUAGE_STOP_TOKENS
        and token not in {"total", "overall", "sum", "average", "avg", "mean", "number", "count"}
    ]
    return " ".join(tokens[:5])


def _extract_dimension_hints(question: str) -> list[str]:
    question_lower = question.lower()
    hints: list[str] = []

    top_entity_matches = re.findall(
        r"\b(?:top|bottom)\s+\d+\s+([a-z_][a-z0-9_ ]+?)\s+by\b",
        question_lower,
    )
    hints.extend(top_entity_matches)

    by_matches = re.findall(r"\b(?:by|per|across)\s+([a-z_][a-z0-9_ ]+)", question_lower)
    hints.extend(by_matches)

    each_matches = re.findall(r"\b(?:in each|for each)\s+([a-z_][a-z0-9_ ]+)", question_lower)
    hints.extend(each_matches)

    which_match = re.search(
        r"\b(?:which|what)\s+([a-z_][a-z0-9_ ]+?)\s+(?:has|have|with|shows|is|are)\b",
        question_lower,
    )
    if which_match:
        hints.append(which_match.group(1))

    rank_subject_match = re.search(
        r"\b([a-z_][a-z0-9_ ]+?)\s+with\s+(?:the\s+)?(?:highest|lowest|largest|smallest|best|worst)\b",
        question_lower,
    )
    if rank_subject_match:
        hints.append(rank_subject_match.group(1))

    # Keep projection-subject fallback conservative to avoid weak/over-eager dimensions.
    if not re.search(r"\b(?:by|per|across|for each|in each)\b", question_lower):
        projection_subject_match = re.search(
            r"\b(?:show|list|display|give)\s+([a-z_][a-z0-9_ ]+?)(?:\s+where\b|\s+in\b|$)",
            question_lower,
        )
        if projection_subject_match:
            hints.append(projection_subject_match.group(1))

    return [_clean_dimension_phrase(h) for h in hints if h.strip()]


def _infer_dimensions(
    question: str,
    raw_intent: dict[str, Any],
    table_meta: dict[str, Any],
    *,
    ambiguities: list[dict[str, Any]],
) -> list[str]:
    all_columns = table_meta["columns"]
    dimension_candidates = table_meta["dimension_columns"] + table_meta["date_columns"]
    resolved: list[str] = []

    for dim in raw_intent.get("dimensions", []) or []:
        if not isinstance(dim, str):
            continue
        mapped = _resolve_column_name_with_ambiguity(
            candidate=dim,
            columns=all_columns,
            context="dimension",
            ambiguities=ambiguities,
        )
        if mapped and mapped in dimension_candidates and mapped not in resolved:
            resolved.append(mapped)

    question_hints = _extract_dimension_hints(question)
    for hint in question_hints:
        normalized_hint = _clean_dimension_phrase(hint)
        mapped = _resolve_column_name_with_ambiguity(
            candidate=normalized_hint,
            columns=[table_meta["column_map"][c] for c in dimension_candidates],
            context="dimension",
            ambiguities=ambiguities,
        )
        # Avoid over-eager mapping for generic grouping words (e.g., "by order").
        if mapped:
            generic_grouping_terms = {"order", "orders", "item", "items", "record", "records", "data", "value"}
            hint_tokens = _expand_tokens(tokenize(normalized_hint))
            if len(hint_tokens) == 1:
                hint_token = next(iter(hint_tokens))
                normalized_mapped = str(mapped).strip().lower()
                if (
                    hint_token in generic_grouping_terms
                    and normalized_mapped != hint_token
                    and normalized_mapped.startswith(f"{hint_token}_")
                ):
                    ambiguities.append(
                        {
                            "type": "dimension_inference",
                            "message": (
                                f"Grouping phrase '{normalized_hint}' is ambiguous; "
                                f"skipped weak inferred dimension '{mapped}'."
                            ),
                            "candidates": [mapped],
                            "resolution": None,
                        }
                    )
                    mapped = None
        if mapped and mapped not in resolved:
            resolved.append(mapped)

    return resolved


def _normalize_numeric_filter_value(raw_value: str) -> int | float:
    if "." in raw_value:
        return float(raw_value)
    return int(raw_value)


def _filter_column_candidates(candidate_column: str) -> list[str]:
    candidate = re.sub(r"\s+", " ", str(candidate_column or "").strip())
    if not candidate:
        return []

    variants: list[str] = []
    for splitter in (" where ", " with ", " for ", " in ", " and "):
        if splitter in candidate:
            tail = candidate.split(splitter)[-1].strip()
            if tail:
                variants.append(tail)
    tokens = candidate.split(" ")
    if len(tokens) >= 3:
        variants.append(" ".join(tokens[-3:]))
    if len(tokens) >= 2:
        variants.append(" ".join(tokens[-2:]))
    variants.append(tokens[-1])
    variants.append(candidate)

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        key = variant.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(variant)
    return deduped


def _resolve_filter_column(
    candidate_column: str,
    all_columns: list[dict[str, Any]],
    column_map: dict[str, dict[str, Any]],
    *,
    require_numeric: bool,
    ambiguities: list[dict[str, Any]],
) -> str | None:
    for candidate in _filter_column_candidates(candidate_column):
        resolved = _resolve_column_name_with_ambiguity(
            candidate=candidate,
            columns=all_columns,
            context="filter",
            ambiguities=ambiguities,
        )
        if not resolved:
            continue
        if require_numeric and not column_map[resolved].get("is_numeric"):
            continue
        if not require_numeric and column_map[resolved].get("is_numeric"):
            continue
        return resolved
    return None


def _normalize_filters(
    question: str,
    raw_intent: dict[str, Any],
    table_meta: dict[str, Any],
    *,
    ambiguities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    all_columns = table_meta["columns"]
    column_map = table_meta["column_map"]
    seen: set[tuple[str, str, str]] = set()

    for filter_item in raw_intent.get("filters", []) or []:
        if not isinstance(filter_item, dict):
            continue
        column = _resolve_column_name_with_ambiguity(
            candidate=str(filter_item.get("column", "")),
            columns=all_columns,
            context="filter",
            ambiguities=ambiguities,
        )
        operator = (filter_item.get("operator") or "=").upper().strip()
        value = filter_item.get("value")

        if not column or value is None:
            continue
        if operator not in VALID_FILTER_OPERATORS:
            continue

        if operator == "BETWEEN":
            if isinstance(value, (list, tuple)) and len(value) == 2:
                value = [value[0], value[1]]
            elif isinstance(value, dict):
                low = value.get("low")
                high = value.get("high")
                if low is None or high is None:
                    continue
                value = [low, high]
            else:
                continue

        fingerprint = (column, operator, str(value))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        filters.append({"column": column, "operator": operator, "value": value})

    question_lower = question.lower()

    for pattern in BETWEEN_FILTER_PATTERNS:
        for match in re.finditer(pattern, question_lower):
            candidate_column = match.group(1).strip()
            column = _resolve_filter_column(
                candidate_column,
                all_columns,
                column_map,
                require_numeric=True,
                ambiguities=ambiguities,
            )
            if not column:
                continue
            low = _normalize_numeric_filter_value(match.group(2).strip())
            high = _normalize_numeric_filter_value(match.group(3).strip())
            low_fingerprint = (column, ">=", str(low))
            high_fingerprint = (column, "<=", str(high))
            if low_fingerprint not in seen:
                seen.add(low_fingerprint)
                filters.append({"column": column, "operator": ">=", "value": low})
            if high_fingerprint not in seen:
                seen.add(high_fingerprint)
                filters.append({"column": column, "operator": "<=", "value": high})

    for pattern_item in NUMERIC_FILTER_PATTERNS:
        pattern = pattern_item["pattern"]
        default_operator = pattern_item["operator"]
        captures_operator = bool(pattern_item["captures_operator"])
        for match in re.finditer(pattern, question_lower):
            candidate_column = match.group(1).strip()
            if captures_operator:
                raw_operator = match.group(2).strip()
                if raw_operator in {"=>", ">="}:
                    normalized_operator = ">="
                elif raw_operator in {"=<", "<="}:
                    normalized_operator = "<="
                elif raw_operator in {"==", "="}:
                    normalized_operator = "="
                else:
                    normalized_operator = default_operator
                raw_value = match.group(3).strip()
            else:
                normalized_operator = default_operator
                raw_value = match.group(2).strip()
            column = _resolve_filter_column(
                candidate_column,
                all_columns,
                column_map,
                require_numeric=True,
                ambiguities=ambiguities,
            )
            if not column:
                continue
            value = _normalize_numeric_filter_value(raw_value)
            fingerprint = (column, normalized_operator, str(value))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            filters.append({"column": column, "operator": normalized_operator, "value": value})

    for pattern in TEXT_FILTER_PATTERNS:
        for match in re.finditer(pattern, question_lower):
            groups = [group.strip() for group in match.groups() if group and group.strip()]
            if len(groups) < 2:
                continue
            if pattern == TEXT_FILTER_PATTERNS[2]:
                value, candidate_column = groups[0], groups[1]
            else:
                candidate_column, value = groups[0], groups[1]
            column = _resolve_filter_column(
                candidate_column,
                all_columns,
                column_map,
                require_numeric=False,
                ambiguities=ambiguities,
            )
            if not column:
                continue
            normalized_value = value.strip(" '\"")
            if not normalized_value:
                continue
            fingerprint = (column, "=", normalized_value)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            filters.append({"column": column, "operator": "=", "value": normalized_value})

    for pattern in TEXT_CONTAINS_PATTERNS:
        for match in re.finditer(pattern, question_lower):
            candidate_column = match.group(1).strip()
            raw_value = match.group(2).strip()
            column = _resolve_filter_column(
                candidate_column,
                all_columns,
                column_map,
                require_numeric=False,
                ambiguities=ambiguities,
            )
            if not column:
                continue
            value = raw_value.strip(" '\"")
            if not value:
                continue
            like_value = value if "%" in value else f"%{value}%"
            fingerprint = (column, "LIKE", like_value)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            filters.append({"column": column, "operator": "LIKE", "value": like_value})

    return filters


def _infer_year_filter(question_lower: str, table_meta: dict[str, Any]) -> dict[str, Any] | None:
    year_match = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", question_lower)
    if not year_match:
        return None

    year_value = int(year_match.group(1))
    for column in table_meta["date_columns"] + table_meta["dimension_columns"]:
        column_lower = column.lower()
        if "year" in column_lower:
            return {"column": column, "operator": "=", "value": year_value}
    return None


def _normalize_order_by(
    raw_intent: dict[str, Any],
    table_meta: dict[str, Any],
    *,
    metric_aliases: list[str],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    all_columns = table_meta["columns"]
    alias_set = set(metric_aliases)

    for order in raw_intent.get("order_by", []) or []:
        if not isinstance(order, dict):
            continue

        column = order.get("column")
        direction = (order.get("direction") or "ASC").upper()
        if direction not in {"ASC", "DESC"}:
            direction = "ASC"

        if column in alias_set:
            resolved = column
        else:
            resolved = _resolve_column_name(column or "", all_columns)
        if not resolved:
            continue

        result.append({"column": resolved, "direction": direction})

    return result


def _derive_operations(
    *,
    metrics: list[dict[str, Any]],
    dimensions: list[str],
    filters: list[dict[str, Any]],
    order_by: list[dict[str, Any]],
    limit: int | None,
    ranking_requested: bool,
    relationship_requested: bool,
    distribution_requested: bool,
    time_grouping_detected: bool,
) -> list[str]:
    operations: list[str] = ["projection"]

    if any(metric.get("aggregation") for metric in metrics):
        operations.append("aggregation")
    if dimensions:
        operations.append("grouping")
    if filters:
        operations.append("filtering")
    if ranking_requested:
        operations.append("ranking")
    if order_by:
        operations.append("sorting")
    if limit:
        operations.append("limiting")
    if dimensions and len(metrics) > 1:
        operations.append("comparison")
    if relationship_requested:
        operations.append("relationship")
        if "comparison" not in operations:
            operations.append("comparison")
    if distribution_requested:
        operations.append("distribution")
    if time_grouping_detected:
        operations.append("time_grouping")

    return operations


def _infer_primary_intent(
    *,
    operations: list[str],
    relationship_requested: bool,
    distribution_requested: bool,
    time_grouping_detected: bool,
) -> str:
    if time_grouping_detected:
        return "time_series"
    if relationship_requested:
        return "correlation"
    if distribution_requested:
        return "distribution"
    if "ranking" in operations:
        return "ranking"
    if "aggregation" in operations and "grouping" in operations:
        return "aggregation"
    if "comparison" in operations:
        return "comparison"
    if "filtering" in operations:
        return "filtering"
    return "projection"

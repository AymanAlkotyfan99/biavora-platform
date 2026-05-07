from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from bi_platform_shared.contracts.chart import ChartTypeEnum, normalize_chart_type
from bi_platform_shared.contracts.intent import CanonicalIntent, OperationCode

from intent_extraction.error_handler import (
    IntentExtractionInputError,
    IntentExtractionModelOutputError,
    classify_intent_extraction_error,
    decide_intent_extraction_action,
)
from intent_extraction.llm_extractor import extract_structured_intent, infer_intent_type
from intent_extraction.predictive_parser import (
    FORECAST_MISSING_TARGET_COLUMN,
    FORECAST_MISSING_TIME_COLUMN,
    PredictiveSchemaError,
    parse_predictive_intent,
)
from intent_extraction.routing import route_intent
from intent_extraction.schemas import (
    IntentExtractionConfig,
    IntentExtractionTaskResult,
    NextStepType,
    build_intent_extraction_failed_result,
    build_intent_extraction_success_result,
)
from intent_extraction.validation import validate_structured_intent
from shared.query_planner import normalize_analytical_intent
from shared.confidence import stage_confidence
from shared.pipeline_trace import make_attempt
from shared.semantic_contract_validator import validate_semantic_contract
from shared.stage_contract import stage_allows_progress
from shared.time_semantics_detector import detect_time_semantics, enrich_intent_with_time_semantics
from shared.deterministic_chart_selector import apply_chart_selection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _schema_column_names(schema: dict[str, list[dict[str, Any]]]) -> list[str]:
    names: list[str] = []
    for cols in (schema or {}).values():
        if not isinstance(cols, list):
            continue
        for col in cols:
            if isinstance(col, dict) and col.get("name"):
                names.append(str(col["name"]).strip())
    return names


def _phrase_query_from_hints(preprocess_hints: dict[str, Any] | None) -> str | None:
    if not isinstance(preprocess_hints, dict):
        return None
    s = str(
        preprocess_hints.get("original_user_question")
        or preprocess_hints.get("original_query_for_intent")
        or ""
    ).strip()
    return s or None


def _apply_time_semantics_only(
    *,
    query: str,
    schema: dict[str, list[dict[str, Any]]],
    intent: dict[str, Any],
    phrase_query: str | None = None,
) -> dict[str, Any]:
    names = _schema_column_names(schema)
    q = str(query or "").strip()
    pq = str(phrase_query or "").strip()
    ts = detect_time_semantics(q, names)
    if pq and pq.lower() != q.lower():
        ts_p = detect_time_semantics(pq, names)
        if ts_p.is_time_series:
            ts = ts_p
    return enrich_intent_with_time_semantics(dict(intent), ts)


def _apply_time_semantics_and_chart(
    *,
    query: str,
    schema: dict[str, list[dict[str, Any]]],
    intent: dict[str, Any],
    preprocess_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pq = _phrase_query_from_hints(preprocess_hints)
    merged = _apply_time_semantics_only(query=query, schema=schema, intent=intent, phrase_query=pq)
    combined_q = " ".join(
        part for part in (str(query or "").strip(), str(pq or "").strip()) if part
    )
    return apply_chart_selection(merged, user_query=combined_q)


def _get_logger() -> logging.Logger:
    return logging.getLogger(__name__)


def _log_event(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    payload = {"timestamp": _utc_now(), **fields}
    logger.log(level, "%s | %s", message, json.dumps(payload, sort_keys=True, default=str))


def _validate_inputs(query: str, schema: dict[str, list[dict[str, Any]]]) -> tuple[str, dict[str, list[dict[str, Any]]]]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise IntentExtractionInputError("query is empty.")

    if not isinstance(schema, dict):
        raise IntentExtractionInputError("schema must be a dictionary.")
    if not schema:
        raise IntentExtractionInputError("schema is empty.")

    return normalized_query, schema


# ---------------------------------------------------------------------------
# CanonicalIntent validation + repair pass (Phase 5 / CRIT-14)
# ---------------------------------------------------------------------------


_CANONICAL_AGGREGATIONS = {"sum", "count", "count_distinct", "avg", "min", "max", "median"}
_CANONICAL_FILTER_OPERATORS = {
    "eq",
    "ne",
    "in",
    "not_in",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "like",
    "ilike",
    "is_null",
    "is_not_null",
}
_LEGACY_OPERATOR_MAP = {
    "=": "eq",
    "!=": "ne",
    "<>": "ne",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
    "in": "in",
    "not_in": "not_in",
    "like": "like",
    "ilike": "ilike",
    "between": "between",
}


def _coerce_canonical_aggregation(raw: Any) -> str | None:
    token = str(raw or "").strip().lower()
    if not token:
        return None
    if token in _CANONICAL_AGGREGATIONS:
        return token
    if token in {"distinct_count", "count distinct"}:
        return "count_distinct"
    return None


def _coerce_canonical_operator(raw: Any) -> str:
    token = str(raw or "").strip().lower()
    if not token:
        return "eq"
    if token in _CANONICAL_FILTER_OPERATORS:
        return token
    return _LEGACY_OPERATOR_MAP.get(token, "eq")


def _intent_dict_to_canonical_payload(
    *,
    query: str,
    intent: dict[str, Any],
    schema: dict[str, list[dict[str, Any]]],
    confidence: float,
) -> dict[str, Any]:
    """Translate the dict-shaped IR into a payload that ``CanonicalIntent``
    accepts. The translation is *non-destructive* – the original dict is left
    untouched – and is purely a contract-validation helper.
    """

    def _str_list(values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        return [str(v).strip() for v in values if str(v or "").strip()]

    metrics_specs = intent.get("metric_specs") if isinstance(intent.get("metric_specs"), list) else []
    metrics: list[dict[str, Any]] = []
    seen_metric_names: set[str] = set()
    for spec in metrics_specs:
        if not isinstance(spec, dict):
            continue
        column = str(spec.get("column", "")).strip()
        if not column or column == "*":
            continue
        alias = str(spec.get("alias") or "").strip() or None
        name = alias or column
        if name in seen_metric_names:
            continue
        seen_metric_names.add(name)
        metrics.append(
            {
                "name": name,
                "column": column,
                "aggregation": _coerce_canonical_aggregation(spec.get("aggregation")),
                "alias": alias,
            }
        )

    if not metrics:
        for column in _str_list(intent.get("metrics")):
            if column == "*":
                continue
            if column in seen_metric_names:
                continue
            seen_metric_names.add(column)
            metrics.append(
                {
                    "name": column,
                    "column": column,
                    "aggregation": _coerce_canonical_aggregation(intent.get("aggregation")),
                    "alias": None,
                }
            )

    dimensions = _str_list(intent.get("dimensions"))

    filters: list[dict[str, Any]] = []
    for flt in intent.get("filters") or []:
        if not isinstance(flt, dict):
            continue
        column = str(flt.get("column", "")).strip()
        if not column:
            continue
        filters.append(
            {
                "column": column,
                "operator": _coerce_canonical_operator(flt.get("operator")),
                "value": flt.get("value"),
                "case_sensitive": bool(flt.get("case_sensitive", False)),
            }
        )

    operations: list[str] = []
    for op in intent.get("operations") or []:
        token = str(op or "").strip().lower()
        if not token:
            continue
        if token in {member.value for member in OperationCode}:
            operations.append(token)
            continue
        legacy_alias = {
            "aggregation": OperationCode.AGGREGATE.value,
            "grouping": OperationCode.GROUP_BY.value,
            "filtering": OperationCode.FILTER.value,
            "ranking": OperationCode.SORT.value,
            "limiting": OperationCode.LIMIT.value,
            "comparison": OperationCode.COMPARE.value,
            "forecasting": OperationCode.FORECAST.value,
            "time_grouping": OperationCode.TIME_SERIES.value,
            "distribution": OperationCode.DISTRIBUTION.value,
            "projection": None,
        }.get(token)
        if legacy_alias:
            operations.append(legacy_alias)
    operations = list(dict.fromkeys(operations))

    order_by: list[dict[str, str]] = []
    for ob in intent.get("order_by") or []:
        if not isinstance(ob, dict):
            continue
        column = str(ob.get("column", "")).strip()
        if not column:
            continue
        direction = str(ob.get("direction", "desc")).strip().lower()
        if direction not in {"asc", "desc"}:
            direction = "desc"
        order_by.append({"column": column, "direction": direction})

    ranking_payload: dict[str, Any] | None = None
    raw_ranking = intent.get("ranking") if isinstance(intent.get("ranking"), dict) else {}
    raw_direction = str(raw_ranking.get("direction") or "").strip().lower()
    if raw_direction in {"asc", "desc"}:
        n_value = intent.get("limit") or raw_ranking.get("n") or 10
        try:
            n_int = max(1, int(n_value))
        except (TypeError, ValueError):
            n_int = 10
        ranking_payload = {
            "direction": "bottom" if raw_direction == "asc" else "top",
            "n": n_int,
            "by": (metrics[0]["name"] if metrics else None),
        }

    forecast_payload: dict[str, Any] | None = None
    if intent.get("intent_type") == "predictive" or intent.get("requires_forecast"):
        horizon_raw = intent.get("forecast_horizon") or intent.get("horizon") or 7
        try:
            horizon_int = max(1, min(3650, int(horizon_raw)))
        except (TypeError, ValueError):
            horizon_int = 7
        forecast_payload = {
            "horizon": horizon_int,
            "horizon_unit": str(intent.get("granularity") or "day").strip().lower() or "day",
            "target_column": (
                str(intent.get("forecast_target_column") or "").strip()
                or str(intent.get("target_column") or "").strip()
                or (metrics[0]["column"] if metrics else None)
            ) or None,
            "date_column": (
                str(intent.get("forecast_date_column") or "").strip()
                or str(intent.get("time_column") or "").strip()
                or (dimensions[0] if dimensions else None)
            ) or None,
        }

    chart_hint_raw = (
        intent.get("selected_chart_type")
        or intent.get("chart_type")
        or (intent.get("chart") or {}).get("type")
    )
    chart_hint_value: str | None = None
    if chart_hint_raw:
        chart_hint_value = normalize_chart_type(str(chart_hint_raw)).value
        if chart_hint_value not in {member.value for member in ChartTypeEnum}:
            chart_hint_value = None

    selected_columns: list[str] = []
    for col in intent.get("metrics") or []:
        c = str(col).strip()
        if c and c != "*" and c not in selected_columns:
            selected_columns.append(c)
    for col in dimensions:
        if col not in selected_columns:
            selected_columns.append(col)

    intent_type = str(intent.get("intent_type") or "analytical").strip().lower()
    if intent_type not in {"analytical", "predictive", "non_data", "invalid", "ambiguous"}:
        intent_type = "analytical"

    payload: dict[str, Any] = {
        "intent_type": intent_type,
        "confidence": max(0.0, min(1.0, float(confidence or 0.0))),
        "metrics": metrics,
        "dimensions": dimensions,
        "filters": filters,
        "operations": operations,
        "order_by": order_by,
        "ranking": ranking_payload,
        "forecast": forecast_payload,
        "chart_type_hint": chart_hint_value,
        "selected_columns": selected_columns,
        "selected_table": str(intent.get("table") or "").strip() or None,
        "raw_question": query,
    }

    time_granularity = str(intent.get("time_granularity") or "").strip().lower()
    time_column = str(intent.get("time_column") or "").strip()
    if time_granularity or time_column:
        payload["time_binding"] = {
            "column": time_column or None,
            "grain": time_granularity or None,
        }

    return payload


def _validate_canonical_intent(
    *,
    query: str,
    intent: dict[str, Any],
    schema: dict[str, list[dict[str, Any]]],
    confidence: float,
) -> tuple[CanonicalIntent | None, str]:
    """Validate the dict-shaped intent against ``CanonicalIntent``.

    Phase 5 / CRIT-14: returns ``(canonical_intent, error_message)``. The
    caller treats a non-empty error_message as the trigger for the
    deterministic repair pass.
    """

    try:
        payload = _intent_dict_to_canonical_payload(
            query=query,
            intent=intent,
            schema=schema,
            confidence=confidence,
        )
        canonical = CanonicalIntent.model_validate(payload)
    except ValidationError as exc:
        return None, exc.json()
    except Exception as exc:  # noqa: BLE001
        return None, f"canonical_intent_unexpected_error: {exc}"
    return canonical, ""


def _next_step_for_intent_type(intent_type: str) -> NextStepType:
    return "forecasting" if intent_type == "predictive" else "metabase"


def _apply_chart_intent_fallback(*, query: str, intent: dict[str, Any]) -> tuple[dict[str, Any], str]:
    normalized_query = str(query or "").strip().lower()
    if not isinstance(intent, dict):
        return {}, ""

    applied_reasons: list[str] = []
    time_series_phrase = bool(
        re.search(r"\b(per|by)\s+(day|week|month|quarter|year|hour)\b", normalized_query)
        or re.search(r"\b(over time|time series|trend|progression|chronological|timeline)\b", normalized_query)
        or re.search(r"\b(daily|weekly|monthly|quarterly|yearly)\b", normalized_query)
        or re.search(r"\b(month over month|year over year|mom|yoy)\b", normalized_query)
    )

    distribution_tokens = ("distribution", "distributed", "histogram", "spread", "frequency")
    if any(token in normalized_query for token in distribution_tokens):
        chart_payload = intent.get("chart") if isinstance(intent.get("chart"), dict) else {}
        if str(chart_payload.get("type", "")).strip().lower() != "histogram":
            applied_reasons.append("query_mentions_distribution_histogram")
        intent["is_distribution"] = True
        intent["is_time_series"] = False
        intent["is_percentage"] = False
        intent["requires_forecast"] = False
        intent["metric_type"] = "absolute"
        intent["chart"] = {
            **chart_payload,
            "type": "histogram",
            "metric_type": "absolute",
            "group_by": chart_payload.get("group_by"),
        }

    percentage_tokens = ("percentage", "percent", "share")
    explicit_pie_request = "pie chart" in normalized_query or "pie graph" in normalized_query
    if any(token in normalized_query for token in percentage_tokens):
        if str(intent.get("metric_type", "")).strip().lower() != "percentage":
            applied_reasons.append("query_mentions_percentage_share_distribution")
        intent["metric_type"] = "percentage"
        chart_payload = intent.get("chart") if isinstance(intent.get("chart"), dict) else {}
        chart_type_lower = str(chart_payload.get("type", "")).strip().lower()
        allow_pie = (not time_series_phrase or explicit_pie_request) and chart_type_lower not in {"pie", "histogram"}
        if allow_pie:
            applied_reasons.append("percentage_semantics_prefer_pie")
            intent["chart"] = {
                **chart_payload,
                "type": "pie",
                "metric_type": "percentage",
                "group_by": chart_payload.get("group_by"),
            }

    if "pie" in normalized_query:
        chart_payload = intent.get("chart") if isinstance(intent.get("chart"), dict) else {}
        current_type = str(chart_payload.get("type", "")).strip().lower()
        if current_type != "pie":
            applied_reasons.append("query_mentions_pie")
        intent["chart"] = {
            **chart_payload,
            "type": "pie",
            "metric_type": "percentage" if str(intent.get("metric_type", "")).strip().lower() == "percentage" else chart_payload.get("metric_type"),
            "group_by": chart_payload.get("group_by"),
        }

    chart_payload = intent.get("chart") if isinstance(intent.get("chart"), dict) else {}
    chart_type = str(chart_payload.get("type", "")).strip().lower()
    if chart_type in {"pie", "histogram"}:
        intent["selected_chart_type"] = chart_type
        intent["chart_type"] = chart_type
        if str(intent.get("metric_type", "")).strip().lower() == "percentage":
            applied_reasons.append("Detected 'percentage share' -> pie chart")

    if "chart" not in intent or not isinstance(intent.get("chart"), dict):
        intent["chart"] = {"type": None, "metric_type": None, "group_by": None}
    else:
        chart = intent["chart"]
        chart.setdefault("type", None)
        chart.setdefault("metric_type", None)
        chart.setdefault("group_by", None)

    intent.setdefault("metric_type", "")
    intent.setdefault("selected_chart_type", "")
    intent.setdefault("chart_type", "")
    return intent, ("; ".join(dict.fromkeys(applied_reasons)) if applied_reasons else "")


def _extract_and_validate(
    *,
    query: str,
    schema: dict[str, list[dict[str, Any]]],
    config: IntentExtractionConfig,
    logger: logging.Logger,
    preprocess_hints: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    _log_event(
        logger,
        logging.INFO,
        "Intent extraction started",
        input_query=query,
        schema_table_count=len(schema),
    )

    extracted_result = extract_structured_intent(
        query=query,
        schema=schema,
        config=config,
        logger=logger,
        log_event=_log_event,
        include_debug=True,
    )
    if isinstance(extracted_result, tuple):
        extracted_intent, llm_debug = extracted_result
    else:
        extracted_intent = extracted_result
        llm_debug = {}
    _log_event(
        logger,
        logging.INFO,
        "Intent extracted from LLM",
        extracted_intent=extracted_intent,
    )

    extracted_intent, fallback_reason = _apply_chart_intent_fallback(query=query, intent=extracted_intent)
    if fallback_reason:
        _log_event(
            logger,
            logging.INFO,
            "Chart intent fallback applied before validation",
            fallback_reason=fallback_reason,
            selected_chart_type=extracted_intent.get("selected_chart_type"),
            metric_type=extracted_intent.get("metric_type"),
        )

    validated_intent = validate_structured_intent(
        intent=extracted_intent,
        schema=schema,
    )
    validated_intent = _apply_time_semantics_only(
        query=query,
        schema=schema,
        intent=validated_intent,
        phrase_query=_phrase_query_from_hints(preprocess_hints),
    )
    repaired_intent = validate_semantic_contract(
        question=query,
        intent=validated_intent,
        schema=schema,
        preprocess_hints=preprocess_hints,
    )
    if repaired_intent != validated_intent:
        validated_intent = validate_structured_intent(intent=repaired_intent, schema=schema)

    validated_intent = _apply_time_semantics_and_chart(
        query=query,
        schema=schema,
        intent=validated_intent,
        preprocess_hints=preprocess_hints,
    )

    # Phase 5 / CRIT-14: canonical-intent validation + repair pass.
    canonical_intent, canonical_error = _validate_canonical_intent(
        query=query,
        intent=validated_intent,
        schema=schema,
        confidence=0.86,
    )
    canonical_repair_applied = False
    if canonical_intent is None:
        _log_event(
            logger,
            logging.WARNING,
            "CanonicalIntent validation failed; running deterministic repair pass.",
            canonical_error=canonical_error[:500],
        )
        repair_repaired = validate_semantic_contract(
            question=query,
            intent=validated_intent,
            schema=schema,
            preprocess_hints=preprocess_hints,
        )
        validated_intent = validate_structured_intent(intent=repair_repaired, schema=schema)
        canonical_intent, canonical_error = _validate_canonical_intent(
            query=query,
            intent=validated_intent,
            schema=schema,
            confidence=0.74,
        )
        canonical_repair_applied = True
        if canonical_intent is None:
            _log_event(
                logger,
                logging.ERROR,
                "CanonicalIntent repair pass failed.",
                canonical_error=canonical_error[:500],
            )
        else:
            validated_intent = _apply_time_semantics_and_chart(
                query=query,
                schema=schema,
                intent=validated_intent,
                preprocess_hints=preprocess_hints,
            )

    detected_type = validated_intent["intent_type"]
    _log_event(
        logger,
        logging.INFO,
        "Intent type classified",
        detected_type=detected_type,
    )
    if fallback_reason or canonical_repair_applied or canonical_error:
        llm_debug = {
            **llm_debug,
            "chart_intent_fallback_applied": bool(fallback_reason),
            "chart_intent_fallback_reason": fallback_reason,
            "chart_intent_selected_chart_type": validated_intent.get("selected_chart_type", ""),
            "chart_intent_metric_type": validated_intent.get("metric_type", ""),
            "canonical_intent_repair_applied": canonical_repair_applied,
            "canonical_intent_error": canonical_error if canonical_intent is None else "",
            "canonical_intent_valid": canonical_intent is not None,
            "canonical_intent": (
                canonical_intent.model_dump(mode="json") if canonical_intent is not None else None
            ),
        }
    else:
        llm_debug = {
            **llm_debug,
            "canonical_intent_valid": True,
            "canonical_intent": canonical_intent.model_dump(mode="json"),
        }
    return extracted_intent, validated_intent, detected_type, llm_debug


def _fallback_extract_and_validate(
    *,
    query: str,
    schema: dict[str, list[dict[str, Any]]],
    logger: logging.Logger,
    preprocess_hints: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    normalized_intent = normalize_analytical_intent(
        question=query,
        raw_intent={},
        schema=schema,
    )
    fallback_metrics = [
        str(metric.get("column", "")).strip()
        for metric in normalized_intent.get("metrics", [])
        if isinstance(metric, dict) and str(metric.get("column", "")).strip()
    ]
    fallback_dimensions = [
        str(dimension).strip()
        for dimension in normalized_intent.get("dimensions", [])
        if str(dimension).strip()
    ]
    fallback_filters = [
        filter_item
        for filter_item in normalized_intent.get("filters", [])
        if isinstance(filter_item, dict)
    ]
    fallback_aggregation = "SUM"
    for metric in normalized_intent.get("metrics", []):
        if isinstance(metric, dict) and str(metric.get("aggregation", "")).strip():
            fallback_aggregation = str(metric.get("aggregation", "")).strip().upper()
            break
    fallback_target_column = fallback_metrics[0] if fallback_metrics else "*"
    normalized_question = str(query or "").strip().lower()
    time_granularity = str(normalized_intent.get("time_granularity", "")).strip().lower()
    time_column = str(normalized_intent.get("time_column", "")).strip()
    is_time_series = bool(normalized_intent.get("time_grouping_detected")) or bool(time_granularity)
    selected_chart_type = "table"
    if is_time_series and len(fallback_metrics) > 1:
        selected_chart_type = "line_multi"
    elif is_time_series:
        selected_chart_type = "line"
    elif any(token in normalized_question for token in ("share", "percentage", "percent", "contribution", "proportion", "part of total")):
        selected_chart_type = "pie"
    elif any(token in normalized_question for token in ("distribution", "spread", "frequency", "histogram")):
        selected_chart_type = "histogram"
    elif any(token in normalized_question for token in ("relationship", "correlation", "vs", "versus", "effect of", "impact of")) and len(fallback_metrics) >= 2:
        selected_chart_type = "scatter"
    elif fallback_dimensions and fallback_metrics:
        selected_chart_type = "bar"
    elif len(fallback_metrics) == 1 and not fallback_dimensions:
        selected_chart_type = "card"
    x_axis = "period" if is_time_series else (fallback_dimensions[0] if fallback_dimensions else "")
    y_axis = [f"sum_{metric}" if fallback_aggregation == "SUM" and metric != "*" else metric for metric in fallback_metrics if metric and metric != "*"]
    inferred_type = infer_intent_type(query=query, hinted_intent_type=None)
    extracted_intent = {
        "intent_type": inferred_type,
        "intent": str(normalized_intent.get("intent", "projection")),
        "metrics": fallback_metrics or ["*"],
        "metric_specs": [
            {
                "column": metric.get("column"),
                "aggregation": metric.get("aggregation"),
                "alias": metric.get("alias"),
            }
            for metric in normalized_intent.get("metrics", [])
            if isinstance(metric, dict) and metric.get("column")
        ],
        "dimensions": fallback_dimensions,
        "filters": fallback_filters,
        "time_range": "all_time",
        "aggregation": fallback_aggregation,
        "target_column": fallback_target_column,
        "table": str(normalized_intent.get("table", "")).strip(),
        "order_by": normalized_intent.get("order_by", []),
        "limit": normalized_intent.get("limit"),
        "ranking": normalized_intent.get("ranking", {}),
        "operations": normalized_intent.get("operations", []),
        "ambiguities": normalized_intent.get("ambiguities", []),
        "chart": {"type": selected_chart_type, "metric_type": None, "group_by": x_axis or None},
        "metric_type": "",
        "selected_chart_type": selected_chart_type,
        "chart_type": selected_chart_type,
        "final_chart_type": selected_chart_type,
        "x_axis": x_axis,
        "y_axis": y_axis,
        "is_time_series": is_time_series,
        "time_column": time_column,
        "time_granularity": time_granularity,
        "time_dimension_alias": "period" if is_time_series else "",
        "time_grouping_detected": is_time_series,
        "is_percentage": selected_chart_type == "pie",
        "is_distribution": selected_chart_type in {"pie", "histogram"},
        "chart_reason": "deterministic fallback chart selection",
        "chart_reason_code": "deterministic_chart_selection",
    }
    extracted_intent, fallback_reason = _apply_chart_intent_fallback(query=query, intent=extracted_intent)
    validated_intent = validate_structured_intent(intent=extracted_intent, schema=schema)
    validated_intent = _apply_time_semantics_only(
        query=query,
        schema=schema,
        intent=validated_intent,
        phrase_query=_phrase_query_from_hints(preprocess_hints),
    )
    repaired_intent = validate_semantic_contract(
        question=query,
        intent=validated_intent,
        schema=schema,
        preprocess_hints=preprocess_hints,
    )
    if repaired_intent != validated_intent:
        validated_intent = validate_structured_intent(intent=repaired_intent, schema=schema)
    validated_intent = _apply_time_semantics_and_chart(
        query=query,
        schema=schema,
        intent=validated_intent,
        preprocess_hints=preprocess_hints,
    )
    detected_type = validated_intent["intent_type"]
    _log_event(
        logger,
        logging.WARNING,
        "Intent extraction fallback used",
        extracted_intent=extracted_intent,
        validated_intent=validated_intent,
    )
    return (
        extracted_intent,
        validated_intent,
        detected_type,
        {
            "provider": "deterministic_fallback",
            "fallback_source": "shared.query_planner.normalize_analytical_intent",
            "normalized_intent": normalized_intent,
            "chart_intent_fallback_applied": bool(fallback_reason),
            "chart_intent_fallback_reason": fallback_reason,
            "chart_intent_selected_chart_type": validated_intent.get("selected_chart_type", ""),
            "chart_intent_metric_type": validated_intent.get("metric_type", ""),
        },
    )


def _rules_first_extract_and_validate(
    *,
    query: str,
    schema: dict[str, list[dict[str, Any]]],
    config: IntentExtractionConfig,
    logger: logging.Logger,
    preprocess_hints: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    rules_extracted, rules_validated, rules_type, rules_debug = _fallback_extract_and_validate(
        query=query,
        schema=schema,
        logger=logger,
        preprocess_hints=preprocess_hints,
    )
    llm_debug: dict[str, Any] = {}
    llm_error = ""
    try:
        llm_extracted, llm_validated, _llm_type, llm_debug = _extract_and_validate(
            query=query,
            schema=schema,
            config=config,
            logger=logger,
            preprocess_hints=preprocess_hints,
        )
    except Exception as exc:  # noqa: BLE001
        llm_extracted, llm_validated = {}, {}
        llm_error = str(exc)
        if isinstance(exc, IntentExtractionModelOutputError):
            raise

    completed_intent = dict(rules_validated)
    for key, value in (llm_validated if isinstance(llm_validated, dict) else {}).items():
        current = completed_intent.get(key)
        if current in (None, "", [], {}) and value not in (None, "", [], {}):
            completed_intent[key] = value

    completed_intent = validate_structured_intent(intent=completed_intent, schema=schema)
    completed_intent = _apply_time_semantics_only(
        query=query,
        schema=schema,
        intent=completed_intent,
        phrase_query=_phrase_query_from_hints(preprocess_hints),
    )
    repaired_intent = validate_semantic_contract(
        question=query,
        intent=completed_intent,
        schema=schema,
        preprocess_hints=preprocess_hints,
    )
    if repaired_intent != completed_intent:
        completed_intent = validate_structured_intent(intent=repaired_intent, schema=schema)

    completed_intent = _apply_time_semantics_and_chart(
        query=query,
        schema=schema,
        intent=completed_intent,
        preprocess_hints=preprocess_hints,
    )

    completed_type = completed_intent["intent_type"]
    debug = {
        **rules_debug,
        "provider": "rules_first_then_llm_validation",
        "rules_first": True,
        "deterministic_intent": rules_validated,
        "llm_raw_intent": llm_extracted if isinstance(llm_extracted, dict) else {},
        "llm_validation_used": bool(llm_validated),
        "llm_validation_error": llm_error,
        "llm_validation_debug": llm_debug,
        "semantic_contract_repairs": (
            completed_intent.get("semantic_contract", {}).get("corrections", [])
            if isinstance(completed_intent.get("semantic_contract"), dict)
            else []
        ),
        "semantic_contract_trace": (
            completed_intent.get("semantic_contract", {}).get("trace", {})
            if isinstance(completed_intent.get("semantic_contract"), dict)
            else {}
        ),
        "repaired_final_intent": completed_intent,
    }
    return rules_extracted, completed_intent, completed_type, debug


def run_intent_extraction_stage(
    query: str,
    schema: dict,
    route: str = "analytical",
    preprocess_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Stage runtime for:
    1) extracting structured intent
    2) validating against schema
    3) determining predictive vs analytical intent type
    """
    logger = _get_logger()
    config = IntentExtractionConfig.from_env()
    retry_count = 0
    attempts: list[dict[str, Any]] = []
    stage_started_at = _utc_now()
    stage_started_perf = time.perf_counter()
    llm_debug: dict[str, Any] = {}
    normalized_preprocess_hints = preprocess_hints if isinstance(preprocess_hints, dict) else {}

    normalized_route = str(route or "analytical").strip().lower() or "analytical"

    while True:
        try:
            attempt_started_perf = time.perf_counter()
            normalized_query, normalized_schema = _validate_inputs(query, schema)
            inferred_predictive_type = infer_intent_type(query=normalized_query, hinted_intent_type=None)
            predictive_route_required = (
                normalized_route == "forecasting"
                or inferred_predictive_type == "predictive"
            )
            if predictive_route_required:
                try:
                    predictive_intent = parse_predictive_intent(
                        query=normalized_query,
                        schema=normalized_schema,
                    )
                except PredictiveSchemaError as predictive_exc:
                    # Phase 5 / CRIT-14: predictive intents must run schema
                    # validation. When a date or target column is missing we
                    # surface a stable error code so the orchestrator can
                    # render a precise, user-facing rejection.
                    error_code = predictive_exc.code or FORECAST_MISSING_TIME_COLUMN
                    error_message = str(predictive_exc) or "Predictive intent failed schema validation."
                    attempts.append(
                        make_attempt(
                            attempt_number=len(attempts) + 1,
                            input_payload={
                                "query": normalized_query,
                                "schema_tables": list(normalized_schema.keys()),
                            },
                            output_payload={"error_code": error_code},
                            success=False,
                            retry_triggered=False,
                            model_or_method_used="predictive_intent_parser",
                            duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                            validation_result={"is_valid": False, "error_code": error_code},
                            error_type="business",
                            error_message=error_message,
                        )
                    )
                    finished_at = _utc_now()
                    return {
                        "status": "rejected",
                        "confidence": 0.0,
                        "intent_type": "predictive",
                        "next_step": "stop",
                        "error_type": "business",
                        "error_code": error_code,
                        "action_taken": "stop",
                        "query": normalized_query,
                        "schema": normalized_schema,
                        "extracted_intent": {},
                        "validated_intent": {},
                        "attempts": attempts,
                        "attempts_count": len(attempts),
                        "started_at": stage_started_at,
                        "finished_at": finished_at,
                        "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                        "warnings": [],
                        "errors": [
                            {"type": error_code, "message": error_message},
                        ],
                        "debug_metadata": {
                            "route": "forecasting",
                            "predictive_parser": "deterministic_schema_aware",
                            "error_code": error_code,
                        },
                    }

                # Phase 5 / CRIT-14: validate the predictive IR through
                # CanonicalIntent so forecast_date_column/forecast_target_column
                # are always present and well-typed before we leave this stage.
                canonical_intent, canonical_error = _validate_canonical_intent(
                    query=normalized_query,
                    intent=predictive_intent,
                    schema=normalized_schema,
                    confidence=0.9,
                )
                if canonical_intent is None or canonical_intent.forecast is None or not canonical_intent.forecast.date_column:
                    error_code = FORECAST_MISSING_TIME_COLUMN
                    error_message = (
                        "Forecasting requires a Date/DateTime column, but the canonical intent "
                        "validator could not bind one to the dataset."
                    )
                    attempts.append(
                        make_attempt(
                            attempt_number=len(attempts) + 1,
                            input_payload={
                                "query": normalized_query,
                                "schema_tables": list(normalized_schema.keys()),
                            },
                            output_payload={"canonical_error": canonical_error},
                            success=False,
                            retry_triggered=False,
                            model_or_method_used="canonical_intent_validator",
                            duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                            validation_result={"is_valid": False, "error_code": error_code},
                            error_type="business",
                            error_message=error_message,
                        )
                    )
                    finished_at = _utc_now()
                    return {
                        "status": "rejected",
                        "confidence": 0.0,
                        "intent_type": "predictive",
                        "next_step": "stop",
                        "error_type": "business",
                        "error_code": error_code,
                        "action_taken": "stop",
                        "query": normalized_query,
                        "schema": normalized_schema,
                        "extracted_intent": predictive_intent,
                        "validated_intent": predictive_intent,
                        "attempts": attempts,
                        "attempts_count": len(attempts),
                        "started_at": stage_started_at,
                        "finished_at": finished_at,
                        "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                        "warnings": [],
                        "errors": [{"type": error_code, "message": error_message}],
                        "debug_metadata": {
                            "route": "forecasting",
                            "canonical_intent_error": canonical_error,
                        },
                    }

                attempts.append(
                    make_attempt(
                        attempt_number=len(attempts) + 1,
                        input_payload={"query": normalized_query, "schema_tables": list(normalized_schema.keys())},
                        output_payload={
                            "extracted_intent": predictive_intent,
                            "validated_intent": predictive_intent,
                            "intent_type": "predictive",
                            "predictive_route_required": predictive_route_required,
                        },
                        success=True,
                        retry_triggered=False,
                        model_or_method_used="predictive_intent_parser",
                        duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                        validation_result={"is_valid": True},
                    )
                )
                finished_at = _utc_now()
                return {
                    "status": "success",
                    "confidence": 0.9,
                    "intent_type": "predictive",
                    "next_step": "forecasting",
                    "error_type": "none",
                    "action_taken": "proceed",
                    "query": normalized_query,
                    "schema": normalized_schema,
                    "extracted_intent": predictive_intent,
                    "validated_intent": predictive_intent,
                    "canonical_intent": canonical_intent.model_dump(mode="json"),
                    "forecast_date_column": canonical_intent.forecast.date_column,
                    "forecast_target_column": canonical_intent.forecast.target_column,
                    "attempts": attempts,
                    "attempts_count": len(attempts),
                    "started_at": stage_started_at,
                    "finished_at": finished_at,
                    "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                    "warnings": [],
                    "errors": [],
                    "debug_metadata": {
                        "route": "forecasting",
                        "route_source": (
                            "explicit_route"
                            if normalized_route == "forecasting"
                            else "predictive_inference_guard"
                        ),
                        "predictive_parser": "deterministic_schema_aware",
                        "canonical_intent_valid": True,
                    },
                }

            extracted_intent, validated_intent, detected_type, llm_debug = _rules_first_extract_and_validate(
                query=normalized_query,
                schema=normalized_schema,
                config=config,
                logger=logger,
                preprocess_hints=preprocess_hints,
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"query": normalized_query, "schema_tables": list(normalized_schema.keys())},
                    output_payload={
                        "extracted_intent": extracted_intent,
                        "validated_intent": validated_intent,
                        "intent_type": detected_type,
                    },
                    success=True,
                    retry_triggered=False,
                    model_or_method_used="rules_first_intent_extractor+llm_validation",
                    duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                    validation_result={"is_valid": True},
                )
            )
            llm_validation_error = str(llm_debug.get("llm_validation_error") or "").strip()

            def _intent_contract_complete(inv: dict[str, Any]) -> bool:
                if not isinstance(inv, dict):
                    return False
                metrics = inv.get("metrics") or []
                specs = inv.get("metric_specs") or []
                if isinstance(specs, list) and specs:
                    return True
                if not isinstance(metrics, list) or not metrics:
                    return False
                if inv.get("time_grouping_detected") or inv.get("group_by_time"):
                    for m in metrics:
                        if isinstance(m, dict) and not str(m.get("aggregation") or "").strip():
                            return False
                return True

            degraded = bool(llm_validation_error) and not _intent_contract_complete(validated_intent)
            finished_at = _utc_now()
            return {
                "status": "degraded" if degraded else "success",
                "degraded": degraded,
                "recovered": degraded,
                "recovery_reason": "intent_extraction_llm_fallback_repaired" if degraded else "",
                "degradation_reason": "intent_extraction_llm_fallback" if degraded else "",
                "confidence": 0.74 if degraded else 0.86,
                "intent_type": detected_type,
                "next_step": _next_step_for_intent_type(detected_type),
                "error_type": "none",
                "action_taken": "repair_and_proceed" if degraded else "proceed",
                "query": normalized_query,
                "schema": normalized_schema,
                "extracted_intent": extracted_intent,
                "validated_intent": validated_intent,
                "attempts": attempts,
                "attempts_count": len(attempts),
                "started_at": stage_started_at,
                "finished_at": finished_at,
                "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                "warnings": (
                    [
                        {
                            "type": "intent_extraction_llm_fallback",
                            "message": (
                                "LLM intent extraction/validation failed; used deterministic "
                                "rules-first intent and semantic repair."
                            ),
                        }
                    ]
                    if degraded
                    else []
                ),
                "errors": [],
                "debug_metadata": {
                    "llm_provider": config.llm_provider,
                    "route": normalized_route,
                    "preprocess_hints": normalized_preprocess_hints,
                    "llm_prompt": llm_debug.get("prompt"),
                    "llm_raw_output": llm_debug.get("raw_output"),
                    "llm_parsed_payload": llm_debug.get("parsed_payload"),
                    "rules_first": llm_debug.get("rules_first"),
                    "deterministic_intent": llm_debug.get("deterministic_intent"),
                    "llm_raw_intent": llm_debug.get("llm_raw_intent"),
                    "semantic_contract_repairs": llm_debug.get("semantic_contract_repairs"),
                    "semantic_contract_trace": llm_debug.get("semantic_contract_trace"),
                    "repaired_final_intent": llm_debug.get("repaired_final_intent"),
                    "chart_intent_fallback_applied": llm_debug.get("chart_intent_fallback_applied"),
                    "chart_intent_fallback_reason": llm_debug.get("chart_intent_fallback_reason"),
                    "chart_intent_selected_chart_type": llm_debug.get("chart_intent_selected_chart_type"),
                    "chart_intent_metric_type": llm_debug.get("chart_intent_metric_type"),
                    "llm_fallback_used": degraded,
                },
            }
        except Exception as exc:  # noqa: BLE001
            error_type = classify_intent_extraction_error(exc)
            action_taken = decide_intent_extraction_action(
                error_type=error_type,
                retry_count=retry_count,
                config=config,
            )
            normalized_query_for_fallback = str(query or "").strip()
            normalized_schema_for_fallback = schema if isinstance(schema, dict) else {}

            if (
                action_taken == "stop"
                and error_type in {"system", "model", "unknown"}
                and normalized_query_for_fallback
                and normalized_schema_for_fallback
            ):
                try:
                    attempt_started_perf = time.perf_counter()
                    extracted_intent, validated_intent, detected_type, llm_debug = _fallback_extract_and_validate(
                        query=normalized_query_for_fallback,
                        schema=normalized_schema_for_fallback,
                        logger=logger,
                        preprocess_hints=preprocess_hints,
                    )
                    attempts.append(
                        make_attempt(
                            attempt_number=len(attempts) + 1,
                            input_payload={
                                "query": normalized_query_for_fallback,
                                "schema_tables": list(normalized_schema_for_fallback.keys()),
                            },
                            output_payload={
                                "extracted_intent": extracted_intent,
                                "validated_intent": validated_intent,
                                "intent_type": detected_type,
                                "fallback_reason": str(exc),
                            },
                            success=True,
                            retry_triggered=False,
                            model_or_method_used="heuristic_query_planner_fallback",
                            duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                            validation_result={"is_valid": True, "fallback_used": True},
                        )
                    )
                    finished_at = _utc_now()
                    return {
                        "status": "degraded",
                        "degraded": True,
                        "recovered": True,
                        "recovery_reason": "intent_extraction_llm_fallback_repaired",
                        "degradation_reason": "intent_extraction_llm_fallback",
                        "confidence": 0.74,
                        "intent_type": detected_type,
                        "next_step": _next_step_for_intent_type(detected_type),
                        "error_type": "none",
                        "action_taken": "repair_and_proceed",
                        "query": normalized_query_for_fallback,
                        "schema": normalized_schema_for_fallback,
                        "extracted_intent": extracted_intent,
                        "validated_intent": validated_intent,
                        "attempts": attempts,
                        "attempts_count": len(attempts),
                        "started_at": stage_started_at,
                        "finished_at": finished_at,
                        "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                        "warnings": [
                            {
                                "type": "intent_extraction_llm_fallback",
                                "message": (
                                    "LLM intent extraction failed; used deterministic query-planner "
                                    "fallback to continue the analytical flow."
                                ),
                            }
                        ],
                        "errors": [],
                        "debug_metadata": {
                            "llm_provider": config.llm_provider,
                            "route": normalized_route,
                            "llm_prompt": llm_debug.get("prompt"),
                            "llm_raw_output": llm_debug.get("raw_output"),
                            "llm_parsed_payload": llm_debug.get("parsed_payload"),
                            "llm_fallback_used": True,
                            "llm_fallback_error_type": error_type,
                            "llm_fallback_error": str(exc),
                            "fallback_source": llm_debug.get("fallback_source"),
                            "chart_intent_fallback_applied": llm_debug.get("chart_intent_fallback_applied"),
                            "chart_intent_fallback_reason": llm_debug.get("chart_intent_fallback_reason"),
                            "chart_intent_selected_chart_type": llm_debug.get("chart_intent_selected_chart_type"),
                            "chart_intent_metric_type": llm_debug.get("chart_intent_metric_type"),
                        },
                    }
                except Exception as fallback_exc:  # noqa: BLE001
                    _log_event(
                        logger,
                        logging.ERROR,
                        "Intent extraction fallback failed",
                        original_error=str(exc),
                        fallback_error=str(fallback_exc),
                    )

            inferred_type = infer_intent_type(query=str(query or ""), hinted_intent_type=None)
            next_step = _next_step_for_intent_type(inferred_type)
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"query": str(query or "")},
                    output_payload={},
                    success=False,
                    retry_triggered=action_taken == "retry",
                    retry_reason=str(exc) if action_taken == "retry" else "",
                    model_or_method_used=f"{config.llm_provider}_intent_extractor",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type=error_type,
                    error_message=str(exc),
                )
            )

            _log_event(
                logger,
                logging.ERROR,
                "Intent extraction stage failed",
                input_query=str(query or ""),
                error_type=error_type,
                action_taken=action_taken,
                retry_count=retry_count,
                error=str(exc),
            )

            if action_taken == "retry":
                retry_count += 1
                continue

            failed_result: dict[str, Any] = build_intent_extraction_failed_result(
                intent_type=inferred_type,
                next_step=next_step,
                error_type=error_type,
                action_taken=action_taken,
            )
            failed_result["query"] = str(query or "")
            failed_result["schema"] = schema if isinstance(schema, dict) else {}
            failed_result["attempts"] = attempts
            failed_result["attempts_count"] = len(attempts)
            failed_result["started_at"] = stage_started_at
            failed_result["finished_at"] = _utc_now()
            failed_result["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            failed_result["warnings"] = []
            failed_result["errors"] = [{"type": error_type, "message": str(exc)}]
            failed_result["debug_metadata"] = {
                "llm_provider": config.llm_provider,
                "route": normalized_route,
                "llm_prompt": llm_debug.get("prompt"),
                "llm_raw_output": llm_debug.get("raw_output"),
            }
            failed_result["confidence"] = stage_confidence(failed_result, base_success=0.86, base_degraded=0.58)
            return failed_result


def run_intent_extraction(query: str, schema: dict) -> dict:
    """
    Full runtime for legacy contract:
    extraction -> validation -> SQL build -> ClickHouse execution -> downstream routing.
    """
    stage_result = run_intent_extraction_stage(query=query, schema=schema)
    if not stage_allows_progress(stage_result.get("status"), degraded=bool(stage_result.get("degraded"))):
        return stage_result

    logger = _get_logger()
    config = IntentExtractionConfig.from_env()
    retry_count = 0
    attempts: list[dict[str, Any]] = []
    stage_started_at = _utc_now()
    stage_started_perf = time.perf_counter()

    normalized_query = str(stage_result.get("query", "")).strip()
    normalized_schema = stage_result.get("schema", {}) or {}
    extracted_intent = stage_result.get("extracted_intent", {}) or {}
    validated_intent = stage_result.get("validated_intent", {}) or {}
    detected_type = str(stage_result.get("intent_type", "analytical") or "analytical")
    next_step = _next_step_for_intent_type(detected_type)

    while True:
        try:
            attempt_started_perf = time.perf_counter()
            # Phase 6 / CRIT-05: lift the per-workspace ClickHouse database
            # off the intent (if upstream populated it) and propagate it into
            # routing so the compiled SQL is always tenant-qualified.
            workspace_clickhouse_db = (
                str(validated_intent.get("workspace_clickhouse_db") or "").strip()
                or str(stage_result.get("workspace_clickhouse_db") or "").strip()
                or None
            )
            _stage_dbg = stage_result.get("debug_metadata", {}) if isinstance(stage_result.get("debug_metadata"), dict) else {}
            _route_preprocess_hints = _stage_dbg.get("preprocess_hints") if isinstance(_stage_dbg.get("preprocess_hints"), dict) else None
            routing_result = route_intent(
                query=normalized_query,
                intent=validated_intent,
                schema=normalized_schema,
                config=config,
                workspace_clickhouse_db=workspace_clickhouse_db,
                preprocess_hints=_route_preprocess_hints,
            )
            _log_event(
                logger,
                logging.INFO,
                "Routing decision completed",
                intent_type=detected_type,
                next_step=routing_result["next_step"],
                sql_query=routing_result["sql_query"],
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={
                        "query": normalized_query,
                        "intent_type": detected_type,
                        "validated_intent": validated_intent,
                    },
                    output_payload=routing_result,
                    success=True,
                    retry_triggered=False,
                    model_or_method_used="route_intent",
                    duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                    validation_result={"is_valid": True},
                )
            )

            result: IntentExtractionTaskResult = build_intent_extraction_success_result(
                intent_type=detected_type,  # type: ignore[arg-type]
                sql_query=routing_result["sql_query"],
                next_step=routing_result["next_step"],
                extracted_intent=extracted_intent,
                normalized_intent=routing_result["normalized_intent"],
                execution_result=routing_result.get("execution_result"),
                downstream_result=routing_result.get("downstream_result"),
            )
            result["attempts"] = attempts
            result["attempts_count"] = len(attempts)
            result["started_at"] = stage_started_at
            result["finished_at"] = _utc_now()
            result["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            result["warnings"] = []
            result["errors"] = []
            result["confidence"] = stage_confidence(stage_result, base_success=0.86, base_degraded=0.58)
            return result
        except Exception as exc:  # noqa: BLE001
            error_type = classify_intent_extraction_error(exc)
            action_taken = decide_intent_extraction_action(
                error_type=error_type,
                retry_count=retry_count,
                config=config,
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"query": normalized_query, "validated_intent": validated_intent},
                    output_payload={},
                    success=False,
                    retry_triggered=action_taken == "retry",
                    retry_reason=str(exc) if action_taken == "retry" else "",
                    model_or_method_used="route_intent",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type=error_type,
                    error_message=str(exc),
                )
            )

            _log_event(
                logger,
                logging.ERROR,
                "Intent routing/execution failed",
                input_query=normalized_query,
                error_type=error_type,
                action_taken=action_taken,
                retry_count=retry_count,
                error=str(exc),
            )

            if action_taken == "retry":
                retry_count += 1
                continue

            failed_payload = build_intent_extraction_failed_result(
                intent_type=detected_type,  # type: ignore[arg-type]
                next_step=next_step,
                error_type=error_type,
                action_taken=action_taken,
            )
            failed_payload["attempts"] = attempts
            failed_payload["attempts_count"] = len(attempts)
            failed_payload["started_at"] = stage_started_at
            failed_payload["finished_at"] = _utc_now()
            failed_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            failed_payload["warnings"] = []
            failed_payload["errors"] = [{"type": error_type, "message": str(exc)}]
            failed_payload["confidence"] = stage_confidence(failed_payload, base_success=0.86, base_degraded=0.58)
            return failed_payload


def _attach_fn_compat(func):
    """
    Keep compatibility for existing call sites/tests that use Prefect's `.fn`.
    """
    setattr(func, "fn", func)
    return func


@_attach_fn_compat
def intent_extraction_task(query: str, schema: dict) -> dict:
    return run_intent_extraction(query=query, schema=schema)

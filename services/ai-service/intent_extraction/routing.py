from __future__ import annotations

import re
from typing import Any

from intent_extraction.error_handler import (
    IntentExtractionSchemaMismatchError,
)
from intent_extraction.schemas import IntentExtractionConfig, StructuredIntent
from shared.pipeline_guards import is_technical_column_name
from shared.query_planner import normalize_analytical_intent
from shared.semantic_contract_validator import validate_semantic_contract
from shared.sql_compiler import (
    DEFAULT_CH_SETTINGS,
    _format_ch_settings,
    _resolve_workspace_db,
    compile_sql,
)
from shared.sql_review import validate_sql  # SQL safety is now centralised in sql_review (CRIT-04).


def _coerce_metrics_to_objects_for_sql_compiler(intent: dict[str, Any]) -> None:
    """``compile_sql`` requires ``metrics`` as list[dict]; validation may leave string columns."""

    metrics = intent.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        return
    if all(isinstance(m, dict) for m in metrics):
        return
    specs = intent.get("metric_specs") if isinstance(intent.get("metric_specs"), list) else []
    if specs and all(isinstance(s, dict) for s in specs):
        intent["metrics"] = [dict(s) for s in specs]
        return
    rebuilt: list[dict[str, Any]] = []
    for m in metrics:
        if isinstance(m, dict):
            rebuilt.append(dict(m))
        elif isinstance(m, str) and m.strip() and m != "*":
            col = m.strip()
            rebuilt.append({"column": col, "aggregation": "SUM", "alias": col})
    if rebuilt:
        intent["metrics"] = rebuilt


def _qualify_with_workspace_db(
    table_name: str,
    *,
    workspace_clickhouse_db: str | None,
) -> str:
    """Phase 6 / CRIT-05: qualify a bare table name with the workspace DB.

    The compiler does this for analytical SQL; this helper reuses the same
    resolution rules for the hand-written predictive SQL emitted in
    ``_build_historical_forecast_sql``.
    """

    cleaned = str(table_name or "").strip()
    if not cleaned:
        return cleaned
    if "." in cleaned:
        return cleaned
    workspace_db = _resolve_workspace_db(
        intent={},
        workspace_clickhouse_db=workspace_clickhouse_db,
    )
    return f"{workspace_db}.{cleaned}"


def _compile_ch_settings_comment() -> str:
    return _format_ch_settings(DEFAULT_CH_SETTINGS) or ""

_GRANULARITY_TO_CLICKHOUSE_EXPR = {
    "hour": "toStartOfHour({column})",
    "day": "toDate({column})",
    "week": "toStartOfWeek({column})",
    "month": "toStartOfMonth({column})",
    "year": "toStartOfYear({column})",
}


def _is_string_like_type(column_type: str) -> bool:
    lowered = str(column_type or "").strip().lower()
    return any(token in lowered for token in ("string", "fixedstring", "varchar", "char"))


def _normalize_clickhouse_date_casts(sql_expr: str) -> str:
    normalized = str(sql_expr or "").strip()
    if not normalized:
        return normalized
    previous = ""
    while normalized != previous:
        previous = normalized
        normalized = re.sub(
            r"toDate\(\s*toDate\(\s*([^)]+?)\s*\)\s*\)",
            r"toDate(\1)",
            normalized,
            flags=re.IGNORECASE,
        )
    return normalized


def _build_predictive_time_expr(
    *,
    granularity: str,
    column_name: str,
    column_type: str,
) -> str:
    template = _GRANULARITY_TO_CLICKHOUSE_EXPR.get(granularity, "toDate({column})")
    if granularity == "day" and ("date" in column_type and "datetime" not in column_type and "timestamp" not in column_type):
        return column_name
    if _is_string_like_type(column_type):
        parsed_expr = _string_time_parse_expr(column_name)
        if granularity == "day":
            return f"toDate({parsed_expr})"
        base_column = parsed_expr
    else:
        base_column = column_name
    expr = template.format(column=base_column)
    return _normalize_clickhouse_date_casts(expr)


def _string_time_parse_expr(column_name: str) -> str:
    return (
        f"coalesce("
        f"parseDateTimeBestEffortUSOrNull({column_name}), "
        f"parseDateTimeBestEffortOrNull({column_name})"
        f")"
    )


def _build_query_builder_payload(intent: StructuredIntent) -> dict[str, Any]:
    order_by = intent.get("order_by", []) or []
    limit = intent.get("limit")
    metric_specs_payload: list[dict[str, Any]] = []

    for metric_spec in intent.get("metric_specs", []) or []:
        if not isinstance(metric_spec, dict):
            continue
        column = str(metric_spec.get("column", "")).strip()
        if not column:
            continue
        metric_agg = str(metric_spec.get("aggregation", "")).strip().upper() or None
        metric_alias = str(metric_spec.get("alias", "")).strip() or None
        metric_specs_payload.append(
            {
                "column": column,
                "aggregation": metric_agg,
                "alias": metric_alias,
            }
        )

    metrics_payload = [
        str(metric_column).strip()
        for metric_column in (intent.get("metrics", []) or [])
        if str(metric_column).strip()
    ]

    if not metrics_payload and not metric_specs_payload:
        target_column = str(intent.get("target_column", "*") or "*").strip() or "*"
        metrics_payload = [target_column]

    chart_payload = intent.get("chart") if isinstance(intent.get("chart"), dict) else {}
    selected_chart_type = (
        str(intent.get("selected_chart_type", "")).strip().lower()
        or str(intent.get("chart_type", "")).strip().lower()
        or str(chart_payload.get("type", "")).strip().lower()
    )
    metric_type = (
        str(intent.get("metric_type", "")).strip().lower()
        or str(chart_payload.get("metric_type", "")).strip().lower()
    )
    if metric_type == "percentage" and not selected_chart_type:
        selected_chart_type = "pie"
    normalized_chart_payload = {
        **chart_payload,
        "type": selected_chart_type or chart_payload.get("type"),
        "metric_type": metric_type or chart_payload.get("metric_type"),
        "group_by": chart_payload.get("group_by"),
    }

    return {
        "table": intent["table"],
        "intent": str(intent.get("intent", "analytical") or "analytical"),
        "operations": intent.get("operations", []),
        "metric_specs": metric_specs_payload,
        "metrics": metrics_payload,
        "dimensions": intent.get("dimensions", []),
        "filters": intent.get("filters", []),
        "order_by": order_by,
        "limit": limit,
        "ranking": intent.get("ranking", {}),
        "ambiguities": intent.get("ambiguities", []),
        "chart": normalized_chart_payload,
        "metric_type": metric_type,
        "selected_chart_type": selected_chart_type,
        "chart_type": selected_chart_type,
    }


def _is_schema_mismatch_message(message: str) -> bool:
    lowered = message.lower()
    return (
        "table" in lowered
        or "column" in lowered
        or "schema" in lowered
        or "does not exist" in lowered
        or "ambiguous table name" in lowered
        or "no numeric columns" in lowered
    )


def build_sql_from_intent(
    *,
    query: str,
    intent: StructuredIntent,
    schema: dict[str, list[dict[str, Any]]],
    workspace_clickhouse_db: str | None = None,
    preprocess_hints: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    predictive_requested = bool(
        str(intent.get("intent_type", "")).strip().lower() == "predictive"
        or intent.get("requires_forecast")
        or str(intent.get("question_type", "")).strip().lower() in {"predictive", "forecast", "forecasting"}
    )
    if predictive_requested:
        intent["intent_type"] = "predictive"
        intent["requires_forecast"] = True
        return _build_historical_forecast_sql(
            intent=intent,
            schema=schema,
            workspace_clickhouse_db=workspace_clickhouse_db,
        )

    query_builder_payload = _build_query_builder_payload(intent)
    preprocessing_hints = {
        "selected_table": str(intent.get("table", "")).strip(),
        "selected_columns": sorted(
            {
                str(metric.get("column", "")).strip()
                for metric in (intent.get("metric_specs", []) if isinstance(intent.get("metric_specs"), list) else [])
                if isinstance(metric, dict) and str(metric.get("column", "")).strip()
            }
            | {
                str(metric).strip()
                for metric in (intent.get("metrics", []) if isinstance(intent.get("metrics"), list) else [])
                if isinstance(metric, str) and str(metric).strip()
            }
            | {
                str(dimension).strip()
                for dimension in (intent.get("dimensions", []) if isinstance(intent.get("dimensions"), list) else [])
                if str(dimension).strip()
            }
            | (
                {str(intent.get("time_column")).strip()}
                if str(intent.get("time_column", "")).strip()
                else set()
            )
        ),
    }
    if isinstance(preprocess_hints, dict):
        preprocessing_hints = {**preprocessing_hints, **preprocess_hints}

    try:
        normalized_intent = normalize_analytical_intent(
            question=query,
            raw_intent=query_builder_payload,
            schema=schema,
        )
        normalized_intent = validate_semantic_contract(
            question=query,
            intent=normalized_intent,
            schema=schema,
            preprocess_hints=preprocessing_hints,
        )
        if normalized_intent.get("time_grouping_detected") and normalized_intent.get("intent") == "time_series":
            time_alias = str(normalized_intent.get("time_dimension_alias") or "date").strip() or "date"
            normalized_intent["order_by"] = [{"column": time_alias, "direction": "ASC"}]
            ranking = normalized_intent.get("ranking") if isinstance(normalized_intent.get("ranking"), dict) else {}
            normalized_intent["ranking"] = {**ranking, "direction": None, "requested": False, "source": "time_series_order"}
        if isinstance(normalized_intent, dict):
            # Prefer semantic-contract / planner output over stale upstream intent so
            # time-series and multi-metric chart choices are not overwritten here.
            selected_chart_type = (
                str(normalized_intent.get("selected_chart_type", "")).strip().lower()
                or str(normalized_intent.get("chart_type", "")).strip().lower()
                or str((normalized_intent.get("chart") or {}).get("type") if isinstance(normalized_intent.get("chart"), dict) else "").strip().lower()
                or str(intent.get("selected_chart_type", "")).strip().lower()
                or str(intent.get("chart_type", "")).strip().lower()
                or str((intent.get("chart") or {}).get("type") if isinstance(intent.get("chart"), dict) else "").strip().lower()
            )
            metric_type = (
                str(normalized_intent.get("metric_type", "")).strip().lower()
                or str((normalized_intent.get("chart") or {}).get("metric_type") if isinstance(normalized_intent.get("chart"), dict) else "").strip().lower()
                or str(intent.get("metric_type", "")).strip().lower()
                or str((intent.get("chart") or {}).get("metric_type") if isinstance(intent.get("chart"), dict) else "").strip().lower()
            )
            if metric_type == "percentage" and not selected_chart_type:
                selected_chart_type = "pie"
            upstream_chart = normalized_intent.get("chart", {}) if isinstance(normalized_intent.get("chart"), dict) else {}
            legacy_chart = intent.get("chart", {}) if isinstance(intent.get("chart"), dict) else {}
            normalized_intent["chart"] = {
                **legacy_chart,
                **upstream_chart,
                "type": selected_chart_type or upstream_chart.get("type") or legacy_chart.get("type"),
                "metric_type": metric_type or upstream_chart.get("metric_type") or legacy_chart.get("metric_type"),
                "group_by": upstream_chart.get("group_by") or legacy_chart.get("group_by"),
            }
            normalized_intent["metric_type"] = metric_type
            normalized_intent["selected_chart_type"] = selected_chart_type
            normalized_intent["chart_type"] = selected_chart_type
        # Phase 6 / CRIT-05: propagate the per-tenant ClickHouse database so
        # the compiler emits ``<workspace_db>.<table>`` instead of the legacy
        # ``etl.<table>`` default.
        _coerce_metrics_to_objects_for_sql_compiler(normalized_intent)
        sql_query = compile_sql(
            normalized_intent,
            schema=schema,
            workspace_clickhouse_db=workspace_clickhouse_db,
        )
        validate_sql(sql_query)
        normalized_intent = validate_semantic_contract(
            question=query,
            intent=normalized_intent,
            schema=schema,
            sql=sql_query,
            chart_type=str(normalized_intent.get("selected_chart_type", "")),
            preprocess_hints=preprocessing_hints,
        )
        if normalized_intent.get("semantic_contract_errors"):
            raise ValueError("; ".join(normalized_intent["semantic_contract_errors"]))
    except ValueError as exc:
        if _is_schema_mismatch_message(str(exc)):
            raise IntentExtractionSchemaMismatchError(str(exc)) from exc
        raise

    return normalized_intent, sql_query


def _resolve_schema_table(schema: dict[str, list[dict[str, Any]]], requested_table: str) -> str:
    requested = str(requested_table or "").strip()
    if requested in schema:
        return requested
    if requested:
        requested_unqualified = requested.split(".")[-1].lower()
        matches = [
            table_name
            for table_name in schema.keys()
            if table_name.split(".")[-1].lower() == requested_unqualified
        ]
        if len(matches) == 1:
            return matches[0]
    if not schema:
        raise IntentExtractionSchemaMismatchError("Schema is empty.")
    return sorted(schema.keys())[0]


def _resolve_schema_table_for_predictive(
    *,
    schema: dict[str, list[dict[str, Any]]],
    requested_table: str,
    requested_metric: str,
    requested_time_column: str,
) -> str:
    resolved = _resolve_schema_table(schema, requested_table)
    if requested_table and resolved:
        return resolved
    metric_hint = str(requested_metric or "").strip().lower()
    time_hint = str(requested_time_column or "").strip().lower()
    if not metric_hint and not time_hint:
        return resolved
    scored: list[tuple[int, str]] = []
    for table_name, cols in schema.items():
        col_names = [str(c.get("name", "")).strip().lower() for c in (cols or []) if isinstance(c, dict)]
        score = 0
        if metric_hint and metric_hint in col_names:
            score += 3
        if time_hint and time_hint in col_names:
            score += 3
        if not time_hint and any(t in col_names for t in ("ds", "date", "datetime", "timestamp", "time")):
            score += 2
        if not metric_hint and any(
            any(token in name for token in ("sales", "revenue", "amount", "total", "count", "orders", "value"))
            for name in col_names
        ):
            score += 1
        scored.append((score, table_name))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if scored and scored[0][0] > 0:
        return scored[0][1]
    return resolved


def _resolve_schema_column(
    *,
    table_columns: list[dict[str, Any]],
    requested_column: str,
) -> str:
    requested = str(requested_column or "").strip()
    if not requested:
        return ""
    exact = [
        str(column.get("name", "")).strip()
        for column in table_columns
        if str(column.get("name", "")).strip().lower() == requested.lower()
    ]
    if exact:
        return exact[0]
    normalized_requested = requested.lower().replace(" ", "_")
    normalized = [
        str(column.get("name", "")).strip()
        for column in table_columns
        if str(column.get("name", "")).strip().lower() == normalized_requested
    ]
    if normalized:
        return normalized[0]
    return ""


def _build_historical_forecast_sql(
    *,
    intent: StructuredIntent,
    schema: dict[str, list[dict[str, Any]]],
    workspace_clickhouse_db: str | None = None,
) -> tuple[dict[str, Any], str]:
    resolved_table = _resolve_schema_table_for_predictive(
        schema=schema,
        requested_table=str(intent.get("table", "")).strip(),
        requested_metric=str(intent.get("metric", "")).strip() or str(intent.get("target_column", "")).strip(),
        requested_time_column=str(intent.get("time_column", "")).strip(),
    )
    table_columns = schema.get(resolved_table, [])
    if not table_columns:
        raise IntentExtractionSchemaMismatchError(f"Table '{resolved_table}' not found in schema.")

    metric = (
        str(intent.get("metric", "")).strip()
        or str(intent.get("target_column", "")).strip()
        or (str((intent.get("metrics") or [""])[0]).strip() if isinstance(intent.get("metrics"), list) else "")
    )
    time_column = (
        str(intent.get("time_column", "")).strip()
        or (str((intent.get("dimensions") or [""])[0]).strip() if isinstance(intent.get("dimensions"), list) else "")
    )

    resolved_metric = _resolve_schema_column(table_columns=table_columns, requested_column=metric)
    resolved_time_column = _resolve_schema_column(table_columns=table_columns, requested_column=time_column)
    if not resolved_metric:
        raise IntentExtractionSchemaMismatchError(
            f"Predictive metric column '{metric}' was not found in table '{resolved_table}'."
        )
    if not resolved_time_column:
        raise IntentExtractionSchemaMismatchError(
            f"Predictive time column '{time_column}' was not found in table '{resolved_table}'."
        )
    if is_technical_column_name(resolved_time_column):
        raise IntentExtractionSchemaMismatchError(
            f"Predictive time column '{resolved_time_column}' is technical metadata and cannot be used."
        )

    granularity = str(intent.get("granularity", "day") or "day").strip().lower() or "day"
    resolved_time_type = ""
    for column in table_columns:
        if str(column.get("name", "")).strip().lower() == resolved_time_column.lower():
            resolved_time_type = str(column.get("type", "")).strip().lower()
            break
    if granularity == "day" and resolved_time_column.lower() in {"ds", "date"} and not _is_string_like_type(resolved_time_type):
        time_expr = resolved_time_column
    else:
        time_expr = _build_predictive_time_expr(
            granularity=granularity,
            column_name=resolved_time_column,
            column_type=resolved_time_type,
        )
    value_expr = f"sum(toFloat64({resolved_metric}))"

    # Phase 6 / CRIT-05: forecast SQL must also be per-tenant qualified.
    qualified_table = _qualify_with_workspace_db(
        resolved_table,
        workspace_clickhouse_db=workspace_clickhouse_db,
    )

    sql_query = (
        f"{_compile_ch_settings_comment()}\n"
        f"SELECT {time_expr} AS ds, {value_expr} AS value "
        f"FROM {qualified_table} "
        f"WHERE {resolved_time_column} IS NOT NULL AND {resolved_metric} IS NOT NULL "
        "GROUP BY ds "
        "ORDER BY ds ASC"
    )
    validate_sql(sql_query)

    normalized_intent = {
        "intent_type": "predictive",
        "table": resolved_table,
        "intent": "forecast",
        "operations": ["projection", "forecasting"],
        "metrics": [{"column": resolved_metric, "aggregation": "SUM", "alias": "value"}],
        "dimensions": [resolved_time_column],
        "filters": [],
        "aggregation": "SUM",
        "ranking": {"direction": "ASC", "requested": True, "source": "predictive_sql_builder"},
        "order_by": [{"column": "ds", "direction": "ASC"}],
        "limit": None,
        "ambiguities": [],
        "metric": resolved_metric,
        "time_column": resolved_time_column,
        "forecast_horizon": intent.get("forecast_horizon", intent.get("horizon", 7)),
        "granularity": granularity,
        "requires_forecast": True,
        "question_type": "predictive",
        "time_column_expression": time_expr,
    }
    return normalized_intent, sql_query


def route_intent(
    *,
    query: str,
    intent: StructuredIntent,
    schema: dict[str, list[dict[str, Any]]],
    config: IntentExtractionConfig,
    workspace_clickhouse_db: str | None = None,
    preprocess_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build SQL for a validated intent and wrap it in the routing payload.

    Phase 6 / CRIT-05: ``workspace_clickhouse_db`` is propagated all the way
    down to ``compile_sql`` / ``_build_historical_forecast_sql`` so the
    emitted SQL is per-tenant qualified.
    """

    # Allow the caller to embed the DB on the intent itself; this is the
    # path taken by the orchestrator after preprocessing-high resolves the
    # workspace context.
    if not workspace_clickhouse_db and isinstance(intent, dict):
        embedded = intent.get("workspace_clickhouse_db")
        if isinstance(embedded, str) and embedded.strip():
            workspace_clickhouse_db = embedded.strip()
    normalized_intent, sql_query = build_sql_from_intent(
        query=query,
        intent=intent,
        schema=schema,
        workspace_clickhouse_db=workspace_clickhouse_db,
        preprocess_hints=preprocess_hints,
    )
    next_step = "forecasting" if str(normalized_intent.get("intent_type", "")).strip().lower() == "predictive" else "metabase"
    return {
        "sql_query": sql_query,
        "next_step": next_step,
        "normalized_intent": normalized_intent,
        "execution_result": None,
        "downstream_result": None,
        "execution_delegated": "query-service",
        "downstream_delegated": "voice-service",
    }

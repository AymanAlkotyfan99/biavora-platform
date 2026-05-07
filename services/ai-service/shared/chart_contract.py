from __future__ import annotations

import re
from typing import Any, Dict, List

try:
    from shared.chart_types import ChartType, normalize_chart_type
except Exception:  # pragma: no cover
    class ChartType:
        LINE = type("C", (), {"value": "line"})()
        LINE_MULTI = type("C", (), {"value": "line_multi"})()
        BAR = type("C", (), {"value": "bar"})()
        BAR_GROUPED = type("C", (), {"value": "bar_grouped"})()
        BAR_STACKED = type("C", (), {"value": "bar_stacked"})()
        AREA = type("C", (), {"value": "area"})()
        PIE = type("C", (), {"value": "pie"})()
        SCATTER = type("C", (), {"value": "scatter"})()
        HISTOGRAM = type("C", (), {"value": "histogram"})()
        MAP = type("C", (), {"value": "map"})()
        COMBO_LINE_BAR = type("C", (), {"value": "combo_line_bar"})()
        CARD = type("C", (), {"value": "card"})()
        TABLE = type("C", (), {"value": "table"})()

    def normalize_chart_type(raw_chart_type, *, default="table"):
        if not raw_chart_type:
            return default
        return str(raw_chart_type).strip().lower() or default


_EXPLICIT_CHART_HINTS: tuple[tuple[str, str], ...] = (
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
    ("card", "card"),
    ("kpi", "card"),
    ("table", "table"),
)


def _list_of_strings(value: Any) -> List[str]:
    if isinstance(value, list):
        cleaned: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = str(item.get("column") or item.get("alias") or "").strip()
            else:
                name = str(item or "").strip()
            if name and name not in cleaned:
                cleaned.append(name)
        return cleaned
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _first_non_blank(*values: Any) -> str:
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return ""


def _explicit_chart_from_text(query_text: str) -> str:
    lowered = f" {str(query_text or '').strip().lower()} "
    for token, chart in sorted(_EXPLICIT_CHART_HINTS, key=lambda pair: -len(pair[0])):
        if token in lowered:
            return chart
    return ""


def _metric_aliases(intent_payload: Dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for spec in (intent_payload.get("metric_specs") if isinstance(intent_payload.get("metric_specs"), list) else []):
        if not isinstance(spec, dict):
            continue
        alias = str(spec.get("alias") or "").strip()
        column = str(spec.get("column") or "").strip()
        preferred = alias or column
        if preferred and preferred not in aliases:
            aliases.append(preferred)
    for metric in _list_of_strings(intent_payload.get("metrics")):
        if metric and metric not in aliases:
            aliases.append(metric)
    return aliases


def _prefer_value_metric(metric_aliases: list[str], metric_type: str) -> str | None:
    if not metric_aliases:
        return None
    if str(metric_type or "").strip().lower() == "percentage":
        for candidate in metric_aliases:
            if "percent" in candidate.lower() or "share" in candidate.lower() or "ratio" in candidate.lower():
                return candidate
    return metric_aliases[0]


def _dedupe_non_blank(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def build_chart_contract_from_intent(
    intent: Dict[str, Any] | None,
    schema: Dict[str, Any] | None = None,
    result_shape: Dict[str, Any] | None = None,
    user_text: str | None = None,
    visualization: Dict[str, Any] | None = None,
    final_route: str | None = None,
) -> Dict[str, Any]:
    _ = schema
    intent_payload = intent if isinstance(intent, dict) else {}
    visualization_payload = visualization if isinstance(visualization, dict) else {}
    query_text = str(user_text or intent_payload.get("query") or "").strip().lower()
    route = str(final_route or "").strip().lower()

    base_from_intent = normalize_chart_type(
        intent_payload.get("chart_type")
        or intent_payload.get("selected_chart_type")
        or intent_payload.get("final_chart_type")
        or ((intent_payload.get("chart") or {}).get("type") if isinstance(intent_payload.get("chart"), dict) else "")
        or visualization_payload.get("selected_chart_type"),
        default=ChartType.TABLE.value,
    )
    selected = base_from_intent
    explicit_chart = _explicit_chart_from_text(query_text)
    explicit = bool(explicit_chart)
    chart_lock_requested = bool(
        intent_payload.get("chart_lock")
        or intent_payload.get("explicit_chart_lock")
        or intent_payload.get("locked")
    )
    forecast = bool(intent_payload.get("requires_forecast") or route == "forecasting")

    metric_aliases = _metric_aliases(intent_payload)
    dimensions = _list_of_strings(intent_payload.get("dimensions"))
    time_column = _first_non_blank(intent_payload.get("time_column"), (intent_payload.get("chart") or {}).get("time_column"))
    time_grain = _first_non_blank(intent_payload.get("time_granularity"), intent_payload.get("time_grain"))
    is_time_series_pre = bool(
        intent_payload.get("is_time_series")
        or intent_payload.get("time_grouping_detected")
        or intent_payload.get("group_by_time")
        or str(time_grain or "").strip().lower() in {"hour", "day", "week", "month", "quarter", "year"}
    )
    time_alias = _first_non_blank(
        intent_payload.get("time_dimension_alias"),
        "date" if (is_time_series_pre or time_column or time_grain) else "",
    )

    upstream_x = _first_non_blank(
        visualization_payload.get("x_axis"),
        intent_payload.get("x_axis"),
        (intent_payload.get("chart") or {}).get("x_axis") if isinstance(intent_payload.get("chart"), dict) else "",
    )
    upstream_y = _list_of_strings(
        visualization_payload.get("y_axis")
        or intent_payload.get("y_axis")
        or ((intent_payload.get("chart") or {}).get("y_axis") if isinstance(intent_payload.get("chart"), dict) else [])
    )

    is_time_series = bool(is_time_series_pre)
    metric_type = _first_non_blank(
        intent_payload.get("metric_type"),
        (intent_payload.get("chart") or {}).get("metric_type") if isinstance(intent_payload.get("chart"), dict) else "",
    ).lower()

    if explicit_chart:
        selected = explicit_chart

    if is_time_series and selected == ChartType.SCATTER.value and not chart_lock_requested:
        selected = ChartType.LINE_MULTI.value if len(metric_aliases) > 1 else ChartType.LINE.value
        explicit = False

    if len(metric_aliases) > 1 and selected in {ChartType.PIE.value, ChartType.CARD.value} and not chart_lock_requested:
        selected = ChartType.LINE_MULTI.value if is_time_series else normalize_chart_type("bar_grouped", default=ChartType.BAR.value)
        explicit = False

    if forecast:
        selected = ChartType.LINE.value
        reason = "forecast_requires_time_series_line"
        reason_code = "forecast_line"
    elif explicit:
        reason = "explicit_user_request"
        reason_code = "explicit_chart"
    elif selected == ChartType.LINE_MULTI.value:
        reason = "multi_metric_time_series"
        reason_code = "semantic_multi_metric_time_series"
    elif selected == ChartType.LINE.value:
        reason = "time_series"
        reason_code = "semantic_time_series"
    elif selected == ChartType.PIE.value:
        reason = "percentage_distribution"
        reason_code = "semantic_percentage_distribution"
    elif selected == ChartType.SCATTER.value:
        reason = "numeric_relationship"
        reason_code = "semantic_numeric_relationship"
    elif selected == ChartType.CARD.value:
        reason = "single_value_kpi"
        reason_code = "semantic_single_value"
    elif selected == ChartType.TABLE.value:
        reason = "safe_fallback"
        reason_code = "safe_fallback"
    else:
        reason = "category_metric_comparison"
        reason_code = "semantic_category_metric"

    # Semantic fallback when upstream chart type is too generic.
    if selected in {ChartType.TABLE.value, ChartType.CARD.value}:
        if is_time_series and len(metric_aliases) > 1:
            selected = ChartType.LINE_MULTI.value
            reason = "multi_metric_time_series"
            reason_code = "semantic_multi_metric_time_series"
        elif is_time_series and metric_aliases:
            selected = ChartType.LINE.value
            reason = "time_series"
            reason_code = "semantic_time_series"

    if selected == ChartType.SCATTER.value:
        if len(metric_aliases) >= 2:
            x_axis = upstream_x or metric_aliases[0]
            y_axis = upstream_y or [metric_aliases[1]]
        elif len(metric_aliases) == 1:
            x_axis = upstream_x or metric_aliases[0]
            y_axis = upstream_y or [metric_aliases[0]]
        else:
            x_axis = upstream_x or (dimensions[0] if dimensions else "")
            y_axis = upstream_y or ([dimensions[1]] if len(dimensions) > 1 else ([dimensions[0]] if dimensions else []))
    elif selected == ChartType.LINE_MULTI.value:
        x_axis = upstream_x or time_alias or (dimensions[0] if dimensions else "")
        y_axis = upstream_y or metric_aliases
    elif selected == ChartType.LINE.value:
        x_axis = upstream_x or time_alias or (dimensions[0] if dimensions else "")
        preferred = _prefer_value_metric(metric_aliases, metric_type)
        y_axis = upstream_y or ([preferred] if preferred else [])
    elif selected == ChartType.BAR.value:
        x_axis = upstream_x or (dimensions[0] if dimensions else time_alias)
        preferred = _prefer_value_metric(metric_aliases, metric_type)
        y_axis = upstream_y or ([preferred] if preferred else [])
    elif selected in {ChartType.BAR_GROUPED.value, ChartType.BAR_STACKED.value}:
        x_axis = upstream_x or (dimensions[0] if dimensions else time_alias)
        y_axis = upstream_y or metric_aliases
    elif selected == ChartType.AREA.value:
        x_axis = upstream_x or time_alias or (dimensions[0] if dimensions else "")
        y_axis = upstream_y or metric_aliases
    elif selected == ChartType.MAP.value:
        x_axis = upstream_x or (dimensions[0] if dimensions else "")
        y_axis = upstream_y or metric_aliases
    elif selected == ChartType.COMBO_LINE_BAR.value:
        x_axis = upstream_x or time_alias or (dimensions[0] if dimensions else "")
        y_axis = upstream_y or metric_aliases
    elif selected == ChartType.PIE.value:
        x_axis = upstream_x or (dimensions[0] if dimensions else (time_alias or "period"))
        preferred = _prefer_value_metric(metric_aliases, metric_type)
        y_axis = upstream_y or ([preferred] if preferred else [])
    elif selected == ChartType.HISTOGRAM.value:
        x_axis = upstream_x or _prefer_value_metric(metric_aliases, metric_type) or (metric_aliases[0] if metric_aliases else "")
        y_axis = upstream_y or (["frequency"] if x_axis else [])
    elif selected == ChartType.CARD.value:
        x_axis = None
        preferred = _prefer_value_metric(metric_aliases, metric_type)
        y_axis = upstream_y or ([preferred] if preferred else [])
    else:
        x_axis = upstream_x or (dimensions[0] if dimensions else None)
        y_axis = upstream_y or metric_aliases

    label_column = None
    value_column = None
    if selected == ChartType.PIE.value:
        label_column = str(x_axis or "").strip() or (dimensions[0] if dimensions else None)
        value_column = (y_axis[0] if y_axis else None) or _prefer_value_metric(metric_aliases, metric_type)
        if value_column and not y_axis:
            y_axis = [value_column]

    sel_conf = intent_payload.get("chart_selection_confidence")
    confidence = sel_conf if isinstance(sel_conf, (int, float)) else visualization_payload.get("chart_selector_confidence")
    if not isinstance(confidence, (int, float)):
        confidence = 0.9 if explicit else 0.8

    locked = bool(
        chart_lock_requested
        or visualization_payload.get("locked", visualization_payload.get("explicit_chart_lock", True))
    )
    if explicit or forecast:
        locked = True

    result_columns = []
    if isinstance(result_shape, dict) and isinstance(result_shape.get("columns"), list):
        result_columns = [str(c).strip() for c in result_shape.get("columns", []) if str(c or "").strip()]
    if result_columns:
        if not dimensions:
            dimensions = [c for c in result_columns if c not in metric_aliases]
        metric_aliases = _dedupe_non_blank(metric_aliases + [c for c in result_columns if c not in dimensions])

    metabase_display = (
        "scatter"
        if selected == ChartType.SCATTER.value
        else "line"
        if selected in {ChartType.LINE.value, ChartType.LINE_MULTI.value, ChartType.AREA.value}
        else "bar"
        if selected in {ChartType.BAR.value, ChartType.BAR_GROUPED.value, ChartType.BAR_STACKED.value, ChartType.HISTOGRAM.value}
        else "pie"
        if selected == ChartType.PIE.value
        else "table"
    )

    contract = {
        "type": selected,
        "chart_type": selected,
        "final_chart_type": selected,
        "semantic_chart_type": selected,
        "renderer_chart_type": metabase_display,
        "x_axis": x_axis,
        "y_axis": y_axis or [],
        "metrics": list(y_axis or []),
        "dimensions": [str(x_axis).strip()] if str(x_axis or "").strip() else [],
        "result_columns": result_columns,
        "metabase_display": metabase_display,
        "intent": str(intent_payload.get("intent") or "").strip() or None,
        "is_time_series": is_time_series,
        "confidence": float(confidence),
        "source": "ai_service.finalized_contract",
        "series": intent_payload.get("series"),
        "label_column": label_column,
        "value_column": value_column,
        "metric_type": metric_type or None,
        "time_column": time_column or None,
        "time_grain": time_grain or None,
        "locked": locked,
        "reason": reason,
        "fallback_allowed": not locked,
        "selected_chart_type": selected,
        "explicit_chart_lock": locked,
        "chart_lock": locked,
        "chart_reason": reason,
        "chart_reason_code": reason_code,
        "chart_confidence": float(confidence),
        "chart_source": "ai-service",
        "chart_selection_source": "deterministic_policy",
        "requested_chart": explicit_chart or base_from_intent or selected,
        "intent_chart": base_from_intent or selected,
        "recommended_chart": selected,
        "final_chart": selected,
        "fallback_applied": False,
        "fallback_reason": "",
        "overwritten_by": "",
        "shape_validation_result": "not_validated_in_ai_service",
        "aggregation": [
            str(spec.get("aggregation") or "").strip().upper()
            for spec in (intent_payload.get("metric_specs") if isinstance(intent_payload.get("metric_specs"), list) else [])
            if isinstance(spec, dict) and str(spec.get("aggregation") or "").strip()
        ],
        "dataset": {
            "table": str(intent_payload.get("table") or "").strip() or None,
            "workspace_id": str(intent_payload.get("workspace_id") or "").strip() or None,
        },
        "metadata": {
            "upstream_chart": base_from_intent,
            "final_chart": selected,
            "overridden_by": None,
            "fallback_reason": None,
        },
    }

    if selected == ChartType.SCATTER.value:
        contract["x_axis_type"] = "numeric"
        contract["y_axis_type"] = "numeric"
    if selected == ChartType.HISTOGRAM.value and not contract.get("x_axis"):
        candidate = _prefer_value_metric(metric_aliases, metric_type) or (metric_aliases[0] if metric_aliases else "")
        if candidate:
            contract["x_axis"] = candidate
            contract["dimensions"] = [candidate]
    if selected == ChartType.HISTOGRAM.value:
        # Renderer will use SQL binning fallback if native histogram display is not reliable.
        contract["y_axis"] = ["frequency"]
        contract["metrics"] = ["frequency"]
        contract["bucket_column"] = "bucket"
        contract["frequency_column"] = "frequency"
        contract["histogram_strategy"] = "sql_binning"
    if selected == ChartType.PIE.value:
        if not contract.get("label_column"):
            contract["label_column"] = (dimensions[0] if dimensions else (result_columns[0] if result_columns else None))
        if not contract.get("value_column"):
            contract["value_column"] = _prefer_value_metric(metric_aliases, metric_type)
        if contract.get("label_column") and not contract.get("x_axis"):
            contract["x_axis"] = contract["label_column"]
        if contract.get("value_column") and not contract.get("y_axis"):
            contract["y_axis"] = [contract["value_column"]]
            contract["metrics"] = [contract["value_column"]]

    # Metabase-ready visualization settings (strict, renderer-only).
    # visualization-service must render exactly this config (no inference, no fallback).
    metrics_out = [m for m in (contract.get("metrics") or []) if isinstance(m, str) and m.strip()]
    dims_out = [d for d in (contract.get("dimensions") or []) if isinstance(d, str) and d.strip()]
    graph_type = metabase_display
    visualization_settings: Dict[str, Any] = {
        "graph": {
            "type": graph_type,
            "dimensions": dims_out,
            "metrics": metrics_out,
        },
        "series_settings": {
            metric: {"display": "line" if graph_type == "line" else graph_type}
            for metric in metrics_out
        },
    }
    contract["visualization_settings"] = visualization_settings

    return contract


def validate_chart_sql_alignment(
    *,
    chart_type: str,
    sql: str,
    intent: Dict[str, Any] | None = None,
) -> list[str]:
    """Fail-fast checks: time-based charts require GROUP BY in SQL."""

    _ = intent
    ct = normalize_chart_type(str(chart_type or "").strip(), default="")
    s = str(sql or "")
    errs: list[str] = []
    if not ct:
        return ["chart_sql_mismatch:missing_chart_type"]
    time_family = {"line", "line_multi", "area", "combo_line_bar"}
    if ct in time_family and not re.search(r"\bGROUP\s+BY\b", s, flags=re.IGNORECASE):
        errs.append("chart_sql_mismatch:time_chart_requires_group_by")
    return errs

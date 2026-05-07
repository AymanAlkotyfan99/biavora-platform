"""Deterministic chart selection (intent stage only; not overridden downstream)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_EXPLICIT_CHART_HINTS: tuple[tuple[str, str], ...] = (
    ("scatter plot", "scatter"),
    ("scatter chart", "scatter"),
    ("bubble chart", "scatter"),
    ("bubble", "scatter"),
    ("pie chart", "pie"),
    ("donut chart", "pie"),
    ("pie", "pie"),
    ("line chart", "line"),
    ("line", "line"),
    ("bar chart", "bar"),
    ("stacked bar", "bar_stacked"),
    ("stacked column", "bar_stacked"),
    ("stacked", "bar_stacked"),
    ("histogram", "histogram"),
    ("distribution", "histogram"),
    ("combo", "combo_line_bar"),
    ("line and bar", "combo_line_bar"),
    ("card", "card"),
    ("kpi", "card"),
    ("map", "map"),
    ("geographic", "map"),
    ("table", "table"),
    ("raw rows", "table"),
    ("raw data", "table"),
)

_RAW_TABLE_TOKENS = ("raw data", "raw rows", "show rows", "list rows", "detail rows", "export rows")
_GEO_TOKENS = ("country", "city", "region", "state", "latitude", "longitude", " lat", " lon", "location", "map of")
_DENSITY_TOKENS = ("density", "kernel density", "kde")
_STACKED_TIME_TOKENS = ("stacked area", "area chart", "stacked area chart", "area over time")
_RELATIONSHIP_TOKENS = (" relationship ", " relationship between ", " correlation ", " correlate ", " association ")
_COMPARISON_TOKENS = (" compare ", " comparison ", " vs ", " versus ")


def _lower(q: str) -> str:
    return f" {str(q or '').strip().lower()} "


def _explicit_chart_from_query(query_text: str) -> str:
    lowered = _lower(query_text)
    for token, chart in sorted(_EXPLICIT_CHART_HINTS, key=lambda pair: -len(pair[0])):
        if token in lowered:
            return chart
    return ""


def _list_metric_entries(intent: dict[str, Any]) -> list[Any]:
    metrics = intent.get("metrics", [])
    if isinstance(metrics, list) and metrics:
        return metrics
    specs = intent.get("metric_specs", [])
    if isinstance(specs, list) and specs:
        return specs
    return []


def _metric_count(intent: dict[str, Any]) -> int:
    n = 0
    for item in _list_metric_entries(intent):
        if isinstance(item, dict):
            col = str(item.get("column") or item.get("name") or "").strip()
            if col and col != "*":
                n += 1
        elif isinstance(item, str) and item.strip():
            n += 1
    return n


def _dimensions(intent: dict[str, Any]) -> list[str]:
    dims = intent.get("dimensions", [])
    if not isinstance(dims, list):
        return []
    out: list[str] = []
    for d in dims:
        s = str(d or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def _time_like_dimension(name: str, time_column: str) -> bool:
    n = name.lower()
    if time_column and n == str(time_column).strip().lower():
        return True
    return any(
        t in n
        for t in ("ds", "date", "time", "timestamp", "period", "day_key", "week", "month", "quarter", "year")
    )


def _categorical_dimension_count(intent: dict[str, Any]) -> int:
    time_column = str(intent.get("time_column") or "ds").strip()
    return sum(1 for d in _dimensions(intent) if not _time_like_dimension(d, time_column))


def _is_time_series(intent: dict[str, Any], query_lower: str) -> bool:
    if any(
        t in query_lower
        for t in (
            " over time ",
            " through time ",
            " across time ",
            " trend ",
            " trending ",
            " by month ",
            " by week ",
            " by day ",
            " by quarter ",
            " by year ",
            " per month ",
            " per week ",
            " per day ",
        )
    ):
        return True
    if bool(
        intent.get("is_time_series")
        or intent.get("time_grouping_detected")
        or intent.get("group_by_time")
        or str(intent.get("intent", "")).strip().lower() == "time_series"
        or str(intent.get("intent_type", "")).strip().lower() == "time_series"
    ):
        return True
    grain = str(intent.get("time_granularity", "") or intent.get("time_grain", "")).strip().lower()
    if grain in {"hour", "day", "week", "month", "quarter", "year"}:
        return True
    if _dimensions(intent) and any(_time_like_dimension(d, str(intent.get("time_column") or "")) for d in _dimensions(intent)):
        return True
    return False


def _raw_table_requested(query_lower: str, intent: dict[str, Any]) -> bool:
    if any(t in query_lower for t in _RAW_TABLE_TOKENS):
        return True
    return str(intent.get("output_format", "")).strip().lower() in {"table", "rows", "raw"}


def _geo_requested(query_lower: str, intent: dict[str, Any]) -> bool:
    if any(t in query_lower for t in _GEO_TOKENS):
        return True
    return str(intent.get("intent", "")).strip().lower() == "geo" or str(intent.get("analysis_mode", "")).strip().lower() == "geo"


def _percentage_semantics(query_lower: str, intent: dict[str, Any]) -> bool:
    if str(intent.get("metric_type", "")).strip().lower() in {"percentage", "percent", "ratio"}:
        return True
    return bool(intent.get("is_percentage")) or any(
        t in query_lower for t in ("percentage", "percent", "share", "proportion", "part of", "contribution")
    )


def _trend_semantics(query_lower: str) -> bool:
    return any(
        t in query_lower
        for t in (
            " trend ",
            " trending ",
            " over time ",
            " through time ",
            " across time ",
            " evolution ",
            " evolve ",
            " change over time ",
        )
    )


def _distribution_semantics(query_lower: str, intent: dict[str, Any]) -> bool:
    if bool(intent.get("is_distribution")):
        return True
    return any(t in query_lower for t in ("histogram", "distribution", "frequency bin", "bins"))


def _stacked_semantics(query_lower: str) -> bool:
    return "stacked" in query_lower or "stacked area" in query_lower


def _combo_semantics(query_lower: str) -> bool:
    return "combo" in query_lower or "line and bar" in query_lower or "mixed chart" in query_lower


def _relationship_semantics(query_lower: str, intent: dict[str, Any], is_ts: bool) -> bool:
    if is_ts:
        return False
    if any(token in query_lower for token in _RELATIONSHIP_TOKENS):
        return True
    ops = {
        str(op).strip().lower()
        for op in (intent.get("operations", []) if isinstance(intent.get("operations"), list) else [])
        if str(op).strip()
    }
    return (
        "relationship" in ops
        or str(intent.get("analysis_mode", "")).strip().lower() == "relationship"
        or str(intent.get("intent", "")).strip().lower() in {"correlation", "relationship"}
    )


def _has_grouping(intent: dict[str, Any]) -> bool:
    return bool(_dimensions(intent) or intent.get("group_by") or intent.get("time_grouping_detected"))


@dataclass(frozen=True)
class ChartSelection:
    chart_type: str
    chart_lock: bool
    reason: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "chart_type": self.chart_type,
            "chart_lock": self.chart_lock,
            "reason": self.reason,
            "confidence": self.confidence,
        }


def select_chart_from_intent(intent: dict[str, Any], *, user_query: str = "") -> ChartSelection:
    """Rule-based chart selection; sole authority for default chart_type at intent stage."""

    q = _lower(user_query)
    n_metrics = _metric_count(intent)
    cat_dims = _categorical_dimension_count(intent)
    is_ts = _is_time_series(intent, q)
    has_group = _has_grouping(intent)
    explicit = _explicit_chart_from_query(user_query)

    if bool(intent.get("requires_forecast")) or str(intent.get("final_route", "")).strip().lower() == "forecasting":
        return ChartSelection("line", True, "forecast_requires_line", 1.0)

    if _raw_table_requested(q, intent) or explicit == "table":
        return ChartSelection("table", True, "raw_table_requested", 1.0)

    if _geo_requested(q, intent) and (_dimensions(intent) or cat_dims):
        return ChartSelection("map", True, "geo_location_intent", 0.95)

    if explicit and explicit not in {"table"}:
        if is_ts and explicit == "scatter":
            explicit = ""
        if n_metrics >= 2 and explicit in {"pie", "card", "histogram"}:
            explicit = ""
        if explicit == "scatter" and n_metrics < 2:
            explicit = ""
        if explicit:
            return ChartSelection(explicit, True, f"explicit_user_chart:{explicit}", 1.0)

    # Strict priority engine:
    # 1) percentage/share -> pie
    # 2) distribution -> histogram
    # 3) relationship/correlation -> scatter
    # 4) comparison -> bar / bar_grouped
    # 5) time series (only when none of the above matched) -> line / line_multi
    distribution_intent = _distribution_semantics(q, intent) or (intent.get("analysis_mode") == "distribution")
    percentage_intent = _percentage_semantics(q, intent)
    relationship_intent = _relationship_semantics(q, intent, False)
    comparison_intent = any(token in q for token in _COMPARISON_TOKENS) or "compare" in {
        str(op).strip().lower()
        for op in (intent.get("operations", []) if isinstance(intent.get("operations"), list) else [])
        if str(op).strip()
    }

    if percentage_intent:
        if _trend_semantics(q):
            return ChartSelection("line_multi" if n_metrics >= 2 else "line", True, "percentage_trend_time_series", 1.0)
        return ChartSelection("pie", True, "percentage_priority", 1.0)

    if distribution_intent:
        if any(t in q for t in _DENSITY_TOKENS):
            return ChartSelection("area", True, "distribution_density", 0.95)
        return ChartSelection("histogram", True, "distribution_priority", 1.0)

    if relationship_intent and n_metrics >= 2:
        return ChartSelection("scatter", True, "relationship_priority", 1.0)

    if comparison_intent:
        if n_metrics >= 2:
            return ChartSelection("bar_grouped", True, "comparison_priority_grouped", 0.95)
        return ChartSelection("bar", True, "comparison_priority_bar", 0.9)

    if is_ts and n_metrics >= 2:
        if _stacked_semantics(q) and any(t in q for t in _STACKED_TIME_TOKENS):
            return ChartSelection("area", True, "time_series_stacked_area", 0.95)
        if _stacked_semantics(q) and cat_dims:
            return ChartSelection("bar_stacked", True, "time_series_with_stacked_categories", 0.9)
        if "compare" in q or "comparison" in q or " vs " in q:
            if re.search(r"\bbar\b", q):
                return ChartSelection("bar", True, "time_series_bar_comparison", 0.9)
        if _combo_semantics(q):
            return ChartSelection("combo_line_bar", True, "time_series_combo_requested", 0.9)
        return ChartSelection("line_multi", True, "time_series_multi_metric", 1.0)

    if is_ts and n_metrics == 1:
        return ChartSelection("line", True, "time_series_single_metric", 1.0)

    if str(intent.get("analysis_mode", "")).strip().lower() == "relationship":
        if n_metrics >= 3:
            return ChartSelection("scatter", True, "three_variable_relationship_as_scatter", 0.9)
        if n_metrics >= 2 and not is_ts:
            return ChartSelection("scatter", True, "two_numeric_relationship", 0.95)

    if cat_dims and n_metrics >= 2:
        if _stacked_semantics(q):
            return ChartSelection("bar_stacked", True, "categorical_stacked_values", 0.95)
        return ChartSelection("bar_grouped", False, "categorical_multi_metric", 0.95)

    if cat_dims and n_metrics == 1:
        if "rank" in q or "top " in q or "bottom " in q:
            return ChartSelection("bar", True, "ranking_sorted_bar", 0.9)
        return ChartSelection("bar", False, "categorical_single_metric", 0.95)

    if not has_group and n_metrics == 1 and not is_ts:
        return ChartSelection("card", False, "single_scalar_kpi", 0.9)

    if n_metrics >= 2:
        return ChartSelection("bar_grouped", False, "multi_metric_analytical_fallback", 0.55)

    if n_metrics == 1 and has_group:
        return ChartSelection("bar", False, "single_metric_grouped_fallback", 0.55)

    if n_metrics >= 1:
        return ChartSelection("bar", False, "metric_only_fallback", 0.5)

    return ChartSelection("table", False, "no_metrics_table_fallback", 0.4)


def select_chart_deterministic(
    is_time_series: bool,
    number_of_metrics: int,
    has_categorical_dimension: bool,
    has_grouping: bool,
) -> ChartSelection:
    """Backward-compatible entry: synthesize minimal intent for tests."""

    dims: list[str] = []
    if is_time_series:
        dims.append("ds")
    if has_categorical_dimension:
        dims.append("category")
    metrics: list[dict[str, str]] = [{"column": f"m{i}", "alias": f"m{i}"} for i in range(max(0, number_of_metrics))]
    fake: dict[str, Any] = {
        "is_time_series": is_time_series,
        "time_grouping_detected": is_time_series,
        "dimensions": dims,
        "metrics": metrics,
    }
    return select_chart_from_intent(fake, user_query="")


def extract_chart_selection_inputs(intent: dict[str, Any], user_query: str = "") -> dict[str, Any]:
    if not isinstance(intent, dict):
        return {
            "is_time_series": False,
            "number_of_metrics": 0,
            "has_categorical_dimension": False,
            "has_grouping": False,
        }
    q = _lower(user_query)
    is_time_series = _is_time_series(intent, q)
    number_of_metrics = _metric_count(intent)
    has_categorical_dimension = _categorical_dimension_count(intent) > 0
    has_grouping = _has_grouping(intent)
    return {
        "is_time_series": is_time_series,
        "number_of_metrics": number_of_metrics,
        "has_categorical_dimension": has_categorical_dimension,
        "has_grouping": has_grouping,
    }


def apply_chart_selection(intent: dict[str, Any], *, user_query: str = "") -> dict[str, Any]:
    q = str(user_query or "").strip() or str((intent or {}).get("query") or "").strip()
    enriched = dict(intent) if isinstance(intent, dict) else {}
    locked = bool(enriched.get("chart_lock") or enriched.get("explicit_chart_lock"))
    locked_chart = str(
        enriched.get("final_chart_type")
        or enriched.get("selected_chart_type")
        or enriched.get("chart_type")
        or ((enriched.get("chart") or {}).get("type") if isinstance(enriched.get("chart"), dict) else "")
        or ""
    ).strip().lower()
    if locked and locked_chart:
        selection = ChartSelection(locked_chart, True, "preserved_locked_chart_contract", 1.0)
    else:
        selection = select_chart_from_intent(enriched, user_query=q)

    enriched["chart_type"] = selection.chart_type
    enriched["selected_chart_type"] = selection.chart_type
    enriched["final_chart_type"] = selection.chart_type
    enriched["chart_lock"] = selection.chart_lock
    enriched["explicit_chart_lock"] = selection.chart_lock
    enriched["chart_selection_reason"] = selection.reason
    enriched["chart_reason_code"] = selection.reason
    enriched["chart_selection_confidence"] = selection.confidence
    enriched["chart_selection_source"] = "deterministic_policy"

    # Decouple conflicting semantic flags so downstream planning/visualization
    # never treats distribution/percentage/relationship as time-series.
    ct = str(selection.chart_type or "").strip().lower()
    if ct in {"histogram", "pie", "scatter"}:
        enriched["is_time_series"] = False
        enriched["time_grouping_detected"] = False
        enriched["group_by_time"] = False

    logger.info(
        "chart_selection_applied",
        extra={
            "chart_type": selection.chart_type,
            "chart_lock": selection.chart_lock,
            "user_query_len": len(q),
            "number_of_metrics": _metric_count(enriched),
        },
    )

    return enriched


def enforce_chart_lock(
    intent_chart_type: str,
    chart_lock: bool,
    downstream_chart_type: str,
) -> str:
    if chart_lock:
        if downstream_chart_type != intent_chart_type:
            logger.warning(
                "chart_lock_enforced",
                extra={
                    "intent_chart_type": intent_chart_type,
                    "downstream_chart_type": downstream_chart_type,
                    "action": "override_rejected",
                },
            )
        return intent_chart_type

    return downstream_chart_type

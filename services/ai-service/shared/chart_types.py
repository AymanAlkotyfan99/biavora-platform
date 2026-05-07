"""
Canonical chart taxonomy for ai-service.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ChartType(str, Enum):
    LINE = "line"
    LINE_MULTI = "line_multi"
    BAR = "bar"
    BAR_GROUPED = "bar_grouped"
    BAR_STACKED = "bar_stacked"
    PIE = "pie"
    AREA = "area"
    SCATTER = "scatter"
    HISTOGRAM = "histogram"
    MAP = "map"
    COMBO_LINE_BAR = "combo_line_bar"
    CARD = "card"
    TABLE = "table"
    KPI = CARD


VALID_CHART_TYPES = {chart.value for chart in ChartType}

LEGACY_TO_CANONICAL_CHART_TYPE = {
    "line": ChartType.LINE.value,
    "line_multi": ChartType.LINE_MULTI.value,
    "multi_line": ChartType.LINE_MULTI.value,
    "multiline": ChartType.LINE_MULTI.value,
    "bar": ChartType.BAR.value,
    "bar_grouped": ChartType.BAR_GROUPED.value,
    "grouped_bar": ChartType.BAR_GROUPED.value,
    "bar_stacked": ChartType.BAR_STACKED.value,
    "stacked_bar": ChartType.BAR_STACKED.value,
    "pie": ChartType.PIE.value,
    "area": ChartType.AREA.value,
    "scatter": ChartType.SCATTER.value,
    "histogram": ChartType.HISTOGRAM.value,
    "map": ChartType.MAP.value,
    "combo": ChartType.COMBO_LINE_BAR.value,
    "combo_line_bar": ChartType.COMBO_LINE_BAR.value,
    "line_bar_combo": ChartType.COMBO_LINE_BAR.value,
    "card": ChartType.CARD.value,
    "kpi": ChartType.CARD.value,
    "number": ChartType.CARD.value,
    "scalar": ChartType.CARD.value,
    "table": ChartType.TABLE.value,
}

CHART_TYPE_TO_METABASE_DISPLAY = {
    ChartType.LINE.value: "line",
    ChartType.LINE_MULTI.value: "line",
    ChartType.BAR.value: "bar",
    ChartType.BAR_GROUPED.value: "bar",
    ChartType.BAR_STACKED.value: "bar",
    ChartType.PIE.value: "pie",
    ChartType.AREA.value: "area",
    ChartType.SCATTER.value: "scatter",
    ChartType.HISTOGRAM.value: "histogram",
    ChartType.MAP.value: "map",
    ChartType.COMBO_LINE_BAR.value: "combo",
    ChartType.CARD.value: "scalar",
    ChartType.TABLE.value: "table",
}


def normalize_chart_type(raw_chart_type: Optional[str], *, default: str = ChartType.TABLE.value) -> str:
    if not raw_chart_type:
        return default
    normalized = str(raw_chart_type).strip().lower()
    if not normalized:
        return default
    return LEGACY_TO_CANONICAL_CHART_TYPE.get(normalized, default)


def validate_chart_type(raw_chart_type: Optional[str], *, default: Optional[str] = None) -> str:
    canonical = normalize_chart_type(raw_chart_type, default="")
    if canonical:
        return canonical
    if default is not None:
        return normalize_chart_type(default, default=ChartType.TABLE.value)
    raise ValueError(f"Unsupported chart type: {raw_chart_type!r}")


def to_metabase_display(chart_type: Optional[str]) -> str:
    canonical_chart_type = normalize_chart_type(chart_type)
    return CHART_TYPE_TO_METABASE_DISPLAY.get(canonical_chart_type, "table")


__all__ = [
    "ChartType",
    "VALID_CHART_TYPES",
    "LEGACY_TO_CANONICAL_CHART_TYPE",
    "CHART_TYPE_TO_METABASE_DISPLAY",
    "normalize_chart_type",
    "validate_chart_type",
    "to_metabase_display",
]



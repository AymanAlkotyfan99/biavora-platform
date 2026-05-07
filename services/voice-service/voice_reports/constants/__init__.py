"""voice-service voice_reports.constants.

Per CRIT-03 the chart taxonomy is defined once in
``bi_platform_shared.contracts.chart``. The previous local enum and helpers
are re-exported here as thin aliases so existing imports keep working without
maintaining a duplicate taxonomy.
"""

from bi_platform_shared.contracts.chart import (
    ChartContract,
    ChartTypeEnum as ChartType,
    normalize_chart_type,
    to_metabase_display,
)


VALID_CHART_TYPES = {member.value for member in ChartType}

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
    ChartType.HISTOGRAM.value: "bar",
    ChartType.MAP.value: "map",
    ChartType.COMBO_LINE_BAR.value: "combo",
    ChartType.CARD.value: "scalar",
    ChartType.TABLE.value: "table",
}


def validate_chart_type(raw_chart_type, *, default=None):
    canonical = normalize_chart_type(raw_chart_type, default=ChartType.TABLE).value
    if canonical:
        return canonical
    if default is not None:
        return normalize_chart_type(default, default=ChartType.TABLE).value
    raise ValueError(f"Unsupported chart type: {raw_chart_type!r}")


__all__ = [
    "CHART_TYPE_TO_METABASE_DISPLAY",
    "ChartContract",
    "ChartType",
    "LEGACY_TO_CANONICAL_CHART_TYPE",
    "VALID_CHART_TYPES",
    "normalize_chart_type",
    "to_metabase_display",
    "validate_chart_type",
]

"""visualization-service visualization_api.constants.

Per CRIT-03 the chart taxonomy is owned by ``bi_platform_shared``. Aliases
are exposed here for backwards-compat with existing imports (notably the
Metabase payload builder).
"""

from bi_platform_shared.contracts.chart import (
    ChartContract,
    ChartTypeEnum as ChartType,
    normalize_chart_type,
    to_metabase_display,
)

VALID_CHART_TYPES = {member.value for member in ChartType}

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
    """Resolve chart type without inventing ``table`` when the caller omits input."""

    token = str(raw_chart_type or "").strip()
    if not token:
        if default is not None:
            return normalize_chart_type(default).value
        raise ValueError("chart_type_required")
    return normalize_chart_type(token).value


__all__ = [
    "CHART_TYPE_TO_METABASE_DISPLAY",
    "ChartContract",
    "ChartType",
    "VALID_CHART_TYPES",
    "normalize_chart_type",
    "to_metabase_display",
    "validate_chart_type",
]

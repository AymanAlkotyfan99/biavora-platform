"""
Canonical chart taxonomy and chart contract.

Replaces the four separate chart-type enums that previously lived in:

    services/ai-service/shared/chart_types.py
    services/voice-service/voice_reports/constants/chart_types.py
    services/visualization-service/visualization_api/constants/chart_types.py
    services/report-service/voice_reports/constants/chart_types.py

This module is now the ONLY place a chart type is defined and the ONLY place a
``ChartContract`` is shaped. Visualization-service must not infer chart shape
on its own; it consumes the contract emitted by ai-service as-is and either
renders or rejects with HTTP 400.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ChartTypeEnum(str, Enum):
    """Single canonical chart taxonomy used by every service."""

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


_LEGACY_TO_CANONICAL: Dict[str, ChartTypeEnum] = {
    "line": ChartTypeEnum.LINE,
    "line_multi": ChartTypeEnum.LINE_MULTI,
    "multi_line": ChartTypeEnum.LINE_MULTI,
    "multiline": ChartTypeEnum.LINE_MULTI,
    "bar": ChartTypeEnum.BAR,
    "bar_grouped": ChartTypeEnum.BAR_GROUPED,
    "grouped_bar": ChartTypeEnum.BAR_GROUPED,
    "bar_stacked": ChartTypeEnum.BAR_STACKED,
    "stacked_bar": ChartTypeEnum.BAR_STACKED,
    "pie": ChartTypeEnum.PIE,
    "donut": ChartTypeEnum.PIE,
    "area": ChartTypeEnum.AREA,
    "scatter": ChartTypeEnum.SCATTER,
    "scatterplot": ChartTypeEnum.SCATTER,
    "bubble": ChartTypeEnum.SCATTER,
    "histogram": ChartTypeEnum.HISTOGRAM,
    "map": ChartTypeEnum.MAP,
    "combo": ChartTypeEnum.COMBO_LINE_BAR,
    "combo_line_bar": ChartTypeEnum.COMBO_LINE_BAR,
    "line_bar_combo": ChartTypeEnum.COMBO_LINE_BAR,
    "card": ChartTypeEnum.CARD,
    "kpi": ChartTypeEnum.CARD,
    "number": ChartTypeEnum.CARD,
    "scalar": ChartTypeEnum.CARD,
    "table": ChartTypeEnum.TABLE,
}

_TO_METABASE_DISPLAY: Dict[ChartTypeEnum, str] = {
    ChartTypeEnum.LINE: "line",
    ChartTypeEnum.LINE_MULTI: "line",
    ChartTypeEnum.BAR: "bar",
    ChartTypeEnum.BAR_GROUPED: "bar",
    ChartTypeEnum.BAR_STACKED: "bar",
    ChartTypeEnum.PIE: "pie",
    ChartTypeEnum.AREA: "area",
    ChartTypeEnum.SCATTER: "scatter",
    ChartTypeEnum.HISTOGRAM: "bar",
    ChartTypeEnum.MAP: "map",
    ChartTypeEnum.COMBO_LINE_BAR: "combo",
    ChartTypeEnum.CARD: "scalar",
    ChartTypeEnum.TABLE: "table",
}


def normalize_chart_type(raw: Optional[str], *, default: ChartTypeEnum = ChartTypeEnum.TABLE) -> ChartTypeEnum:
    if raw is None:
        return default
    token = str(raw).strip().lower()
    if not token:
        return default
    return _LEGACY_TO_CANONICAL.get(token, default)


def to_metabase_display(chart_type: ChartTypeEnum | str) -> str:
    canonical = chart_type if isinstance(chart_type, ChartTypeEnum) else normalize_chart_type(chart_type)
    return _TO_METABASE_DISPLAY.get(canonical, "table")


class ChartContract(BaseModel):
    """The single contract every service exchanges to describe a chart.

    The contract is *locked* at the boundary of ai-service. Downstream
    services (voice-service orchestration, visualization-service) must NOT
    re-infer chart shape; they may only validate structural compatibility
    against the actual query result and either render the chart or return
    HTTP 400.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    chart_type: ChartTypeEnum
    x_axis: Optional[str] = Field(default=None, description="Primary X-axis column name.")
    y_axis: Optional[List[str]] = Field(default=None, description="One or more Y-axis (measure) column names.")
    series_dimension: Optional[str] = Field(
        default=None,
        description="Optional dimension column used for grouping/series (e.g., region for bar_grouped).",
    )
    label_column: Optional[str] = Field(default=None, description="Label column for pie/card charts.")
    value_column: Optional[str] = Field(default=None, description="Value column for pie/card charts.")
    bin_column: Optional[str] = Field(default=None, description="Continuous column to bucket for histogram.")
    bin_count: Optional[int] = Field(default=None, ge=1, le=200)
    aggregations: List[str] = Field(default_factory=list)
    locked: bool = Field(
        default=True,
        description="When True, downstream services MUST NOT change chart_type.",
    )
    explicit_chart_lock: bool | None = Field(
        default=None,
        description="Alias of locked from ai-service traces; when set, overrides locked.",
    )
    chart_source: str = Field(
        default="ai_service",
        description="Service that authored the contract. Always 'ai_service' in production.",
    )
    rationale: Optional[str] = Field(
        default=None,
        description="Short human-readable reason for the chart selection (for trace).",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sync_explicit_chart_lock(self) -> "ChartContract":
        if self.explicit_chart_lock is not None:
            object.__setattr__(self, "locked", bool(self.explicit_chart_lock))
        return self

    @field_validator("chart_type", mode="before")
    @classmethod
    def _coerce_chart_type(cls, value: Any) -> Any:
        if isinstance(value, ChartTypeEnum):
            return value
        if isinstance(value, str):
            return normalize_chart_type(value).value
        return value

    @field_validator("y_axis", mode="before")
    @classmethod
    def _coerce_y_axis(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, str):
            return [value]
        return value

    def required_columns(self) -> List[str]:
        """Columns that MUST exist in the query result for this contract to render.

        Used by visualization-service for the structural compatibility check
        described in the audit's CRIT-03 fix.
        """

        cols: List[str] = []
        if self.x_axis:
            cols.append(self.x_axis)
        if self.y_axis:
            cols.extend(self.y_axis)
        if self.series_dimension:
            cols.append(self.series_dimension)
        if self.label_column:
            cols.append(self.label_column)
        if self.value_column:
            cols.append(self.value_column)
        if self.bin_column:
            cols.append(self.bin_column)
        return [c for c in dict.fromkeys(cols) if c]

    def metabase_display(self) -> str:
        return to_metabase_display(self.chart_type)


__all__ = [
    "ChartTypeEnum",
    "ChartContract",
    "normalize_chart_type",
    "to_metabase_display",
]

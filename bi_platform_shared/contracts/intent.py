"""
Canonical Intent contract.

Replaces the implicit, dict-shaped IR (intent representation) that previously
flowed between ai-service stages without validation. Every LLM-emitted IR is
now validated through ``CanonicalIntent.model_validate(...)`` before any
downstream stage consumes it. Validation failures trigger the deterministic
repair pass instead of being silently propagated.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bi_platform_shared.contracts.chart import ChartTypeEnum


class OperationCode(str, Enum):
    """Atomic analytical operation codes the SQL compiler can emit."""

    AGGREGATE = "aggregate"
    GROUP_BY = "group_by"
    FILTER = "filter"
    SORT = "sort"
    LIMIT = "limit"
    TOP_N = "top_n"
    BOTTOM_N = "bottom_n"
    DISTRIBUTION = "distribution"
    COMPARE = "compare"
    TIME_SERIES = "time_series"
    FORECAST = "forecast"
    JOIN = "join"
    PERCENT_OF_TOTAL = "percent_of_total"
    DELTA = "delta"


class IntentMetric(BaseModel):
    """A single measure / aggregation requested by the user."""

    model_config = ConfigDict(extra="forbid")

    name: str
    column: Optional[str] = None
    aggregation: Optional[str] = Field(
        default=None,
        description="One of: sum, count, count_distinct, avg, min, max, median.",
    )
    alias: Optional[str] = None


class IntentFilter(BaseModel):
    """A single filter predicate."""

    model_config = ConfigDict(extra="forbid")

    column: str
    operator: str = Field(
        description="One of: eq, ne, in, not_in, gt, gte, lt, lte, between, like, ilike, is_null, is_not_null."
    )
    value: Any = None
    case_sensitive: bool = False


class TimeBinding(BaseModel):
    """Binds an analytical question to a time dimension and grain."""

    model_config = ConfigDict(extra="forbid")

    column: Optional[str] = None
    grain: Optional[str] = Field(
        default=None,
        description="One of: minute, hour, day, week, month, quarter, year.",
    )
    relative_window: Optional[str] = Field(
        default=None,
        description='Free-form relative window such as "last 30 days" or "ytd".',
    )
    start: Optional[str] = None
    end: Optional[str] = None


class ForecastSpec(BaseModel):
    """Specification for a forecasting request (only valid when intent_type=='predictive')."""

    model_config = ConfigDict(extra="forbid")

    horizon: Optional[int] = Field(default=None, ge=1, le=3650)
    horizon_unit: Optional[str] = Field(default="day")
    target_column: Optional[str] = None
    date_column: Optional[str] = None
    confidence_level: Optional[float] = Field(default=None, ge=0.5, le=0.999)
    seasonality: Optional[str] = None


class OrderBy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    direction: Literal["asc", "desc"] = "desc"


class Ranking(BaseModel):
    """Top-N / Bottom-N ranking specification."""

    model_config = ConfigDict(extra="forbid")

    direction: Literal["top", "bottom"] = "top"
    n: int = Field(ge=1, le=10_000)
    by: Optional[str] = None


class Ambiguity(BaseModel):
    """A flagged ambiguity the system could not deterministically resolve."""

    model_config = ConfigDict(extra="forbid")

    field: str
    reason: str
    candidates: List[str] = Field(default_factory=list)


class SchemaProvenance(BaseModel):
    """Where the schema used to interpret this intent came from.

    Surfacing this in the trace is critical for diagnosing ETL-vs-AI schema
    drift (audit §12.x).
    """

    model_config = ConfigDict(extra="forbid")

    schema_hash: Optional[str] = None
    loaded_at: Optional[datetime] = None
    source: Optional[str] = Field(
        default=None,
        description="Which service produced the schema snapshot (metadata-service | query-service).",
    )
    workspace_id: Optional[str] = None
    table_name: Optional[str] = None


class CanonicalIntent(BaseModel):
    """The validated, structured representation of the user's question."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent_type: Literal["analytical", "predictive", "non_data", "invalid", "ambiguous"]
    confidence: float = Field(ge=0.0, le=1.0)
    language: Optional[str] = Field(default=None, description="ISO 639-1 language code (en, ar, fr, ...).")

    metrics: List[IntentMetric] = Field(default_factory=list)
    dimensions: List[str] = Field(default_factory=list)
    filters: List[IntentFilter] = Field(default_factory=list)
    time_binding: Optional[TimeBinding] = None
    operations: List[OperationCode] = Field(default_factory=list)
    order_by: List[OrderBy] = Field(default_factory=list)
    ranking: Optional[Ranking] = None
    forecast: Optional[ForecastSpec] = None

    chart_type_hint: Optional[ChartTypeEnum] = None
    selected_columns: List[str] = Field(default_factory=list)
    selected_table: Optional[str] = None

    ambiguities: List[Ambiguity] = Field(default_factory=list)
    schema_provenance: Optional[SchemaProvenance] = None
    raw_question: Optional[str] = None

    @field_validator("operations", mode="before")
    @classmethod
    def _coerce_ops(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            return [v if isinstance(v, OperationCode) else str(v).strip().lower() for v in value if v]
        return value


__all__ = [
    "Ambiguity",
    "CanonicalIntent",
    "ForecastSpec",
    "IntentFilter",
    "IntentMetric",
    "OperationCode",
    "OrderBy",
    "Ranking",
    "SchemaProvenance",
    "TimeBinding",
]

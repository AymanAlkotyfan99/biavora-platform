"""
Query and forecast execution contracts.

Aligns with audit §9.8 and §11.x: every executor must return a typed result
that explicitly carries metadata (column types, scanned rows, settings
applied, abortion reason) that downstream stages and the trace need.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from bi_platform_shared.contracts.trace import StageStatus


class QueryExecutionResult(BaseModel):
    """The canonical shape returned by query-service after running a SELECT."""

    model_config = ConfigDict(extra="forbid")

    columns: List[str]
    rows: List[List[Any]]
    column_types: List[str] = Field(default_factory=list)
    row_count: int = 0
    scanned_rows: Optional[int] = None
    output_bytes: Optional[int] = None
    execution_time_ms: float = 0.0
    aborted_due_to_timeout: bool = False
    settings_applied: Dict[str, Any] = Field(default_factory=dict)
    workspace_database: Optional[str] = None
    sql_hash: Optional[str] = Field(
        default=None, description="SHA-256 prefix of the executed SQL for log redaction."
    )
    status: StageStatus = StageStatus.SUCCESS
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class ForecastResult(BaseModel):
    """Output of the forecasting bridge (TimesFM)."""

    model_config = ConfigDict(extra="forbid")

    horizon: int
    horizon_unit: str = "day"
    point_forecasts: List[float] = Field(default_factory=list)
    lower_bounds: List[float] = Field(default_factory=list)
    upper_bounds: List[float] = Field(default_factory=list)
    timestamps: List[datetime] = Field(default_factory=list)
    historical_points_used: int = 0
    confidence_level: float = 0.95
    model_name: str = "timesfm"
    model_version: Optional[str] = None
    status: StageStatus = StageStatus.SUCCESS
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class RenderedQuestion(BaseModel):
    """The Metabase rendering result returned by visualization-service."""

    model_config = ConfigDict(extra="forbid")

    question_id: Optional[int] = None
    embed_url: Optional[str] = None
    metabase_card_id: Optional[int] = None
    chart_type_used: Optional[str] = None
    status: StageStatus = StageStatus.SUCCESS
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


__all__ = ["QueryExecutionResult", "ForecastResult", "RenderedQuestion"]

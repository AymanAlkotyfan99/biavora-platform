"""
Pipeline-level contracts: request, per-stage outputs, full result, and trace.

These shapes are what voice-service ⇄ ai-service exchange. Each stage carries
its own typed payload and a normalized ``StageStatus`` so the trace cannot
contain ad-hoc strings such as ``"ok"`` or ``"degraded_success"``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from bi_platform_shared.contracts.chart import ChartContract
from bi_platform_shared.contracts.execution import (
    ForecastResult,
    QueryExecutionResult,
    RenderedQuestion,
)
from bi_platform_shared.contracts.intent import CanonicalIntent
from bi_platform_shared.contracts.trace import StageStatus


class RequestMetadata(BaseModel):
    """Routing/identity metadata that travels with every pipeline request."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    workspace_id: str
    user_id: Optional[str] = None
    job_id: Optional[str] = None
    traceparent: Optional[str] = None
    tracestate: Optional[str] = None
    received_at: Optional[datetime] = None
    source: Optional[str] = Field(default=None, description="voice | text | api")


class PipelineRequest(BaseModel):
    """Request envelope sent from voice-service to ai-service."""

    model_config = ConfigDict(extra="forbid")

    metadata: RequestMetadata
    input_type: Literal["audio", "text"]
    text: Optional[str] = None
    audio_object_key: Optional[str] = None
    audio_filename: Optional[str] = None
    audio_mime_type: Optional[str] = None
    locale_hint: Optional[str] = None
    dataset_table: Optional[str] = None
    dataset_database: Optional[str] = None


class _BaseStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: StageStatus = StageStatus.SUCCESS
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    notes: Optional[str] = None


class TranscriptionStage(_BaseStage):
    transcript: Optional[str] = None
    language_detected: Optional[str] = None
    audio_duration_seconds: Optional[float] = None
    model_name: Optional[str] = None
    cached: bool = False


class PreprocessLowStage(_BaseStage):
    cleaned_text: Optional[str] = None
    language: Optional[str] = None
    rules_applied: List[str] = Field(default_factory=list)


class ClassificationStage(_BaseStage):
    label: Literal["ANALYTICAL", "PREDICTIVE", "NON_DATA", "INVALID", "AMBIGUOUS"] = "INVALID"
    confidence: float = 0.0
    source: Literal["deterministic", "llm", "fallback"] = "llm"
    reasoning: Optional[str] = None
    evidence_tokens: List[str] = Field(default_factory=list)


class PreprocessHighStage(_BaseStage):
    schema_validation_status: Optional[str] = None
    selected_table: Optional[str] = None
    selected_columns: List[str] = Field(default_factory=list)
    forecast_date_column: Optional[str] = None
    forecast_target_column: Optional[str] = None


class SqlStage(_BaseStage):
    sql: Optional[str] = None
    sql_hash: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    ch_settings: Dict[str, Any] = Field(default_factory=dict)


class SqlReviewStage(_BaseStage):
    accepted: bool = False
    review_decision: Optional[Literal["accepted_compiler", "accepted_llm_correction", "rejected"]] = None
    final_sql: Optional[str] = None
    intent_alignment_passed: Optional[bool] = None
    safety_validation_passed: Optional[bool] = None


class PipelineTrace(BaseModel):
    """Versioned trace bundle persisted alongside every pipeline run."""

    model_config = ConfigDict(extra="forbid")

    version: str = "2.0"
    request: RequestMetadata
    transcription: Optional[TranscriptionStage] = None
    preprocess_low: Optional[PreprocessLowStage] = None
    classification: Optional[ClassificationStage] = None
    preprocess_high: Optional[PreprocessHighStage] = None
    intent: Optional[CanonicalIntent] = None
    sql: Optional[SqlStage] = None
    sql_review: Optional[SqlReviewStage] = None
    query_execution: Optional[QueryExecutionResult] = None
    chart_contract: Optional[ChartContract] = None
    forecast: Optional[ForecastResult] = None
    visualization: Optional[RenderedQuestion] = None
    overall_status: StageStatus = StageStatus.SUCCESS
    final_user_message: Optional[str] = None


class PipelineResult(BaseModel):
    """The body voice-service returns to its caller (Celery task / API)."""

    model_config = ConfigDict(extra="forbid")

    metadata: RequestMetadata
    overall_status: StageStatus
    intent: Optional[CanonicalIntent] = None
    chart_contract: Optional[ChartContract] = None
    sql: Optional[str] = None
    final_sql: Optional[str] = None
    query_result: Optional[QueryExecutionResult] = None
    forecast: Optional[ForecastResult] = None
    visualization: Optional[RenderedQuestion] = None
    trace: PipelineTrace
    final_user_message: Optional[str] = None
    degraded_reason: Optional[str] = None


__all__ = [
    "ClassificationStage",
    "PipelineRequest",
    "PipelineResult",
    "PipelineTrace",
    "PreprocessHighStage",
    "PreprocessLowStage",
    "RequestMetadata",
    "SqlReviewStage",
    "SqlStage",
    "TranscriptionStage",
]

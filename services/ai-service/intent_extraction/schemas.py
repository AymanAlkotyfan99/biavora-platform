from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict


IntentType = Literal["analytical", "predictive"]
IntentExtractionErrorType = Literal[
    "none",
    "system",
    "model",
    "input",
    "schema_mismatch",
    "query_service_auth",
    "unknown",
]
IntentExtractionActionType = Literal["retry", "stop", "proceed"]
NextStepType = Literal["metabase", "forecasting"]


class StructuredIntent(TypedDict):
    intent_type: IntentType
    intent: str
    metrics: list[str]
    metric_specs: list[dict[str, Any]]
    dimensions: list[str]
    filters: list[dict[str, Any]]
    time_range: str
    aggregation: str
    target_column: str
    table: str
    order_by: list[dict[str, Any]]
    limit: int | None
    ranking: dict[str, Any]
    operations: list[str]
    ambiguities: list[dict[str, Any]]
    chart: NotRequired[dict[str, Any]]
    metric_type: NotRequired[str]
    selected_chart_type: NotRequired[str]
    chart_type: NotRequired[str]


class IntentExtractionTaskResult(TypedDict, total=False):
    status: Literal["success", "failed", "degraded", "skipped", "rejected"]
    intent_type: IntentType
    sql_query: str
    next_step: NextStepType
    error_type: IntentExtractionErrorType
    action_taken: IntentExtractionActionType
    confidence: float
    extracted_intent: StructuredIntent
    normalized_intent: dict[str, Any]
    execution_result: Any
    downstream_result: Any
    attempts: list[dict[str, Any]]
    attempts_count: int
    warnings: list[dict[str, str]]
    errors: list[dict[str, str]]
    debug_metadata: dict[str, Any]
    started_at: str
    finished_at: str
    duration_ms: int


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


@dataclass(frozen=True)
class IntentExtractionConfig:
    llm_provider: str
    ollama_url: str
    ollama_model: str
    request_timeout_seconds: float
    max_retries: int
    clickhouse_executor_path: str
    metabase_handler_path: str
    forecasting_handler_path: str

    @classmethod
    def from_env(cls) -> "IntentExtractionConfig":
        from shared.ollama_env import global_ollama_read_timeout_seconds

        retries = _env_int("INTENT_EXTRACTION_MAX_RETRIES", 2)
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
        default_ollama_url = f"{ollama_host.rstrip('/')}/api/generate"
        global_timeout = global_ollama_read_timeout_seconds()
        return cls(
            llm_provider=os.getenv("INTENT_EXTRACTION_LLM_PROVIDER", "openrouter").strip().lower(),
            ollama_url=os.getenv("INTENT_EXTRACTION_OLLAMA_URL", default_ollama_url),
            ollama_model=os.getenv("INTENT_EXTRACTION_OLLAMA_MODEL", "gemma3:1b"),
            request_timeout_seconds=_env_float(
                "INTENT_EXTRACTION_TIMEOUT_SECONDS",
                _env_float("OLLAMA_INTENT_TIMEOUT", global_timeout),
            ),
            max_retries=max(0, min(retries, 3)),
            clickhouse_executor_path=os.getenv("INTENT_EXTRACTION_CLICKHOUSE_EXECUTOR_PATH", "").strip(),
            metabase_handler_path=os.getenv("INTENT_EXTRACTION_METABASE_HANDLER_PATH", "").strip(),
            forecasting_handler_path=os.getenv(
                "INTENT_EXTRACTION_FORECASTING_HANDLER_PATH",
                "forecasting.dagster_handler:run_forecasting_handler",
            ).strip(),
        )


def build_intent_extraction_success_result(
    *,
    intent_type: IntentType,
    sql_query: str,
    next_step: NextStepType,
    extracted_intent: StructuredIntent,
    normalized_intent: dict[str, Any],
    execution_result: Any = None,
    downstream_result: Any = None,
) -> IntentExtractionTaskResult:
    return {
        "status": "success",
        "intent_type": intent_type,
        "sql_query": sql_query,
        "next_step": next_step,
        "error_type": "none",
        "action_taken": "proceed",
        "confidence": 0.0,
        "extracted_intent": extracted_intent,
        "normalized_intent": normalized_intent,
        "execution_result": execution_result,
        "downstream_result": downstream_result,
    }


def build_intent_extraction_failed_result(
    *,
    intent_type: IntentType,
    next_step: NextStepType,
    error_type: IntentExtractionErrorType,
    action_taken: IntentExtractionActionType,
) -> IntentExtractionTaskResult:
    return {
        "status": "failed",
        "intent_type": intent_type,
        "sql_query": "",
        "next_step": next_step,
        "error_type": error_type,
        "action_taken": action_taken,
        "confidence": 0.0,
    }

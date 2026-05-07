from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, TypedDict


HighPreprocessErrorType = Literal["none", "system", "llm", "schema", "business", "input", "unknown"]
HighPreprocessActionType = Literal["retry", "stop", "proceed"]


class SchemaColumn(TypedDict):
    name: str
    type: str


class UserSchema(TypedDict):
    tables: list[str]
    columns: dict[str, list[SchemaColumn]]


class ValidationMapping(TypedDict):
    requested: str
    matched_table: str
    matched_column: str
    status: Literal["exact", "mapped", "derivable", "invalid"]
    reason: str


class SchemaValidationResult(TypedDict):
    is_valid: bool
    missing_column: str
    mappings: list[ValidationMapping]
    derivable_columns: list[ValidationMapping]
    invalid_mappings: list[ValidationMapping]


class PreprocessHighResult(TypedDict, total=False):
    status: Literal["success", "failed", "rejected", "degraded"]
    final_query: str
    schema_valid: bool
    degraded: bool
    deferred: bool
    degradation_reason: str
    confidence: float
    error_type: str
    action_taken: HighPreprocessActionType
    message: str
    missing_column: str
    schema_used: UserSchema
    mappings: list[ValidationMapping]
    derivable_columns: list[ValidationMapping]
    invalid_mappings: list[ValidationMapping]
    original_terms: list[str]
    corrected_terms: list[str]
    unresolved_terms: list[str]
    unresolved_lexical_terms: list[str]
    unsupported_terms: list[str]
    term_resolutions: list[dict[str, str]]
    candidate_columns: dict[str, list[str]]
    candidate_tables: list[str]
    selected_table: str
    selected_columns: list[str]
    schema_validation_status: str
    route: str
    skipped_schema_terms: list[str]
    attempts: list[dict[str, object]]
    attempts_count: int
    warnings: list[dict[str, str]]
    errors: list[dict[str, str]]
    term_corrections: list[dict[str, str]]
    user_friendly_messages: list[str]
    debug_metadata: dict[str, object]
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


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class HighPreprocessConfig:
    ollama_url: str
    ollama_model: str
    request_timeout_seconds: float
    enable_llm_schema_validation: bool
    llm_schema_validation_timeout_seconds: float
    max_retries: int
    clickhouse_host: str
    clickhouse_port: int
    clickhouse_user: str
    clickhouse_password: str
    clickhouse_default_database: str
    user_database_template: str
    schema_cache_ttl_seconds: int
    default_user_id: str

    @classmethod
    def from_env(cls) -> "HighPreprocessConfig":
        from shared.ollama_env import global_ollama_read_timeout_seconds

        retries = _env_int("OLLAMA_SCHEMA_VALIDATION_MAX_RETRIES", _env_int("PREPROCESS_HIGH_MAX_RETRIES", 1))
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
        default_ollama_url = f"{ollama_host.rstrip('/')}/api/generate"
        return cls(
            ollama_url=os.getenv("PREPROCESS_HIGH_OLLAMA_URL", default_ollama_url),
            ollama_model=os.getenv("PREPROCESS_HIGH_OLLAMA_MODEL", "gemma3:1b"),
            request_timeout_seconds=_env_float(
                "PREPROCESS_HIGH_TIMEOUT_SECONDS",
                global_ollama_read_timeout_seconds(),
            ),
            enable_llm_schema_validation=_env_bool("ENABLE_LLM_SCHEMA_VALIDATION", False),
            llm_schema_validation_timeout_seconds=_env_float("OLLAMA_SCHEMA_VALIDATION_TIMEOUT", 90.0),
            max_retries=max(0, min(retries, 3)),
            clickhouse_host=os.getenv("CLICKHOUSE_HOST", "localhost"),
            clickhouse_port=_env_int("CLICKHOUSE_PORT", 8123),
            clickhouse_user=os.getenv("CLICKHOUSE_USER", "etl_user"),
            clickhouse_password=os.getenv("CLICKHOUSE_PASSWORD", "etl_pass123"),
            clickhouse_default_database=os.getenv("CLICKHOUSE_DATABASE", "etl"),
            user_database_template=os.getenv("PREPROCESS_HIGH_DATABASE_TEMPLATE", "").strip(),
            schema_cache_ttl_seconds=max(0, _env_int("PREPROCESS_HIGH_SCHEMA_CACHE_TTL_SECONDS", 60)),
            default_user_id=os.getenv("PREPROCESS_HIGH_DEFAULT_USER_ID", "default_user"),
        )


def build_preprocess_high_success_result(
    final_query: str,
    *,
    schema_used: UserSchema | None = None,
    mappings: list[ValidationMapping] | None = None,
    derivable_columns: list[ValidationMapping] | None = None,
    invalid_mappings: list[ValidationMapping] | None = None,
) -> PreprocessHighResult:
    result: PreprocessHighResult = {
        "status": "success",
        "final_query": final_query,
        "schema_valid": True,
        "confidence": 0.0,
        "error_type": "none",
        "action_taken": "proceed",
    }
    if schema_used is not None:
        result["schema_used"] = schema_used
    if mappings is not None:
        result["mappings"] = mappings
    if derivable_columns is not None:
        result["derivable_columns"] = derivable_columns
    if invalid_mappings is not None:
        result["invalid_mappings"] = invalid_mappings
    return result


def build_preprocess_high_failed_result(
    *,
    error_type: HighPreprocessErrorType,
    action_taken: HighPreprocessActionType,
    final_query: str = "",
    schema_used: UserSchema | None = None,
    mappings: list[ValidationMapping] | None = None,
    derivable_columns: list[ValidationMapping] | None = None,
    invalid_mappings: list[ValidationMapping] | None = None,
) -> PreprocessHighResult:
    result: PreprocessHighResult = {
        "status": "failed",
        "final_query": final_query,
        "schema_valid": False,
        "confidence": 0.0,
        "error_type": error_type,
        "action_taken": action_taken,
    }
    if schema_used is not None:
        result["schema_used"] = schema_used
    if mappings is not None:
        result["mappings"] = mappings
    if derivable_columns is not None:
        result["derivable_columns"] = derivable_columns
    if invalid_mappings is not None:
        result["invalid_mappings"] = invalid_mappings
    return result


def build_preprocess_high_rejected_result(
    *,
    final_query: str,
    missing_column: str,
    message: str = "The requested column does not exist in your data.",
    schema_used: UserSchema | None = None,
    mappings: list[ValidationMapping] | None = None,
    derivable_columns: list[ValidationMapping] | None = None,
    invalid_mappings: list[ValidationMapping] | None = None,
) -> PreprocessHighResult:
    result: PreprocessHighResult = {
        "status": "rejected",
        "final_query": final_query,
        "schema_valid": False,
        "confidence": 0.0,
        "error_type": "business",
        "action_taken": "stop",
        "message": message,
        "missing_column": missing_column,
    }
    if schema_used is not None:
        result["schema_used"] = schema_used
    if mappings is not None:
        result["mappings"] = mappings
    if derivable_columns is not None:
        result["derivable_columns"] = derivable_columns
    if invalid_mappings is not None:
        result["invalid_mappings"] = invalid_mappings
    return result

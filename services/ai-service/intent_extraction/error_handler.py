from __future__ import annotations

import requests

from intent_extraction.schemas import (
    IntentExtractionActionType,
    IntentExtractionConfig,
    IntentExtractionErrorType,
)


class IntentExtractionError(Exception):
    """Base exception for intent extraction failures."""


class IntentExtractionInputError(IntentExtractionError):
    """Input query or schema is invalid."""


class IntentExtractionSystemError(IntentExtractionError):
    """Runtime system issue (timeouts, transient dependency errors)."""


class IntentExtractionModelOutputError(IntentExtractionError):
    """Model returned invalid or malformed output."""


class IntentExtractionSchemaMismatchError(IntentExtractionError):
    """Extracted intent does not align with ClickHouse schema."""


def classify_intent_extraction_error(exception: BaseException) -> IntentExtractionErrorType:
    if isinstance(exception, IntentExtractionInputError):
        return "input"

    if isinstance(exception, IntentExtractionSchemaMismatchError):
        return "schema_mismatch"

    if isinstance(exception, IntentExtractionModelOutputError):
        return "model"

    if isinstance(exception, IntentExtractionSystemError):
        return "system"

    if isinstance(exception, requests.Timeout):
        return "system"

    lowered = str(exception).lower()
    if "query_service_unauthorized" in lowered or "query_service_auth_not_configured" in lowered:
        return "query_service_auth"
    if "timeout" in lowered or "timed out" in lowered or "temporary" in lowered:
        return "system"
    if "json" in lowered or "parse" in lowered or "malformed" in lowered:
        return "model"
    if (
        "schema" in lowered
        or "column" in lowered
        or "table" in lowered
        or "does not exist" in lowered
        or "not found in schema" in lowered
    ):
        return "schema_mismatch"

    return "unknown"


def decide_intent_extraction_action(
    *,
    error_type: IntentExtractionErrorType,
    retry_count: int,
    config: IntentExtractionConfig,
) -> IntentExtractionActionType:
    if error_type in {"input", "schema_mismatch", "query_service_auth"}:
        return "stop"

    if error_type in {"system", "model", "unknown"} and retry_count < config.max_retries:
        return "retry"

    return "stop"

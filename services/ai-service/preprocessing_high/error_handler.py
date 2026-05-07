from __future__ import annotations

import requests

from preprocessing_high.schemas import HighPreprocessActionType, HighPreprocessConfig, HighPreprocessErrorType


class PreprocessHighError(Exception):
    """Base exception for high-level preprocessing failures."""


class PreprocessHighInputError(PreprocessHighError):
    """Invalid high-level preprocessing input."""


class PreprocessHighSystemError(PreprocessHighError):
    """Transient system/runtime failure."""


class PreprocessHighSchemaLoadError(PreprocessHighError):
    """Schema loading failure from ClickHouse."""


class PreprocessHighLLMError(PreprocessHighError):
    """LLM returned invalid or unusable content."""


class PreprocessHighMissingColumnError(PreprocessHighError):
    """Business rejection when a referenced column cannot be resolved.

    Phase 5 / CRIT-14: forecasting reuses this exception to surface the
    canonical ``forecast_missing_time_column`` /
    ``forecast_missing_target_column`` codes with a precise, user-safe
    message.
    """

    def __init__(self, missing_column: str, message: str | None = None) -> None:
        self.missing_column = missing_column
        super().__init__(
            message
            or f"The requested column does not exist in your data: {missing_column}"
        )


def classify_preprocess_high_error(exception: BaseException) -> HighPreprocessErrorType:
    if isinstance(exception, PreprocessHighInputError):
        return "input"

    if isinstance(exception, PreprocessHighMissingColumnError):
        return "business"

    if isinstance(exception, PreprocessHighSchemaLoadError):
        return "schema"

    if isinstance(exception, PreprocessHighLLMError):
        return "llm"

    if isinstance(exception, PreprocessHighSystemError):
        return "system"

    if isinstance(exception, requests.Timeout):
        return "system"

    if isinstance(exception, requests.RequestException):
        lowered = str(exception).lower()
        if "timeout" in lowered or "timed out" in lowered:
            return "system"
        return "unknown"

    lowered = str(exception).lower()
    if "timeout" in lowered or "timed out" in lowered or "temporary" in lowered:
        return "system"

    return "unknown"


def decide_preprocess_high_action(
    *,
    error_type: HighPreprocessErrorType,
    retry_count: int,
    config: HighPreprocessConfig,
) -> HighPreprocessActionType:
    if error_type in {"input", "business"}:
        return "stop"

    if error_type in {"system", "llm", "schema", "unknown"} and retry_count < config.max_retries:
        return "retry"

    return "stop"

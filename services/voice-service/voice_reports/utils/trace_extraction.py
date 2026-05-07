from __future__ import annotations

from copy import deepcopy
from typing import Any
import logging

logger = logging.getLogger(__name__)

CANONICAL_STAGE_KEYS = (
    "preprocessing_low",
    "classification",
    "intent_extraction",
    "query_execution",
    "visualization",
)

_STAGE_ALIASES: dict[str, tuple[str, ...]] = {
    "preprocessing_low": ("preprocessing_low", "preprocessing_low_asset"),
    "classification": ("classification", "classification_asset", "input_validation"),
    "intent_extraction": ("intent_extraction", "intent_extraction_asset", "analytical_intent"),
    "query_execution": ("query_execution", "query_execution_asset"),
    "visualization": ("visualization", "visualization_asset"),
}


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def is_valid_trace(trace: dict) -> bool:
    if not isinstance(trace, dict):
        return False
    return all(any(alias in trace for alias in aliases) for aliases in _STAGE_ALIASES.values())


def _payload_already_flat_pipeline_trace(payload: dict[str, Any]) -> bool:
    """True when ``payload`` is a persisted pipeline_trace object (not an API envelope)."""

    if is_valid_trace(payload):
        return True
    if str(payload.get("trace_version") or "").strip():
        return True
    # Mid-pipeline traces may omit late stages but still carry analyst-grade content.
    if any(
        key in payload
        for key in (
            "classification_asset",
            "intent_extraction_asset",
            "query_execution_asset",
            "visualization_asset",
            "sql_review",
            "sql_generation",
        )
    ):
        return True
    return False


def extract_pipeline_trace(response: dict[str, Any]) -> dict[str, Any]:
    """
    Extract a full pipeline trace from ai-service responses.

    Accepts either:

    * API envelopes (``{"result": {"pipeline_trace": {...}}}``), or
    * Already-persisted flat ``pipeline_trace`` JSON saved on ``VoiceReport``.
    """

    if not isinstance(response, dict):
        logger.warning("pipeline_trace_extract_invalid_payload", extra={"type": type(response).__name__})
        return {}

    if _payload_already_flat_pipeline_trace(response):
        out = deepcopy(response)
        logger.debug(
            "pipeline_trace_extract_flat",
            extra={"keys": len(out), "valid": is_valid_trace(out)},
        )
        return out

    payload = deepcopy(response)
    response_keys = list(payload.keys())
    logger.debug("pipeline_trace_extract_envelope", extra={"top_level_keys": response_keys})

    candidates: list[tuple[str, Any]] = []
    candidate_paths = (
        ("pipeline_trace", ("pipeline_trace",)),
        ("result.pipeline_trace", ("result", "pipeline_trace")),
        ("pipeline_result.pipeline_trace", ("pipeline_result", "pipeline_trace")),
        ("trace", ("trace",)),
        ("result.trace", ("result", "trace")),
        ("pipeline_result.trace", ("pipeline_result", "trace")),
        ("ai_trace", ("ai_trace",)),
    )

    for label, path in candidate_paths:
        current: Any = payload
        found = True
        for segment in path:
            if not isinstance(current, dict) or segment not in current:
                found = False
                break
            current = current.get(segment)
        if found:
            candidates.append((label, current))

    selected_key = "none"
    selected_trace: dict[str, Any] = {}
    for label, candidate in candidates:
        candidate_dict = _safe_dict(candidate)
        if is_valid_trace(candidate_dict):
            selected_key = label
            selected_trace = deepcopy(candidate_dict)
            break

    logger.debug(
        "pipeline_trace_extract_result",
        extra={"source": selected_key, "valid": bool(selected_trace), "size": len(selected_trace)},
    )

    if not selected_trace and candidates:
        for label, candidate in candidates:
            candidate_dict = _safe_dict(candidate)
            if candidate_dict:
                selected_key = f"{label}_partial"
                selected_trace = deepcopy(candidate_dict)
                logger.warning(
                    "pipeline_trace_partial_fallback",
                    extra={"source": selected_key, "keys": list(selected_trace.keys())[:20]},
                )
                break
        if not selected_trace:
            logger.warning(
                "pipeline_trace_rejected_candidates",
                extra={"candidates": [label for label, _ in candidates]},
            )
    return selected_trace

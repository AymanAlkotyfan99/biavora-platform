"""Intent classification task (Phase 4 / CRIT-06).

The previous version of this module shipped its own ``_PREDICTIVE_KEYWORDS`` /
``_PREDICTIVE_PATTERNS`` tables which competed with the LLM and with the
shared canonical detector in ``bi_platform_shared.predictive.detector``. The
audit (CRIT-06 + CRIT-14) requires a single source of truth, so the duplicated
predictive heuristics have been removed and replaced with the shared
``is_predictive`` helper.

The task now also natively understands the ``AMBIGUOUS`` label produced by the
hardened classifier in ``llm_intent_client``: ambiguous outputs no longer
cascade into ``invalid_input`` / hard rejections – they bubble up as a
dedicated ``ambiguous`` route so the orchestrator can surface a clarification
prompt to the user.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from bi_platform_shared.predictive.detector import is_predictive

from reasoning_app.llm_intent_client import classify_question
from shared.pipeline_trace import make_attempt
from shared.stage_contract import stage_allows_progress


IntentErrorType = Literal["system", "model", "input", "logic", "unknown"]
IntentActionType = Literal["retry", "stop"]


class IntentClassificationResult(TypedDict):
    status: Literal["success", "failed"]
    is_analytical: bool
    error_type: str
    action_taken: IntentActionType


class IntentClassificationError(Exception):
    """Base exception for intent classification task failures."""


class IntentInputError(IntentClassificationError):
    """Input text cannot be classified."""


class IntentLogicError(IntentClassificationError):
    """Unexpected return shape from existing classifier wrapper."""


class IntentModelOutputError(IntentClassificationError):
    """Classifier output values are malformed."""


@dataclass(frozen=True)
class IntentTaskConfig:
    max_retries: int
    min_confidence: float

    @classmethod
    def from_env(cls) -> "IntentTaskConfig":
        raw = os.getenv("INTENT_CLASSIFICATION_MAX_RETRIES")
        if raw is None:
            max_retries = 2
        else:
            try:
                max_retries = int(raw)
            except ValueError:
                max_retries = 2
        confidence_raw = os.getenv("INTENT_CLASSIFICATION_MIN_CONFIDENCE", "0.60")
        try:
            min_confidence = float(confidence_raw)
        except ValueError:
            min_confidence = 0.60
        return cls(max_retries=max(0, min(max_retries, 3)), min_confidence=max(0.0, min(1.0, min_confidence)))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_logger() -> logging.Logger:
    return logging.getLogger(__name__)


def _log_event(logger: logging.Logger, level: int, message: str, **fields: object) -> None:
    payload = {"timestamp": _utc_now(), **fields}
    logger.log(level, "%s | %s", message, json.dumps(payload, sort_keys=True, default=str))


def classify_intent_task_error(exception: BaseException) -> IntentErrorType:
    if isinstance(exception, IntentInputError):
        return "input"

    if isinstance(exception, IntentModelOutputError):
        return "model"

    if isinstance(exception, IntentLogicError):
        return "logic"

    lowered = str(exception).lower()
    if "timeout" in lowered or "timed out" in lowered or "temporary" in lowered:
        return "system"

    return "unknown"


def _decide_intent_action(
    error_type: IntentErrorType,
    retry_count: int,
    config: IntentTaskConfig,
) -> IntentActionType:
    if error_type in {"input", "logic"}:
        return "stop"
    if error_type in {"system", "model", "unknown"} and retry_count < config.max_retries:
        return "retry"
    return "stop"


def _validate_cleaned_text(cleaned_text: str) -> None:
    if cleaned_text is None:
        raise IntentInputError("Input text is missing.")


_STRONG_ANALYTICAL_PATTERNS = (
    r"\b(show|list|give|display|plot)\b.*\b(total|sum|average|avg|count|number\s+of|max|min|distribution|breakdown|population|revenue|profit|margin|sales|age)\b",
    r"\b(total|sum|average|avg|count|number\s+of|max|min)\b.*\b(by|per|across|for each|in each)\b",
    r"\b(distribution|breakdown)\b.*\b(by|per|across|for each|in each)\b",
    r"\b(how|what)\b.*\b(distribution|distributed|spread|histogram|frequency)\b",
    r"\b(how|what)\b.*\b(impact|relationship|correlation|effect|influence)\b",
    r"\b(top|bottom)\s+\d+\b.*\bby\b",
    r"\bhow many\b.*\b(by|per|across|for each|in each)\b",
)

_ANALYTICAL_KEYWORDS = (
    "total",
    "sum",
    "average",
    "avg",
    "count",
    "number of",
    "max",
    "min",
    "median",
    "mean",
    "population",
    "revenue",
    "profit",
    "margin",
    "sales",
    "age",
    "trend",
    "distribution",
    "distributed",
    "spread",
    "histogram",
    "frequency",
    "impact",
    "relationship",
    "correlation",
    "effect",
    "influence",
    "breakdown",
    "compare",
    "top",
    "bottom",
    "cumulative",
    "accumulated",
    "running total",
)


_GROUP_BY_KEYWORDS = (
    "by",
    "per",
    "across",
    "for each",
    "in each",
    "group by",
)

_STRONG_CONVERSATIONAL_PATTERNS = (
    r"\bhello\b",
    r"\bhi\b",
    r"\bhey\b",
    r"\bhow are you\b",
    r"\bthanks?\b",
    r"\bthank you\b",
    r"\bgood (morning|afternoon|evening)\b",
)

_SKIP_LABELS = {
    "invalid_input",
    "numeric_only_input",
    "noise_input",
    "empty_input",
    "transcription_failure",
    "no_speech_detected",
}

_PREDICTIVE_LABELS = {"predictive", "forecast", "forecasting"}


def _normalize_intent_text(text: Any) -> str:
    lowered = str(text or "").strip().lower()
    lowered = re.sub(r"[_-]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered)


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_intent_text(phrase)
    if not normalized_phrase:
        return False
    pattern = r"\b" + re.escape(normalized_phrase).replace(r"\ ", r"\s+") + r"\b"
    return bool(re.search(pattern, text))


def _detect_rule_based_analytical(text: str) -> dict[str, Any]:
    normalized = _normalize_intent_text(text)
    if not normalized:
        return {
            "is_analytical": False,
            "matched_keywords": [],
            "matched_grouping_keywords": [],
            "matched_patterns": [],
        }

    matched_keywords = [
        keyword
        for keyword in _ANALYTICAL_KEYWORDS
        if _contains_phrase(normalized, keyword)
    ]
    matched_grouping_keywords = [
        keyword
        for keyword in _GROUP_BY_KEYWORDS
        if _contains_phrase(normalized, keyword)
    ]
    matched_patterns = [
        pattern
        for pattern in _STRONG_ANALYTICAL_PATTERNS
        if re.search(pattern, normalized)
    ]

    has_metric_signal = bool(matched_keywords)
    has_group_signal = bool(matched_grouping_keywords)
    is_analytical = bool(
        matched_patterns
        or has_metric_signal
        or (has_group_signal and has_metric_signal)
    )
    return {
        "is_analytical": is_analytical,
        "matched_keywords": matched_keywords,
        "matched_grouping_keywords": matched_grouping_keywords,
        "matched_patterns": matched_patterns,
    }


def _detect_rule_based_predictive(text: str) -> dict[str, Any]:
    """Phase 4 / CRIT-06: delegate to the canonical shared detector.

    The legacy local ``_PREDICTIVE_KEYWORDS`` / ``_PREDICTIVE_PATTERNS`` tables
    were removed because they competed with — and routinely disagreed with —
    the shared detector at ``bi_platform_shared.predictive.detector``. The
    return shape is preserved for the callers that still consume it.
    """

    normalized = _normalize_intent_text(text)
    if not normalized:
        return {"is_predictive": False, "matched_keywords": [], "matched_patterns": []}
    detected = bool(is_predictive(normalized))
    return {
        "is_predictive": detected,
        "matched_keywords": [],
        "matched_patterns": [],
    }


def _enforce_predictive_consistency(payload: dict[str, Any]) -> dict[str, Any]:
    normalized_question_type = _normalize_intent_text(payload.get("question_type"))
    normalized_classification = _normalize_intent_text(payload.get("classification"))
    is_predictive_payload = (
        normalized_question_type in _PREDICTIVE_LABELS
        or normalized_classification in _PREDICTIVE_LABELS
    )
    if is_predictive_payload:
        payload["classification"] = "predictive"
        payload["question_type"] = "predictive"
        payload["requires_forecast"] = True
        payload["route"] = "forecasting"
        if isinstance(payload.get("debug_metadata"), dict):
            payload["debug_metadata"]["route"] = "forecasting"
    return payload


def _is_strong_conversational_signal(text: str) -> bool:
    normalized = _normalize_intent_text(text)
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in _STRONG_CONVERSATIONAL_PATTERNS)


def _extract_classifier_label(classifier_output: Any) -> tuple[str, bool]:
    if not isinstance(classifier_output, dict):
        raise IntentLogicError("Classifier output must be a dictionary.")

    decision_source = _normalize_intent_text(classifier_output.get("decision_source"))
    llm_explicit_flag = bool(classifier_output.get("llm_explicit_decision", False))

    classification_candidates = [
        classifier_output.get("classification"),
        classifier_output.get("question_type"),
        classifier_output.get("intent_type"),
    ]
    for candidate in classification_candidates:
        normalized = _normalize_intent_text(candidate)
        if normalized == "analytical":
            return "analytical", bool(llm_explicit_flag or decision_source == "llm_explicit")
        if normalized in _PREDICTIVE_LABELS:
            return "predictive", bool(llm_explicit_flag or decision_source == "llm_explicit")
        if normalized in {"conversational", "informational", "information", "non_analytical", "non-analytical"}:
            return "conversational", bool(llm_explicit_flag or decision_source == "llm_explicit")
        if normalized == "ambiguous":
            return "ambiguous", bool(llm_explicit_flag or decision_source == "llm_explicit")

    needs_sql = classifier_output.get("needs_sql")
    if isinstance(needs_sql, bool):
        if bool(classifier_output.get("requires_forecast", False)):
            return "predictive", False
        return ("analytical" if needs_sql else "conversational"), False

    raise IntentModelOutputError("Classifier output is missing an interpretable label.")


def _log_intent_detection_summary(
    *,
    logger: logging.Logger,
    input_text: str,
    rule_based_detected: bool,
    llm_label: str,
    llm_source: str,
    final_label: str,
) -> None:
    _log_event(
        logger,
        logging.INFO,
        "[Intent Detection] Decision",
        input_text=input_text[:200],
        rule_based="SUCCESS" if rule_based_detected else "FAILED",
        llm=llm_label or "SKIPPED",
        llm_source=llm_source or "n/a",
        final=final_label,
    )


def run_intent_classification(
    cleaned_text: str,
    raw_text: str | None = None,
    *,
    source: str = "text",
    transcription_status: str | None = None,
) -> dict:
    """Always-on LLM intent classification with fail-safe fallback.

    Phase 4 / CRIT-06 contract:
    - The classifier never raises; failures and low-confidence outputs come
      back as ``label == AMBIGUOUS`` and are routed to a clarification step.
    - Predictive consistency is enforced via the shared
      ``bi_platform_shared.predictive.detector.is_predictive`` so the LLM and
      rules agree on what a forecast question looks like.
    - The legacy ``invalid_input`` / ``rejected`` shapes are preserved for
      hard signals (empty text, numeric-only noise, conversational chit-chat).
    """
    logger = _get_logger()
    config = IntentTaskConfig.from_env()
    stage_started_at = _utc_now()
    stage_started_perf = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    normalized_cleaned_text = re.sub(r"[^\S\r\n]+", " ", str(cleaned_text or "").strip())
    _validate_cleaned_text(normalized_cleaned_text)
    llm_started_perf = time.perf_counter()
    classifier_output = classify_question(normalized_cleaned_text)
    llm_duration_ms = int((time.perf_counter() - llm_started_perf) * 1000)

    category_type = str(classifier_output.get("type", "") or classifier_output.get("label", "")).strip().upper()
    classification = str(classifier_output.get("classification", "")).strip().lower()
    confidence = float(classifier_output.get("confidence", 0.0) or 0.0)
    reasoning = str(classifier_output.get("reasoning", "")).strip() or "No reasoning provided."

    # Sync the deterministic predictive detector with the LLM verdict so we
    # never disagree about whether a question is a forecast.
    if (
        classification not in {"predictive", "conversational", "invalid_input", "ambiguous"}
        and is_predictive(normalized_cleaned_text)
    ):
        classification = "predictive"
        category_type = "PREDICTIVE"

    if classification not in {"analytical", "predictive", "conversational", "invalid_input", "ambiguous"}:
        if category_type == "AMBIGUOUS":
            classification = "ambiguous"
        elif category_type == "PREDICTIVE":
            classification = "predictive"
        elif category_type == "ANALYTICAL":
            classification = "analytical"
        elif category_type == "NON_DATA":
            classification = "conversational"
        elif category_type == "INVALID":
            classification = "invalid_input"
        else:
            classification = "ambiguous"
            category_type = "AMBIGUOUS"
            reasoning = "Classifier output did not contain a valid classification."

    if category_type not in {"ANALYTICAL", "PREDICTIVE", "NON_DATA", "INVALID", "AMBIGUOUS"}:
        category_type = (
            "PREDICTIVE"
            if classification == "predictive"
            else (
                "ANALYTICAL"
                if classification == "analytical"
                else (
                    "AMBIGUOUS"
                    if classification == "ambiguous"
                    else ("INVALID" if classification == "invalid_input" else "NON_DATA")
                )
            )
        )

    route = (
        "forecasting"
        if classification == "predictive"
        else (
            "analytical"
            if classification == "analytical"
            else (
                "ambiguous"
                if classification == "ambiguous"
                else ("invalid" if classification == "invalid_input" else "stop")
            )
        )
    )
    classification_source = str(classifier_output.get("decision_source") or "llm_intent_classifier")
    is_ambiguous = classification == "ambiguous"
    is_rejected = classification in {"conversational", "invalid_input"}
    is_degraded = classification_source in {"deterministic_rule_input_guard", "rule_input_guard"} and classification in {"analytical", "predictive"}
    attempts.append(
        make_attempt(
            attempt_number=1,
            input_payload={
                "raw_text": raw_text,
                "cleaned_text": normalized_cleaned_text,
                "source": source,
                "transcription_status": transcription_status,
            },
            output_payload=classifier_output,
            success=not is_degraded,
            retry_triggered=False,
            model_or_method_used="llm_intent_classifier",
            duration_ms=llm_duration_ms,
            validation_result={
                "is_valid": not is_rejected and not is_ambiguous,
                "type": category_type,
                "classification": classification,
                "degraded": is_degraded,
                "rejected": is_rejected,
                "ambiguous": is_ambiguous,
            },
        )
    )

    _log_event(
        logger,
        logging.INFO,
        "Intent classification completed",
        type=category_type,
        classification=classification,
        confidence=confidence,
        reasoning=reasoning,
        route=route,
        decision_source=classification_source,
    )
    finished_at = _utc_now()
    error_type = "none"
    if is_ambiguous:
        error_type = "ambiguous"
    elif is_rejected:
        error_type = "input"

    status = "success"
    if is_ambiguous:
        status = "ambiguous"
    elif is_rejected:
        status = "rejected"
    elif is_degraded:
        status = "degraded"

    warnings: list[dict[str, str]] = []
    if is_degraded:
        warnings.append(
            {"type": "rule_based_classifier", "message": "Rule-based classification used without LLM confirmation."}
        )
    if is_ambiguous:
        warnings.append(
            {"type": "ambiguous_intent", "message": reasoning}
        )

    errors: list[dict[str, str]] = []
    if is_rejected:
        errors.append({"type": "classification_rejected", "message": reasoning})

    return _enforce_predictive_consistency({
        "status": status,
        "degraded": is_degraded,
        "is_analytical": classification in {"analytical", "predictive"},
        "is_ambiguous": is_ambiguous,
        "error_type": error_type,
        "action_taken": "stop",
        "route": route,
        "classification": classification,
        "classification_type": category_type,
        "classification_reason": reasoning,
        "confidence": max(0.0, min(1.0, confidence)),
        "question_type": classification,
        "requires_forecast": classification == "predictive",
        "raw_classifier_output": classifier_output,
        "raw_model_response": str(
            classifier_output.get("raw_model_response")
            or classifier_output.get("llm_raw_response")
            or ""
        ),
        "evidence_tokens": list(classifier_output.get("evidence_tokens") or []),
        "attempts": attempts,
        "attempts_count": len(attempts),
        "started_at": stage_started_at,
        "finished_at": finished_at,
        "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
        "warnings": warnings,
        "errors": errors,
        "debug_metadata": {
            "route": route,
            "classification_source": classification_source,
            "type": category_type,
            "reasoning": reasoning,
            "raw_model_response": str(
                classifier_output.get("raw_model_response")
                or classifier_output.get("llm_raw_response")
                or ""
            ),
        },
    })


def _attach_fn_compat(func):
    """
    Keep compatibility for existing call sites/tests that use Prefect's `.fn`.
    """
    setattr(func, "fn", func)
    return func


@_attach_fn_compat
def intent_classification_task(cleaned_text: str) -> dict:
    return run_intent_classification(cleaned_text=cleaned_text)


def route_intent_classification(
    cleaned_text: str,
    classification_result: dict[str, Any],
    user_id: str = "",
) -> dict[str, Any]:
    """
    Decision-based routing after intent classification.

    Phase 4 / CRIT-06: ambiguous results no longer fall through as
    ``invalid_input``; they are routed to a dedicated ``ambiguous`` next-step
    so the orchestrator can surface a clarification prompt.
    """
    classification_label = str(classification_result.get("classification", "")).strip().lower()
    classification_type = str(classification_result.get("classification_type", "")).strip().upper()

    if classification_label == "ambiguous" or classification_type == "AMBIGUOUS":
        reason = (
            classification_result.get("classification_reason")
            or "The question is data-related but too vague to classify."
        )
        return {
            "status": "ambiguous",
            "next_step": "clarify",
            "message": (
                "We could not determine whether this is an analytical or predictive question. "
                f"{reason}"
            ),
            "reason": "ambiguous_intent",
            "classification": classification_result,
        }

    if not stage_allows_progress(
        classification_result.get("status"),
        degraded=bool(classification_result.get("degraded")),
    ):
        reason = (
            classification_result.get("classification_reason")
            or classification_result.get("reasoning")
            or "classification_failed"
        )
        return {
            "status": "rejected",
            "next_step": "stop",
            "message": f"Classification did not produce a safe analytical or predictive decision: {reason}.",
            "reason": "classification_failed",
            "classification": classification_result,
        }

    if classification_type == "INVALID" or classification_label == "invalid_input":
        reason = classification_result.get("classification_reason") or "invalid_input"
        return {
            "status": "rejected",
            "next_step": "stop",
            "message": f"The request is invalid for analysis: {reason}.",
            "reason": "invalid_input",
            "classification": classification_result,
        }

    if classification_type == "NON_DATA" or classification_label == "conversational":
        return {
            "status": "rejected",
            "next_step": "stop",
            "message": "The question is not data-related and cannot be processed.",
            "reason": "non_analytical",
            "classification": classification_result,
        }

    normalized_question_type = str(classification_result.get("question_type", "")).strip().lower()
    requires_forecast = bool(classification_result.get("requires_forecast", False))
    predictive_state = (
        classification_label in _PREDICTIVE_LABELS
        or normalized_question_type in _PREDICTIVE_LABELS
        or is_predictive(cleaned_text)
    )
    if predictive_state:
        requires_forecast = True
        classification_result["requires_forecast"] = True
        classification_result["route"] = "forecasting"
        classification_result["classification"] = "predictive"
        classification_result["question_type"] = "predictive"

    explicit_route = str(classification_result.get("route", "")).strip().lower()
    if explicit_route in {"forecasting", "analytical"}:
        route = explicit_route
    else:
        route = (
            "forecasting" if predictive_state or requires_forecast else "analytical"
        )
    return {
        "status": "success",
        "legacy_status": "routed",
        "next_stage": "preprocessing_high",
        "route": route,
        "next_step": "forecasting" if route == "forecasting" else "metabase",
        "module_path": "services/ai-service/preprocessing_high/",
        "classification": classification_result,
        "payload": {
            "cleaned_text": cleaned_text,
            "user_id": str(user_id or "").strip(),
            "route": route,
        },
    }

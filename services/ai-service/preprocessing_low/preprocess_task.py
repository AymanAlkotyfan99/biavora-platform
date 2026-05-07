from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone

from preprocessing_low.cleaners import _rule_based_clean_with_changes
from preprocessing_low.error_handler import (
    _decide_preprocess_action,
    classify_preprocess_error,
)
from preprocessing_low.llm_client import _call_ollama_preprocessor, _call_ollama_prompt
from preprocessing_low.schemas import (
    TextPreprocessConfig,
    build_preprocess_failed_result,
    build_preprocess_success_result,
)
from preprocessing_low.spell_corrector import apply_spelling_correction, detect_spelling_changes
from shared.confidence import preprocessing_low_confidence
from shared.ollama_env import ollama_retry_backoff_seconds
from shared.pipeline_trace import make_attempt

_PROTECTED_ANALYTICAL_KEYWORDS = {
    "highest",
    "lowest",
    "top",
    "bottom",
    "best",
    "worst",
    "maximum",
    "minimum",
    "trend",
    "relationship",
    "compare",
    "forecast",
    "predict",
    "most",
    "least",
}
_PROTECTED_ANALYTICAL_PHRASES = {"over time", "per day", "per week"}
_SNAKE_CASE_PATTERN = re.compile(r"^[a-zA-Z]+(?:_[a-zA-Z0-9]+)+$")


# Phase 13 / GAP-02 — multi-language support.
#
# The audit calls out that the classifier currently uses one prompt for
# every language. Step zero is to MARK the detected language so downstream
# stages can branch (load the right prompt template, the right stop-word
# list, etc.) and the trace can attribute classification confidence to a
# language. The detector below is intentionally heuristic and dependency-
# free: it inspects the script of the input string. Heavier libraries
# (``langdetect``, ``fasttext``) can be plugged in later without changing
# the call site contract.

_ARABIC_RANGE = (0x0600, 0x06FF)
_HEBREW_RANGE = (0x0590, 0x05FF)
_CYRILLIC_RANGE = (0x0400, 0x04FF)
_CJK_RANGES = ((0x4E00, 0x9FFF), (0x3040, 0x30FF), (0xAC00, 0xD7AF))


def detect_language_simple(text: str) -> str:
    """Return a coarse-grained language tag for ``text``.

    Returns one of ``ar``, ``he``, ``ru``, ``zh``, ``ja``, ``ko`` or ``en``
    (the default). Phase 13 / GAP-02: this is the seed of multi-language
    routing; richer detection can replace the body without changing the
    call-site contract.
    """

    sample = (text or "").strip()
    if not sample:
        return "en"

    arabic_chars = 0
    hebrew_chars = 0
    cyrillic_chars = 0
    cjk_chars = 0
    for ch in sample[:512]:
        codepoint = ord(ch)
        if _ARABIC_RANGE[0] <= codepoint <= _ARABIC_RANGE[1]:
            arabic_chars += 1
        elif _HEBREW_RANGE[0] <= codepoint <= _HEBREW_RANGE[1]:
            hebrew_chars += 1
        elif _CYRILLIC_RANGE[0] <= codepoint <= _CYRILLIC_RANGE[1]:
            cyrillic_chars += 1
        elif any(low <= codepoint <= high for low, high in _CJK_RANGES):
            cjk_chars += 1

    if arabic_chars > 0 and arabic_chars >= len(sample) // 4:
        return "ar"
    if hebrew_chars > 0 and hebrew_chars >= len(sample) // 4:
        return "he"
    if cyrillic_chars > 0 and cyrillic_chars >= len(sample) // 4:
        return "ru"
    if cjk_chars > 0 and cjk_chars >= len(sample) // 4:
        return "zh"
    return "en"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_logger() -> logging.Logger:
    return logging.getLogger(__name__)


def _log_event(logger: logging.Logger, level: int, message: str, **fields: object) -> None:
    payload = {"timestamp": _utc_now(), **fields}
    logger.log(level, "%s | %s", message, json.dumps(payload, sort_keys=True, default=str))


def _attach_spelling_trace_fields(
    payload: dict,
    *,
    original_text: str,
    spelling_corrected_text: str,
    spelling_changes: list[dict[str, str]],
    has_spelling_correction: bool,
    removed_filler_words: list[str],
    correction_source: str,
) -> None:
    payload["original_text"] = original_text
    payload["spelling_corrected_text"] = spelling_corrected_text
    payload["spelling_changes"] = spelling_changes
    payload["has_spelling_correction"] = has_spelling_correction
    payload["removed_filler_words"] = removed_filler_words
    payload["changes"] = {
        "spelling_corrections": spelling_changes,
        "removed_filler_words": removed_filler_words,
    }
    payload["correction_source"] = correction_source


def _extract_removed_filler_words(detected_changes: list[dict]) -> list[str]:
    removed: list[str] = []
    for change in detected_changes:
        if not isinstance(change, dict):
            continue
        if str(change.get("type", "")).strip() != "removed_filler_words":
            continue
        before = str(change.get("before", "")).strip()
        if not before:
            continue
        for token in [item.strip() for item in before.split(",")]:
            if token:
                removed.append(token)
    return removed


def _change_type_labels(detected_changes: list[dict]) -> list[str]:
    labels: list[str] = []
    for change in detected_changes:
        if not isinstance(change, dict):
            continue
        label = str(change.get("type", "")).strip()
        if not label:
            continue
        if label not in labels:
            labels.append(label)
    return labels


def _token_set(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"\b\w+\b", str(text or ""), flags=re.UNICODE)}


def _has_protected_loss(before: str, after: str) -> bool:
    before_tokens = _token_set(before)
    after_tokens = _token_set(after)
    for keyword in _PROTECTED_ANALYTICAL_KEYWORDS:
        if keyword in before_tokens and keyword not in after_tokens:
            return True
    before_lower = str(before or "").lower()
    after_lower = str(after or "").lower()
    for phrase in _PROTECTED_ANALYTICAL_PHRASES:
        if phrase in before_lower and phrase not in after_lower:
            return True
    return False


def _snake_case_tokens(text: str) -> list[str]:
    return [
        token
        for token in str(text or "").split()
        if _SNAKE_CASE_PATTERN.fullmatch(token.strip(".,!?;:()[]{}\"'"))
    ]


def _snake_case_changed(before: str, after: str) -> bool:
    before_tokens = _snake_case_tokens(before)
    after_tokens = _snake_case_tokens(after)
    if len(before_tokens) != len(after_tokens):
        return True
    return any(left != right for left, right in zip(before_tokens, after_tokens))


def run_preprocess_text(text: str) -> dict:
    """
    Runtime entrypoint for language-agnostic text preprocessing.

    Phase 13 / GAP-02: the detected language tag is recorded on every
    payload (success / degraded / failed) so downstream stages can branch
    and the trace can attribute classification confidence to a language.
    """

    logger = _get_logger()
    config = TextPreprocessConfig.from_env()
    retry_count = 0
    stage_started_at = _utc_now()
    stage_started_perf = time.perf_counter()
    attempts: list[dict] = []
    source_text = text if isinstance(text, str) else str(text or "")
    detected_language = detect_language_simple(source_text)
    spelling_corrected_text = source_text
    spelling_changes: list[dict[str, str]] = []
    has_spelling_correction = False
    correction_source = "rule_based"
    removed_filler_words: list[str] = []

    try:
        rule_started_perf = time.perf_counter()
        rule_cleaned_text, detected_changes, input_flags = _rule_based_clean_with_changes(source_text)
        removed_filler_words = _extract_removed_filler_words(detected_changes)
        rule_duration_ms = int((time.perf_counter() - rule_started_perf) * 1000)
        rule_validation = {
            "is_valid": True,
            "flags": input_flags,
            "change_count": len(detected_changes),
            "removed_filler_words": removed_filler_words,
        }
        attempts.append(
            make_attempt(
                attempt_number=1,
                input_payload={"text": source_text},
                output_payload={
                    "cleaned_text": rule_cleaned_text,
                    "detected_changes": detected_changes,
                    "removed_filler_words": removed_filler_words,
                },
                success=True,
                retry_triggered=False,
                model_or_method_used="rule_based_cleaner",
                duration_ms=rule_duration_ms,
                validation_result=rule_validation,
            )
        )
        spelling_corrected_text = rule_cleaned_text
        spelling_changes = detect_spelling_changes(source_text, rule_cleaned_text)
        has_spelling_correction = bool(spelling_changes)
    except Exception as exc:  # noqa: BLE001
        error_type = classify_preprocess_error(exc)
        finished_at = _utc_now()
        _log_event(
            logger,
            logging.ERROR,
            "Text preprocessing input validation failed",
            error_type=error_type,
            action_taken="stop",
            error=str(exc),
        )
        failure_payload = build_preprocess_failed_result(error_type=error_type, action_taken="stop")
        failure_payload["errors"] = [{"type": error_type, "message": str(exc)}]
        failure_payload["attempts"] = attempts
        failure_payload["attempts_count"] = len(attempts)
        failure_payload["started_at"] = stage_started_at
        failure_payload["finished_at"] = finished_at
        failure_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
        failure_payload["detected_language"] = detected_language
        failure_payload["debug_metadata"] = {"input_chars": len(str(text or "")), "detected_language": detected_language}
        _attach_spelling_trace_fields(
            failure_payload,
            original_text=source_text,
            spelling_corrected_text=spelling_corrected_text,
            spelling_changes=spelling_changes,
            has_spelling_correction=has_spelling_correction,
            removed_filler_words=removed_filler_words,
            correction_source=correction_source,
        )
        failure_payload["debug_metadata"]["correction_source"] = correction_source
        failure_payload["confidence"] = preprocessing_low_confidence(failure_payload)
        return failure_payload

    _log_event(
        logger,
        logging.INFO,
        "Rule-based text preprocessing completed",
        input_chars=len(source_text),
        cleaned_chars=len(rule_cleaned_text),
    )

    # Keep explicit empty/punctuation outcomes observable for downstream input classification.
    if (
        not source_text.strip()
        or rule_cleaned_text == ""
        or bool(input_flags.get("punctuation_only_input"))
        or bool(input_flags.get("numeric_only_input"))
        or bool(input_flags.get("noise_input"))
        or bool(input_flags.get("silence_like_input"))
    ):
        finished_at = _utc_now()
        success_payload = build_preprocess_success_result(cleaned_text=rule_cleaned_text)
        success_payload["detected_changes"] = detected_changes
        success_payload["warnings"] = [
            {
                "type": "empty_after_cleaning",
                "message": "Input was classified as empty, punctuation-only, numeric-only, noise-like, or silence-like during low preprocessing.",
            }
        ]
        success_payload["attempts"] = attempts
        success_payload["attempts_count"] = len(attempts)
        success_payload["started_at"] = stage_started_at
        success_payload["finished_at"] = finished_at
        success_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
        success_payload["detected_language"] = detected_language
        success_payload["debug_metadata"] = {
            "input_chars": len(source_text),
            "cleaned_chars": len(rule_cleaned_text),
            "input_flags": input_flags,
            "correction_source": correction_source,
            "spelling_change_count": len(spelling_changes),
            "removed_filler_words": removed_filler_words,
            "detected_language": detected_language,
            "detected_change_types": _change_type_labels(detected_changes),
        }
        success_payload["detected_change_types"] = _change_type_labels(detected_changes)
        success_payload["removed_filler_words"] = removed_filler_words
        _attach_spelling_trace_fields(
            success_payload,
            original_text=source_text,
            spelling_corrected_text=spelling_corrected_text,
            spelling_changes=spelling_changes,
            has_spelling_correction=has_spelling_correction,
            removed_filler_words=removed_filler_words,
            correction_source=correction_source,
        )
        success_payload["confidence"] = preprocessing_low_confidence(success_payload)
        return success_payload

    while True:
        try:
            llm_started_perf = time.perf_counter()
            llm_input_text = rule_cleaned_text
            cleaned_text = _call_ollama_preprocessor(
                llm_input_text,
                config=config,
                logger=logger,
                log_event=_log_event,
            )
            llm_cleaned_text, llm_changes, llm_flags = _rule_based_clean_with_changes(cleaned_text)
            llm_candidate = llm_cleaned_text or rule_cleaned_text
            llm_guard_rejected = False
            if _has_protected_loss(rule_cleaned_text, llm_candidate):
                llm_guard_rejected = True
            if _snake_case_changed(rule_cleaned_text, llm_candidate):
                llm_guard_rejected = True
            final_cleaned_text = rule_cleaned_text if llm_guard_rejected else llm_candidate
            final_changes = list(detected_changes)
            if not llm_guard_rejected:
                final_changes.extend(llm_changes)
            elif llm_changes:
                final_changes.append(
                    {
                        "type": "llm_post_clean_rejected",
                        "before": cleaned_text,
                        "after": final_cleaned_text,
                    }
                )
            if source_text.strip() and source_text.strip() != final_cleaned_text and not final_changes:
                final_changes.append(
                    {
                        "type": "normalized_text",
                        "before": source_text.strip(),
                        "after": final_cleaned_text,
                    }
                )
            spelling_changes = detect_spelling_changes(source_text, final_cleaned_text)
            has_spelling_correction = bool(spelling_changes)
            spelling_corrected_text = final_cleaned_text
            correction_source = "llm_based" if not llm_guard_rejected else "rule_based"
            spelling_attempt_skipped_reason = ""
            if not has_spelling_correction:
                spelling_result = apply_spelling_correction(
                    final_cleaned_text,
                    llm_client=lambda prompt: _call_ollama_prompt(
                        prompt,
                        config=config,
                        logger=logger,
                        log_event=_log_event,
                        purpose="preprocessing_low_spelling",
                    ),
                )
                spelling_attempt_skipped_reason = spelling_result.skipped_reason
                if spelling_result.has_correction:
                    pre_spell_text = final_cleaned_text
                    final_cleaned_text = spelling_result.text
                    spelling_corrected_text = spelling_result.text
                    spelling_changes = spelling_result.changes
                    has_spelling_correction = True
                    correction_source = "llm_based"
                    final_changes.append(
                        {
                            "type": "llm_spelling_pass",
                            "before": pre_spell_text,
                            "after": final_cleaned_text,
                        }
                    )
            if has_spelling_correction:
                final_changes.extend(
                    {
                        "type": "corrected_spelling_llm",
                        "before": change["original"],
                        "after": change["corrected"],
                    }
                    for change in spelling_changes
                )
            removed_filler_words = _extract_removed_filler_words(final_changes)
            llm_duration_ms = int((time.perf_counter() - llm_started_perf) * 1000)
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"text": llm_input_text},
                    output_payload={
                        "cleaned_text": final_cleaned_text,
                        "spelling_corrected_text": spelling_corrected_text,
                        "spelling_changes": spelling_changes,
                        "has_spelling_correction": has_spelling_correction,
                        "removed_filler_words": removed_filler_words,
                        "correction_source": correction_source,
                        "llm_raw_output": cleaned_text,
                        "post_llm_changes": llm_changes,
                        "llm_guard_rejected": llm_guard_rejected,
                    },
                    success=True,
                    retry_triggered=False,
                    model_or_method_used=f"ollama:{config.ollama_model}",
                    duration_ms=llm_duration_ms,
                    validation_result={"is_valid": bool(final_cleaned_text.strip()), "flags": llm_flags},
                )
            )
            finished_at = _utc_now()
            success_payload = build_preprocess_success_result(cleaned_text=final_cleaned_text)
            success_payload["detected_changes"] = final_changes
            success_payload["attempts"] = attempts
            success_payload["attempts_count"] = len(attempts)
            success_payload["started_at"] = stage_started_at
            success_payload["finished_at"] = finished_at
            success_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            success_payload["detected_language"] = detected_language
            success_payload["debug_metadata"] = {
                "input_chars": len(source_text),
                "rule_cleaned_chars": len(rule_cleaned_text),
                "final_cleaned_chars": len(final_cleaned_text),
                "input_flags": input_flags,
                "llm_output_flags": llm_flags,
                "llm_guard_rejected": llm_guard_rejected,
                "spelling_pass_skipped_reason": spelling_attempt_skipped_reason,
                "correction_source": correction_source,
                "spelling_change_count": len(spelling_changes),
                "removed_filler_words": removed_filler_words,
                "detected_change_types": _change_type_labels(final_changes),
                "detected_language": detected_language,
            }
            success_payload["detected_change_types"] = _change_type_labels(final_changes)
            success_payload["removed_filler_words"] = removed_filler_words
            _attach_spelling_trace_fields(
                success_payload,
                original_text=source_text,
                spelling_corrected_text=spelling_corrected_text,
                spelling_changes=spelling_changes,
                has_spelling_correction=has_spelling_correction,
                removed_filler_words=removed_filler_words,
                correction_source=correction_source,
            )
            success_payload["confidence"] = preprocessing_low_confidence(success_payload)
            return success_payload
        except Exception as exc:  # noqa: BLE001
            error_type = classify_preprocess_error(exc)
            action_taken = _decide_preprocess_action(
                error_type=error_type,
                retry_count=retry_count,
                config=config,
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"text": rule_cleaned_text},
                    output_payload={},
                    success=False,
                    retry_triggered=action_taken == "retry",
                    retry_reason=str(exc) if action_taken == "retry" else "",
                    model_or_method_used=f"ollama:{config.ollama_model}",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type=error_type,
                    error_message=str(exc),
                )
            )
            _log_event(
                logger,
                logging.ERROR,
                "LLM-based text preprocessing failed",
                error_type=error_type,
                action_taken=action_taken,
                retry_count=retry_count,
                error=str(exc),
            )

            if action_taken == "retry":
                backoff = ollama_retry_backoff_seconds()
                if backoff > 0:
                    time.sleep(backoff)
                retry_count += 1
                continue

            if error_type != "input" and bool(rule_cleaned_text.strip()):
                spelling_corrected_text = rule_cleaned_text
                correction_source = "rule_based_fallback"
                finished_at = _utc_now()
                fallback_payload = build_preprocess_success_result(cleaned_text=rule_cleaned_text)
                fallback_payload["detected_changes"] = detected_changes
                fallback_payload["attempts"] = attempts
                fallback_payload["attempts_count"] = len(attempts)
                fallback_payload["started_at"] = stage_started_at
                fallback_payload["finished_at"] = finished_at
                fallback_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
                fallback_payload["warnings"] = [
                    {
                        "type": "llm_preprocessing_fallback",
                        "message": (
                            "Ollama preprocessing failed; continued with deterministic "
                            "rule-based cleaned text."
                        ),
                    }
                ]
                fallback_payload["errors"] = []
                fallback_payload["detected_language"] = detected_language
                fallback_payload["debug_metadata"] = {
                    "input_chars": len(source_text),
                    "rule_cleaned_chars": len(rule_cleaned_text),
                    "input_flags": input_flags,
                    "llm_fallback_used": True,
                    "llm_fallback_error_type": error_type,
                    "llm_fallback_error": str(exc),
                    "correction_source": correction_source,
                    "spelling_change_count": len(spelling_changes),
                    "removed_filler_words": removed_filler_words,
                    "detected_language": detected_language,
                    "detected_change_types": _change_type_labels(detected_changes),
                }
                fallback_payload["detected_change_types"] = _change_type_labels(detected_changes)
                fallback_payload["removed_filler_words"] = removed_filler_words
                _attach_spelling_trace_fields(
                    fallback_payload,
                    original_text=source_text,
                    spelling_corrected_text=spelling_corrected_text,
                    spelling_changes=spelling_changes,
                    has_spelling_correction=has_spelling_correction,
                    removed_filler_words=removed_filler_words,
                    correction_source=correction_source,
                )
                _log_event(
                    logger,
                    logging.WARNING,
                    "LLM preprocessing fallback activated",
                    fallback_error_type=error_type,
                    fallback_error=str(exc),
                    cleaned_chars=len(rule_cleaned_text),
                )
                fallback_payload["degraded"] = True
                fallback_payload["degradation_reason"] = "llm_preprocessing_fallback"
                fallback_payload["status"] = "degraded"
                fallback_payload["confidence"] = preprocessing_low_confidence(fallback_payload)
                return fallback_payload

            finished_at = _utc_now()
            failed_payload = build_preprocess_failed_result(
                error_type=error_type,
                action_taken=action_taken,
            )
            failed_payload["detected_changes"] = detected_changes
            failed_payload["errors"] = [{"type": error_type, "message": str(exc)}]
            failed_payload["attempts"] = attempts
            failed_payload["attempts_count"] = len(attempts)
            failed_payload["started_at"] = stage_started_at
            failed_payload["finished_at"] = finished_at
            failed_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            failed_payload["debug_metadata"] = {
                "input_chars": len(source_text),
                "rule_cleaned_chars": len(rule_cleaned_text),
                "input_flags": input_flags,
                "correction_source": correction_source,
                "spelling_change_count": len(spelling_changes),
                "removed_filler_words": removed_filler_words,
                "detected_change_types": _change_type_labels(detected_changes),
            }
            failed_payload["detected_change_types"] = _change_type_labels(detected_changes)
            failed_payload["removed_filler_words"] = removed_filler_words
            _attach_spelling_trace_fields(
                failed_payload,
                original_text=source_text,
                spelling_corrected_text=spelling_corrected_text,
                spelling_changes=spelling_changes,
                has_spelling_correction=has_spelling_correction,
                removed_filler_words=removed_filler_words,
                correction_source=correction_source,
            )
            failed_payload["confidence"] = preprocessing_low_confidence(failed_payload)
            return failed_payload


def _attach_fn_compat(func):
    """
    Keep compatibility for existing call sites/tests that use Prefect's `.fn`.
    """
    setattr(func, "fn", func)
    return func


@_attach_fn_compat
def preprocess_text_task(text: str) -> dict:
    return run_preprocess_text(text)

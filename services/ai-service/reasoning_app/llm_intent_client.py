"""LLM-backed intent classifier (Phase 4 / CRIT-06).

The previous implementation made the 1B Ollama model the only arbiter and
silently returned ``INVALID`` whenever the LLM failed. The audit (Section 5.6
and CRIT-06) requires:

1. **Deterministic pre-check before the LLM** – uses
   ``bi_platform_shared.predictive.detector.is_predictive`` for forecast-style
   questions and a NON_DATA pattern for trivial chit-chat. If the pre-check
   fires we never call the LLM.

2. **Configurable model** – the model is read from
   ``OLLAMA_CLASSIFICATION_MODEL`` (with the legacy
   ``INTENT_CLASSIFIER_OLLAMA_MODEL`` retained as a fallback so existing
   deployments do not break). The default is intentionally NOT the historic
   ``gemma3:1b`` because it was the root cause of CRIT-06.

3. **JSON-schema-constrained output** – the prompt asks for the canonical
   shape ``{label, confidence, reasoning, evidence_tokens}`` and we reject any
   LLM payload that does not match the four-field contract. Anything else is
   downgraded to ``AMBIGUOUS`` instead of bubbling up as ``INVALID``.

4. **Ambiguous handling** – low-confidence (< 0.6) results return label
   ``AMBIGUOUS`` so the orchestrator can ask the user to rephrase rather than
   silently rejecting.

5. **Circuit breaker** – the call goes through the shared HTTP client, which
   already implements the per-host circuit breaker and request-id /
   trace-context propagation. When the breaker is open we return
   ``AMBIGUOUS`` instead of raising.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from bi_platform_shared.http import (
    CircuitBreakerOpenError,
    HttpClientError,
    get_default_client,
)
from bi_platform_shared.predictive.detector import is_predictive

from shared.input_classifier import classify_input
from shared.bi_llm_core_policy import STRICT_BI_LLM_CORE_POLICY

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


_DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_CLASSIFICATION_DEFAULT_MODEL", "gemma3:1b")
_DEFAULT_MIN_CONFIDENCE = 0.6
_VALID_LABELS = ("ANALYTICAL", "PREDICTIVE", "NON_DATA", "INVALID", "AMBIGUOUS")

# Patterns that classify an input as non-data without an LLM call. These are
# deliberately conservative: they fire only on canonical greetings / chit-chat
# so we never block a real BI question.
_NON_DATA_PATTERNS = (
    re.compile(r"^\s*(hi|hello|hey|yo|hola|salut|hii|sup)\b", re.IGNORECASE),
    re.compile(r"\bhow\s+are\s+you\b", re.IGNORECASE),
    re.compile(r"\bgood\s+(morning|afternoon|evening|night)\b", re.IGNORECASE),
    re.compile(r"^\s*(thanks|thank\s+you|merci|cheers)\b", re.IGNORECASE),
    re.compile(r"^\s*(bye|goodbye|see\s+ya|see\s+you)\b", re.IGNORECASE),
    re.compile(r"^\s*(ok|okay|cool|nice|great)\s*[!.?]*\s*$", re.IGNORECASE),
)

# Deterministic analytical fallback used when the classifier model is
# unavailable (for example Ollama model-not-found). This is intentionally
# conservative and runs only after NON_DATA/PREDICTIVE guards.
_ANALYTICAL_PATTERNS = (
    re.compile(r"\b(compare|comparison|versus|vs)\b", re.IGNORECASE),
    re.compile(r"\b(total|sum|average|avg|count|number of|max|min)\b", re.IGNORECASE),
    re.compile(r"\b(trend|over time|by month|by year|by day)\b", re.IGNORECASE),
    re.compile(r"\b(group by|breakdown|distribution|top\s+\d+|bottom\s+\d+)\b", re.IGNORECASE),
    re.compile(r"\b(sales|revenue|profit|customers|orders|conversion)\b", re.IGNORECASE),
)


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _get_ollama_url() -> str:
    ollama_host = str(os.getenv("OLLAMA_HOST", "http://localhost:11434")).strip() or "http://localhost:11434"
    default_url = f"{ollama_host.rstrip('/')}/api/generate"
    return str(os.getenv("INTENT_CLASSIFIER_OLLAMA_URL", default_url)).strip() or default_url


def _get_ollama_model() -> str:
    """Resolve the classification model.

    Order of precedence (audit Phase 4 / CRIT-06):
    1. ``OLLAMA_CLASSIFICATION_MODEL`` (canonical, audit-mandated env var).
    2. ``INTENT_CLASSIFIER_OLLAMA_MODEL`` (legacy alias, kept for backwards
       compatibility while operators migrate their .env files).
    3. Hard-coded default (currently a 4B instruct model, *not* the deprecated
       1B classifier).
    """

    canonical = str(os.getenv("OLLAMA_CLASSIFICATION_MODEL", "")).strip()
    if canonical:
        return canonical
    legacy = str(os.getenv("INTENT_CLASSIFIER_OLLAMA_MODEL", "")).strip()
    if legacy:
        return legacy
    return _DEFAULT_OLLAMA_MODEL


def _get_timeout_seconds() -> int:
    from shared.ollama_env import global_ollama_read_timeout_seconds

    fallback = int(global_ollama_read_timeout_seconds())
    raw_value = str(
        os.getenv("OLLAMA_CLASSIFICATION_TIMEOUT", os.getenv("INTENT_CLASSIFIER_TIMEOUT_SECONDS", str(fallback)))
    ).strip()
    try:
        parsed = int(float(raw_value))
    except ValueError:
        parsed = fallback
    return max(1, parsed)


def _get_min_confidence() -> float:
    raw_value = str(os.getenv("INTENT_CLASSIFICATION_MIN_CONFIDENCE", _DEFAULT_MIN_CONFIDENCE)).strip()
    try:
        parsed = float(raw_value)
    except ValueError:
        parsed = _DEFAULT_MIN_CONFIDENCE
    return max(0.0, min(1.0, parsed))


# ---------------------------------------------------------------------------
# Decision-payload helpers
# ---------------------------------------------------------------------------


def _classification_for_label(label: str) -> str:
    label_upper = (label or "").strip().upper()
    if label_upper == "PREDICTIVE":
        return "predictive"
    if label_upper == "ANALYTICAL":
        return "analytical"
    if label_upper == "NON_DATA":
        return "conversational"
    if label_upper == "INVALID":
        return "invalid_input"
    if label_upper == "AMBIGUOUS":
        return "ambiguous"
    return "ambiguous"


def _build_decision_payload(
    *,
    label: str,
    confidence: float,
    reasoning: str,
    decision_source: str,
    evidence_tokens: Optional[List[str]] = None,
    llm_raw_response: str = "",
    llm_error: str = "",
    llm_explicit_decision: bool = True,
) -> Dict[str, Any]:
    label_upper = (label or "").strip().upper() or "AMBIGUOUS"
    if label_upper not in _VALID_LABELS:
        label_upper = "AMBIGUOUS"
    classification = _classification_for_label(label_upper)
    confidence_clamped = max(0.0, min(1.0, float(confidence or 0.0)))

    needs_sql = classification in {"analytical", "predictive"}
    if classification == "predictive":
        route = "forecasting"
    elif classification == "analytical":
        route = "analytical"
    elif classification == "ambiguous":
        route = "ambiguous"
    elif classification == "invalid_input":
        route = "invalid"
    else:
        route = "stop"

    return {
        # Canonical (Phase 4) fields ------------------------------------------------
        "label": label_upper,
        "confidence": confidence_clamped,
        "reasoning": str(reasoning or "").strip() or "No reasoning provided.",
        "evidence_tokens": [str(t).strip() for t in (evidence_tokens or []) if str(t).strip()],
        # Backwards-compatible fields used by intent_classification_task ------------
        "type": label_upper if label_upper != "AMBIGUOUS" else "AMBIGUOUS",
        "classification": classification,
        "question_type": classification if classification in {"analytical", "predictive", "ambiguous", "invalid_input"} else "conversational",
        "needs_sql": needs_sql and classification != "ambiguous",
        "needs_chart": needs_sql and classification != "ambiguous",
        "requires_forecast": classification == "predictive",
        "route": route,
        "decision_source": decision_source,
        "llm_raw_response": llm_raw_response,
        "raw_model_response": llm_raw_response,
        "llm_error": llm_error,
        "llm_explicit_decision": bool(llm_explicit_decision),
    }


# ---------------------------------------------------------------------------
# Deterministic pre-check
# ---------------------------------------------------------------------------


def _matches_non_data(question: str) -> bool:
    if not question:
        return False
    return any(p.search(question) for p in _NON_DATA_PATTERNS)


def _matches_analytical_signal(question: str) -> bool:
    if not question:
        return False
    normalized = re.sub(r"\s+", " ", str(question).strip().lower())
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _ANALYTICAL_PATTERNS)


def _deterministic_pre_check(question: str) -> Optional[Dict[str, Any]]:
    """Return a decision payload when the question can be classified without
    consulting the LLM. ``None`` means the LLM must run."""

    if not question or not question.strip():
        return _build_decision_payload(
            label="INVALID",
            confidence=1.0,
            reasoning="Empty input cannot be classified.",
            decision_source="deterministic_empty_input",
            llm_explicit_decision=False,
        )

    # Non-data chit-chat (greetings, thanks, ...).
    if _matches_non_data(question):
        return _build_decision_payload(
            label="NON_DATA",
            confidence=0.99,
            reasoning="Question matches a non-data conversational pattern.",
            decision_source="deterministic_non_data_pattern",
            llm_explicit_decision=False,
        )

    # Forecasting / predictive patterns from the shared canonical detector.
    if is_predictive(question):
        return _build_decision_payload(
            label="PREDICTIVE",
            confidence=0.95,
            reasoning="Predictive language detected by shared deterministic detector.",
            decision_source="deterministic_predictive_detector",
            llm_explicit_decision=False,
        )

    # Existing rule-based input classifier (numeric-only, noise, etc).
    rule_result = classify_input(raw_text=question, cleaned_text=question, source="text")
    rule_label = str(rule_result.get("classification") or "").strip().lower()
    if rule_label in {"invalid_input", "numeric_only_input", "noise_input", "empty_input", "no_speech_detected"}:
        return _build_decision_payload(
            label="INVALID",
            confidence=float(rule_result.get("confidence") or 1.0),
            reasoning=str(rule_result.get("reason") or "Input is invalid for BI analysis.").strip(),
            decision_source="deterministic_rule_input_guard",
            llm_explicit_decision=False,
        )

    return None


# ---------------------------------------------------------------------------
# LLM call (with shared circuit breaker)
# ---------------------------------------------------------------------------


def _build_prompt(question: str) -> str:
    question_json = json.dumps(str(question or ""))
    return (
        f"{STRICT_BI_LLM_CORE_POLICY}\n\n"
        "You are a query classifier. You must respond with ONLY a valid JSON object.\n\n"
        "TASK: Classify the user question into exactly ONE category.\n\n"
        "VALID LABELS (pick exactly one word):\n"
        "- ANALYTICAL   → questions about data, reports, comparisons, trends, totals, charts\n"
        "- PREDICTIVE   → questions about forecasts, future, predictions, \"will\", \"next month\"\n"
        "- NON_DATA     → greetings, general questions, unrelated to data\n"
        "- INVALID      → gibberish, incomplete, or unprocessable input\n"
        "- AMBIGUOUS    → only if truly impossible to classify\n\n"
        f"USER QUESTION: {question_json}\n\n"
        "RULES:\n"
        "- Your entire response must be ONLY the JSON object below, nothing else\n"
        "- Do NOT include markdown, explanation, or extra text\n"
        '- The "label" field must be ONE word: ANALYTICAL or PREDICTIVE or NON_DATA or INVALID or AMBIGUOUS\n'
        '- Do NOT put pipe characters or multiple labels in "label"\n'
        '- The "confidence" field must be a JSON number between 0.0 and 1.0 (not a string)\n\n'
        "RESPOND WITH THIS EXACT FORMAT (replace example values):\n"
        "{\n"
        '  "label": "ANALYTICAL",\n'
        '  "confidence": 0.85,\n'
        '  "reasoning": "one sentence explanation",\n'
        '  "evidence_tokens": ["word1", "word2"]\n'
        "}"
    )


def _strip_markdown_json_fence(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if not lines:
        return stripped
    # Drop opening ``` or ```json
    lines = lines[1:]
    while lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_llm_payload(raw_output: str) -> Dict[str, Any]:
    if not raw_output or not raw_output.strip():
        raise ValueError("Classifier output is empty.")
    normalized = _strip_markdown_json_fence(raw_output)
    try:
        payload = json.loads(normalized)
    except ValueError:
        match = re.search(r"\{.*\}", normalized, flags=re.DOTALL)
        if not match:
            raise ValueError(f"Classifier output is not valid JSON: {raw_output!r}")
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("Classifier JSON output must be an object.")

    label_source = str(payload.get("label") or payload.get("type") or "").strip()
    if "|" in label_source:
        raise ValueError(f"Classifier returned a multi-label field: {label_source!r}")
    label_raw = label_source.upper().split()[0] if label_source else ""
    if label_raw not in _VALID_LABELS:
        raise ValueError(f"Classifier returned an invalid label: {label_raw!r}")

    confidence_raw = payload.get("confidence", payload.get("score", 0.5))
    if isinstance(confidence_raw, str):
        confidence_raw = confidence_raw.strip().strip('"').strip("'")
    try:
        confidence_value = float(confidence_raw)
    except (TypeError, ValueError):
        confidence_value = 0.5

    reasoning = str(payload.get("reasoning") or payload.get("reason") or "").strip()
    if not reasoning:
        reasoning = "No reasoning provided."

    evidence_raw = payload.get("evidence_tokens", payload.get("evidence", []))
    if isinstance(evidence_raw, list):
        evidence = [str(t).strip() for t in evidence_raw if str(t).strip()]
    elif isinstance(evidence_raw, str) and evidence_raw.strip():
        evidence = [evidence_raw.strip()]
    else:
        evidence = []

    return {
        "label": label_raw,
        "confidence": max(0.0, min(1.0, confidence_value)),
        "reasoning": reasoning,
        "evidence_tokens": evidence,
    }


def _call_ollama_classifier(*, question: str) -> str:
    url = _get_ollama_url()
    model = _get_ollama_model()
    timeout_seconds = _get_timeout_seconds()
    payload = {
        "model": model,
        "prompt": _build_prompt(question),
        "stream": False,
        # Ollama JSON mode: forces the runtime to emit JSON instead of free
        # text. Falls back gracefully on older daemons that ignore the flag.
        "format": "json",
        "options": {
            "temperature": 0.0,
        },
    }
    request_id = str(uuid.uuid4())
    logger.info(
        "intent_classifier_request",
        extra={
            "endpoint": url,
            "model": model,
            "timeout_seconds": timeout_seconds,
            "request_id": request_id,
        },
    )

    response = get_default_client().post(
        url,
        json=payload,
        timeout=(5.0, float(timeout_seconds)),
        request_id=request_id,
        attach_internal_api_key=False,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Ollama HTTP {response.status_code}: {response.text.strip()[:500]}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError("Ollama returned non-JSON payload.") from exc

    raw_output = str(body.get("response", "")).strip()
    if not raw_output:
        raise RuntimeError("Ollama returned empty response body.")
    return raw_output


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_question(question: str) -> Dict[str, Any]:
    """Classify a BI question.

    The returned dict carries both the canonical Phase-4 fields
    (``label``, ``confidence``, ``reasoning``, ``evidence_tokens``) and the
    legacy fields the rest of the pipeline still consumes (``classification``,
    ``question_type``, ``needs_sql``, ``route``, ...).

    Behaviour:
    - Deterministic pre-check first; if it fires the LLM is never called.
    - Otherwise the LLM is called via the shared HTTP client (with retry +
      circuit breaker). When the breaker is open, we return ``AMBIGUOUS``
      instead of raising.
    - When the LLM succeeds, we enforce the JSON-schema contract on its
      output. Confidence below ``INTENT_CLASSIFICATION_MIN_CONFIDENCE`` (0.6
      by default) is downgraded to ``AMBIGUOUS``.
    - When the LLM fails (HTTP error, parse error, missing fields) we return
      ``AMBIGUOUS`` with the failure recorded in ``llm_error``.
    """

    normalized_question = re.sub(r"[^\S\r\n]+", " ", str(question or "").strip())

    deterministic_decision = _deterministic_pre_check(normalized_question)
    if deterministic_decision is not None:
        return deterministic_decision

    def _run_classifier_with_retry() -> str:
        first = _call_ollama_classifier(question=normalized_question)
        try:
            _parse_llm_payload(first)
        except ValueError:
            return _call_ollama_classifier(question=normalized_question)
        return first

    try:
        raw_output = _run_classifier_with_retry()
    except CircuitBreakerOpenError as exc:
        logger.warning(
            "intent_classifier_breaker_open",
            extra={"error": str(exc), "url": exc.url},
        )
        if _matches_analytical_signal(normalized_question):
            return _build_decision_payload(
                label="ANALYTICAL",
                confidence=0.72,
                reasoning="Classifier unavailable; deterministic analytical fallback matched BI intent signals.",
                decision_source="deterministic_analytical_fallback",
                llm_error=str(exc),
                llm_explicit_decision=False,
            )
        return _build_decision_payload(
            label="AMBIGUOUS",
            confidence=0.0,
            reasoning="Classifier circuit breaker is open; cannot reach Ollama right now.",
            decision_source="circuit_breaker_open",
            llm_error=str(exc),
            llm_explicit_decision=False,
        )
    except HttpClientError as exc:
        logger.warning(
            "intent_classifier_http_error",
            extra={"error": str(exc)},
        )
        if _matches_analytical_signal(normalized_question):
            return _build_decision_payload(
                label="ANALYTICAL",
                confidence=0.72,
                reasoning="Classifier transport failed; deterministic analytical fallback matched BI intent signals.",
                decision_source="deterministic_analytical_fallback",
                llm_error=str(exc),
                llm_explicit_decision=False,
            )
        return _build_decision_payload(
            label="AMBIGUOUS",
            confidence=0.0,
            reasoning="Classifier HTTP transport failed; defaulting to AMBIGUOUS so user can rephrase.",
            decision_source="llm_transport_failure",
            llm_error=str(exc),
            llm_explicit_decision=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "intent_classifier_unexpected_error",
            extra={"error": str(exc)},
        )
        if _matches_analytical_signal(normalized_question):
            return _build_decision_payload(
                label="ANALYTICAL",
                confidence=0.72,
                reasoning="Classifier failed; deterministic analytical fallback matched BI intent signals.",
                decision_source="deterministic_analytical_fallback",
                llm_error=str(exc),
                llm_explicit_decision=False,
            )
        return _build_decision_payload(
            label="AMBIGUOUS",
            confidence=0.0,
            reasoning="Classifier failed; defaulting to AMBIGUOUS so user can rephrase.",
            decision_source="llm_failure",
            llm_error=str(exc),
            llm_explicit_decision=False,
        )

    try:
        parsed = _parse_llm_payload(raw_output)
    except ValueError as exc:
        return _build_decision_payload(
            label="AMBIGUOUS",
            confidence=0.0,
            reasoning="Classifier produced an invalid JSON-schema payload; downgraded to AMBIGUOUS.",
            decision_source="llm_invalid_schema",
            llm_raw_response=raw_output,
            llm_error=str(exc),
            llm_explicit_decision=False,
        )

    label = parsed["label"]
    confidence = parsed["confidence"]
    min_conf = _get_min_confidence()

    # Phase 4 ambiguous handling: low confidence becomes AMBIGUOUS rather than
    # INVALID. We never flip a deterministic INVALID/NON_DATA back to AMBIGUOUS.
    if label not in {"INVALID", "NON_DATA"} and confidence < min_conf:
        return _build_decision_payload(
            label="AMBIGUOUS",
            confidence=confidence,
            reasoning=(
                f"Classifier confidence {confidence:.2f} is below the threshold {min_conf:.2f}. "
                "User should be asked to rephrase."
            ),
            decision_source="llm_low_confidence",
            evidence_tokens=parsed["evidence_tokens"],
            llm_raw_response=raw_output,
            llm_explicit_decision=False,
        )

    return _build_decision_payload(
        label=label,
        confidence=confidence,
        reasoning=parsed["reasoning"],
        decision_source="llm_explicit",
        evidence_tokens=parsed["evidence_tokens"],
        llm_raw_response=raw_output,
        llm_explicit_decision=True,
    )


__all__ = ["classify_question"]

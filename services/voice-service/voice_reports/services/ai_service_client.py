"""
voice-service ⇄ ai-service HTTP client.

Per CRIT-12 of the BACKEND_FULL_AUDIT_AND_FIX_ROADMAP this module is the
canonical replacement for ``voice_reports.services.small_whisper_client``
(deleted). The previous ``SmallWhisperClient`` class was misleadingly named
because it actually drives the entire AI pipeline (transcription, intent,
SQL, chart contract), not just Whisper.

This client treats ai-service as a black box: it submits audio or text to
the ai-service Dagster-backed endpoints and adapts whichever response shape
ai-service returns into the canonical pipeline-result shape used by
voice-service's orchestration layer.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from copy import deepcopy
from typing import Any, Dict, Optional

import requests
from django.conf import settings

from voice_reports.utils.trace_extraction import extract_pipeline_trace

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
    _SHARED_CLIENT_AVAILABLE = True
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]
    _SHARED_CLIENT_AVAILABLE = False


logger = logging.getLogger(__name__)


_EXPLICIT_NON_ANALYTICAL_TYPES = {
    "conversational",
    "informational",
    "invalid_input",
    "numeric_only_input",
    "noise_input",
    "empty_input",
    "transcription_failure",
    "no_speech_detected",
}
_ANALYTICAL_TYPES = {"analytical", "predictive", "forecast", "forecasting"}


def _normalize_question_type(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"forecast", "forecasting"}:
        return "predictive"
    if normalized in {
        "invalid",
        "invalid_input",
        "numeric_only_input",
        "noise_input",
        "empty_input",
        "transcription_failure",
        "no_speech_detected",
    }:
        return "invalid_input"
    if normalized in {
        "information",
        "informational",
        "info",
        "non_analytical",
        "non-analytical",
        "non_data",
    }:
        return "conversational"
    return normalized or "unknown"


def _adapt_canonical_ai_response(payload: dict, *, fallback_text: str = "") -> dict:
    status_value = str(payload.get("status") or "").strip().lower()
    if status_value not in {"success", "failed", "rejected", "degraded_success"}:
        return {}
    classification = payload.get("classification") if isinstance(payload.get("classification"), dict) else {}
    class_type = str(classification.get("type") or "").strip().lower()
    if class_type == "predictive":
        question_type = "predictive"
    elif class_type == "analytical":
        question_type = "analytical"
    elif class_type == "invalid":
        question_type = "invalid_input"
    else:
        question_type = "conversational"
    sql_review = payload.get("sql_review") if isinstance(payload.get("sql_review"), dict) else {}
    corrected_sql = str(sql_review.get("corrected_sql") or "").strip()
    sql = corrected_sql or str(payload.get("sql") or "").strip()
    final_user_message = str(
        payload.get("final_user_message")
        or payload.get("message")
        or payload.get("error")
        or classification.get("reasoning")
        or ""
    ).strip()
    return {
        "success": True,
        "status": status_value,
        "message": final_user_message,
        "error": final_user_message if status_value in {"failed", "rejected"} else "",
        "text": str(payload.get("normalized_question") or payload.get("question") or fallback_text).strip(),
        "reasoning": {
            "question_type": question_type,
            "needs_sql": question_type in _ANALYTICAL_TYPES,
            "needs_chart": question_type in _ANALYTICAL_TYPES,
            "message": final_user_message,
        },
        "question_type": question_type,
        "classification": classification,
        "schema_mapping": payload.get("schema_mapping") if isinstance(payload.get("schema_mapping"), dict) else {},
        "intent": payload.get("intent") if isinstance(payload.get("intent"), dict) else {},
        "sql": sql,
        "generated_sql": str(payload.get("generated_sql") or payload.get("sql") or "").strip(),
        "reviewed_sql": sql,
        "sql_review": sql_review,
        "chart": payload.get("chart_contract") if isinstance(payload.get("chart_contract"), dict) else {},
        "chart_contract": payload.get("chart_contract") if isinstance(payload.get("chart_contract"), dict) else {},
        "confidence": classification.get("confidence"),
        "confidence_breakdown": payload.get("confidence_breakdown"),
        "degraded": status_value == "degraded_success",
        "preprocessing_low": payload.get("preprocessing_low"),
        "preprocessing_high": payload.get("preprocessing_high"),
        "pipeline_trace": payload.get("pipeline_trace") or payload.get("trace") or {},
        "overall_status": payload.get("overall_status"),
        "root_cause": payload.get("root_cause"),
        "dagster_runtime": payload.get("dagster_runtime"),
        "final_route": "forecasting" if question_type == "predictive" else ("metabase" if question_type == "analytical" else "stop"),
        "final_user_message": final_user_message,
        "raw_response": payload,
    }


class AIServiceClient:
    """Client for the ai-service AI pipeline.

    Endpoints:

    - ``POST /api/transcribe/``: audio + form-data → full pipeline result.
    - ``POST /api/llm/intent/``: text → full pipeline result (legacy URL,
      now backed by the same Dagster pipeline as ``/api/transcribe/`` after
      Phase 12 of the audit).

    Response shapes are passed through ``_adapt_canonical_ai_response`` so
    voice-service's orchestrator only ever sees the canonical shape.
    """

    def __init__(self) -> None:
        self.base_url = getattr(settings, "SMALL_WHISPER_URL", "http://127.0.0.1:8001")
        self.transcribe_endpoint = f"{self.base_url}/api/transcribe/"
        self.intent_endpoint = f"{self.base_url}/api/llm/intent/"
        self.health_endpoint = f"{self.base_url}/admin/"
        self.health_timeout_seconds = int(getattr(settings, "SMALL_WHISPER_HEALTH_TIMEOUT_SECONDS", 5))
        self.connect_timeout_seconds = int(getattr(settings, "SMALL_WHISPER_CONNECT_TIMEOUT_SECONDS", 10))
        self.read_timeout_seconds = int(getattr(settings, "SMALL_WHISPER_TIMEOUT_SECONDS", 300))
        self.max_retries = max(0, int(getattr(settings, "SMALL_WHISPER_MAX_RETRIES", 1)))
        self.internal_api_key = str(getattr(settings, "AI_SERVICE_INTERNAL_API_KEY", "") or "").strip()
        logger.info(
            "ai_service_client_initialized",
            extra={
                "base_url": self.base_url,
                "connect_timeout_s": self.connect_timeout_seconds,
                "read_timeout_s": self.read_timeout_seconds,
                "max_retries": self.max_retries,
            },
        )

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.internal_api_key:
            headers["X-Internal-Api-Key"] = self.internal_api_key
        return headers

    def check_health(self) -> bool:
        try:
            if _SHARED_CLIENT_AVAILABLE:
                response = get_default_client().get(
                    self.health_endpoint,
                    timeout=(min(5.0, float(self.health_timeout_seconds)), float(self.health_timeout_seconds)),
                    attach_internal_api_key=False,
                )
            else:
                response = requests.get(self.health_endpoint, timeout=self.health_timeout_seconds)
            return response.status_code in (200, 301, 302, 404)
        except HttpClientError as exc:  # type: ignore[misc]
            logger.error("ai_service_health_failed", extra={"base_url": self.base_url, "error": str(exc)})
            return False
        except requests.exceptions.RequestException as exc:
            logger.error("ai_service_health_failed", extra={"base_url": self.base_url, "error": str(exc)})
            return False

    def _prepare_files(self, audio_file):
        if hasattr(audio_file, "read"):
            audio_file.seek(0)
            filename = os.path.basename(str(getattr(audio_file, "name", "audio") or "audio"))
            content_type = str(getattr(audio_file, "content_type", "") or "").strip()
            if not content_type:
                content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            return {"audio": (filename, audio_file, content_type)}, None
        file_handle = open(audio_file, "rb")
        filename = os.path.basename(audio_file)
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return {"audio": (filename, file_handle, content_type)}, file_handle

    def process_audio(
        self,
        audio_file,
        user_id: Optional[str] = None,
        *,
        workspace_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
        source_id: Optional[str] = None,
        table_name: Optional[str] = None,
        report_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.check_health():
            return {
                "success": False,
                "error": (
                    f"AI service is not reachable at {self.base_url}. "
                    "Please ensure the ai-service container is healthy."
                ),
            }

        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            file_to_close = None
            try:
                files, file_to_close = self._prepare_files(audio_file)
                form_data: Dict[str, str] = {}
                for key, value in (
                    ("user_id", user_id),
                    ("manager_id", manager_id),
                    ("workspace_id", workspace_id),
                    ("dataset_id", dataset_id),
                    ("source_id", source_id),
                    ("table_name", table_name),
                    ("report_id", report_id),
                ):
                    if value is not None and str(value).strip():
                        form_data[key] = str(value).strip()

                if _SHARED_CLIENT_AVAILABLE:
                    response = get_default_client().post(
                        self.transcribe_endpoint,
                        files=files,
                        data=form_data or None,
                        headers=self._headers(),
                        timeout=(float(self.connect_timeout_seconds), float(self.read_timeout_seconds)),
                        attach_internal_api_key=False,
                    )
                else:
                    response = requests.post(
                        self.transcribe_endpoint,
                        files=files,
                        data=form_data or None,
                        headers=self._headers(),
                        timeout=(self.connect_timeout_seconds, self.read_timeout_seconds),
                    )
                logger.info(
                    "ai_service_audio_response",
                    extra={"status": response.status_code, "attempt": attempt, "attempts": attempts},
                )

                if response.status_code != 200:
                    response_error = response.text[:500]
                    error_code = ""
                    error_type = ""
                    try:
                        payload = response.json()
                        if isinstance(payload, dict):
                            response_error = str(payload.get("error") or response_error)
                            error_code = str(payload.get("error_code") or "")
                            error_type = str(payload.get("error_type") or "")
                    except ValueError:
                        payload = None
                    logger.warning(
                        "ai_service_audio_rejected",
                        extra={
                            "status": response.status_code,
                            "error_code": error_code,
                            "error_type": error_type,
                            "error": response_error[:300],
                        },
                    )
                    return {
                        "success": False,
                        "error": f"AI service returned {response.status_code}: {response_error}",
                        "error_code": error_code,
                        "error_type": error_type,
                    }
                try:
                    result = response.json()
                except ValueError:
                    return {"success": False, "error": "AI service returned invalid JSON"}
                if not isinstance(result, dict):
                    return {"success": False, "error": "AI service returned invalid response payload"}

                canonical = _adapt_canonical_ai_response(result)
                if canonical:
                    return canonical
                return self._adapt_legacy_audio_response(result)

            except requests.exceptions.Timeout as exc:
                logger.warning(
                    "ai_service_audio_timeout",
                    extra={"attempt": attempt, "attempts": attempts, "error": str(exc)},
                )
                if attempt >= attempts:
                    break
            except requests.exceptions.ConnectionError as exc:
                logger.error("ai_service_audio_unreachable", extra={"error": str(exc)})
                return {
                    "success": False,
                    "error": (
                        f"AI service is not reachable at {self.base_url}. "
                        "Verify the ai-service container and DNS connectivity."
                    ),
                }
            except HttpClientError as exc:  # type: ignore[misc]
                logger.error("ai_service_audio_http_client_error", extra={"error": str(exc)})
                return {
                    "success": False,
                    "error": f"AI service request failed: {exc}",
                }
            except Exception as exc:  # noqa: BLE001
                logger.exception("ai_service_audio_unexpected")
                return {"success": False, "error": f"Unexpected error: {exc}"}
            finally:
                if file_to_close:
                    file_to_close.close()

        return {
            "success": False,
            "error": (
                f"AI service processing timed out after {self.read_timeout_seconds}s. "
                "Try a shorter audio file or a smaller Whisper model."
            ),
        }

    def _adapt_legacy_audio_response(self, result: Dict[str, Any]) -> Dict[str, Any]:
        text = result.get("text", "")
        reasoning = result.get("reasoning", {})
        llm_data = result.get("llm")
        question_type = _normalize_question_type(reasoning.get("question_type", "unknown"))
        if question_type == "unknown":
            question_type = "invalid_input"
        needs_sql = bool(reasoning.get("needs_sql", False) or question_type in _ANALYTICAL_TYPES)
        is_explicit_non_analytical = question_type in _EXPLICIT_NON_ANALYTICAL_TYPES
        common_payload = {
            "preprocessing_low": result.get("preprocessing_low"),
            "preprocessing_high": result.get("preprocessing_high"),
            "pipeline_trace": extract_pipeline_trace(result),
            "overall_status": result.get("overall_status"),
            "root_cause": result.get("root_cause"),
            "dagster_runtime": result.get("dagster_runtime"),
            "final_route": result.get("final_route"),
            "final_user_message": result.get("final_user_message"),
            "confidence": result.get("confidence"),
            "confidence_breakdown": result.get("confidence_breakdown"),
            "degraded": result.get("degraded"),
            "raw_response": result,
        }

        if is_explicit_non_analytical or (question_type not in _ANALYTICAL_TYPES and not needs_sql):
            return {
                "success": True,
                "text": text,
                "reasoning": reasoning,
                "question_type": question_type,
                "intent": None,
                "sql": None,
                "chart": None,
                "message": (
                    str(common_payload.get("final_user_message") or "").strip()
                    or reasoning.get("message")
                    or "Question does not require data analysis"
                ),
                **common_payload,
            }

        if not isinstance(llm_data, dict):
            return {
                "success": True,
                "text": text,
                "reasoning": reasoning,
                "question_type": question_type,
                "intent": None,
                "sql": None,
                "chart": None,
                "message": reasoning.get("message", "Analytical stage failed"),
                "analytical_error": reasoning.get("analytical_error"),
                **common_payload,
            }

        return {
            "success": True,
            "text": text,
            "reasoning": reasoning,
            "question_type": question_type,
            "intent": llm_data.get("intent"),
            "sql": llm_data.get("sql"),
            "generated_sql": llm_data.get("generated_sql"),
            "reviewed_sql": llm_data.get("reviewed_sql"),
            "sql_review": llm_data.get("sql_review"),
            "chart": llm_data.get("chart"),
            **common_payload,
        }

    def process_text(
        self,
        text: str,
        user_id: Optional[str] = None,
        *,
        workspace_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
        source_id: Optional[str] = None,
        table_name: Optional[str] = None,
        report_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        question = (text or "").strip()
        if not question:
            return {"success": False, "error": "Text is required"}
        if not self.check_health():
            return {
                "success": False,
                "error": (
                    f"AI service is not reachable at {self.base_url}. "
                    "Please ensure the ai-service container is healthy."
                ),
            }

        try:
            llm_payload: Dict[str, Any] = {"question": question}
            for key, value in (
                ("user_id", user_id),
                ("manager_id", manager_id),
                ("workspace_id", workspace_id),
                ("dataset_id", dataset_id),
                ("source_id", source_id),
                ("table_name", table_name),
                ("report_id", report_id),
            ):
                if value is not None and str(value).strip():
                    llm_payload[key] = str(value).strip()

            if _SHARED_CLIENT_AVAILABLE:
                llm_response = get_default_client().post(
                    self.intent_endpoint,
                    json=llm_payload,
                    headers=self._headers(),
                    timeout=(float(self.connect_timeout_seconds), float(self.read_timeout_seconds)),
                    attach_internal_api_key=False,
                )
            else:
                llm_response = requests.post(
                    self.intent_endpoint,
                    json=llm_payload,
                    headers=self._headers(),
                    timeout=(self.connect_timeout_seconds, self.read_timeout_seconds),
                )
            try:
                response_payload = llm_response.json()
            except ValueError:
                return {"success": False, "error": "ai_service_invalid_json"}
            if not isinstance(response_payload, dict):
                return {"success": False, "error": "ai_service_invalid_payload"}

            normalized_trace = extract_pipeline_trace(response_payload)
            canonical = _adapt_canonical_ai_response(response_payload, fallback_text=question)
            if canonical:
                return canonical

            if llm_response.status_code != 200 or response_payload.get("error"):
                classification_reason = (
                    str(response_payload.get("message") or "").strip()
                    or "AI classification failed; SQL generation was stopped."
                )
                reasoning = {
                    "question_type": "invalid_input",
                    "needs_sql": False,
                    "needs_chart": False,
                    "message": classification_reason,
                }
                return {
                    "success": True,
                    "text": question,
                    "reasoning": reasoning,
                    "question_type": "invalid_input",
                    "intent": None,
                    "sql": None,
                    "chart": None,
                    "message": reasoning["message"],
                    "analytical_error": response_payload,
                    "preprocessing_low": response_payload.get("preprocessing_low"),
                    "preprocessing_high": response_payload.get("preprocessing_high"),
                    "pipeline_trace": normalized_trace,
                    "overall_status": response_payload.get("overall_status"),
                    "root_cause": response_payload.get("root_cause"),
                    "dagster_runtime": response_payload.get("dagster_runtime"),
                    "final_route": response_payload.get("final_route"),
                    "final_user_message": response_payload.get("final_user_message"),
                    "confidence": response_payload.get("confidence"),
                    "confidence_breakdown": response_payload.get("confidence_breakdown"),
                    "degraded": response_payload.get("degraded"),
                    "raw_response": {"llm": deepcopy(response_payload)},
                }

            classification_payload = response_payload.get("classification") if isinstance(response_payload.get("classification"), dict) else {}
            intent_payload = response_payload.get("intent") if isinstance(response_payload.get("intent"), dict) else {}
            question_type = _normalize_question_type(
                response_payload.get("question_type")
                or classification_payload.get("type")
                or intent_payload.get("query_type")
                or intent_payload.get("intent_type")
            )
            if question_type == "unknown":
                question_type = "invalid_input"
            reasoning = {
                "question_type": question_type,
                "needs_sql": bool(question_type in _ANALYTICAL_TYPES),
                "needs_chart": bool(question_type in _ANALYTICAL_TYPES),
                "message": response_payload.get("final_user_message", "Analytical request processed."),
            }
            return {
                "success": True,
                "text": question,
                "reasoning": reasoning,
                "question_type": question_type,
                "intent": response_payload.get("intent"),
                "sql": response_payload.get("sql"),
                "generated_sql": response_payload.get("generated_sql"),
                "reviewed_sql": response_payload.get("reviewed_sql"),
                "sql_review": response_payload.get("sql_review"),
                "chart": response_payload.get("chart"),
                "confidence": response_payload.get("confidence", 0.5),
                "confidence_breakdown": response_payload.get("confidence_breakdown"),
                "degraded": response_payload.get("degraded"),
                "preprocessing_low": response_payload.get("preprocessing_low"),
                "preprocessing_high": response_payload.get("preprocessing_high"),
                "pipeline_trace": normalized_trace,
                "overall_status": response_payload.get("overall_status"),
                "root_cause": response_payload.get("root_cause"),
                "dagster_runtime": response_payload.get("dagster_runtime"),
                "final_route": response_payload.get("final_route"),
                "final_user_message": response_payload.get("final_user_message"),
                "raw_response": {"llm": deepcopy(response_payload)},
            }

        except requests.exceptions.Timeout as exc:
            logger.error("ai_service_text_timeout", extra={"error": str(exc)})
            return {
                "success": True,
                "status": "failed",
                "text": question,
                "reasoning": {
                    "question_type": "invalid_input",
                    "needs_sql": False,
                    "needs_chart": False,
                    "message": "AI classification timed out; SQL generation was stopped.",
                },
                "question_type": "invalid_input",
                "intent": {},
                "sql": None,
                "chart": {},
                "degraded": False,
                "pipeline_trace": {"overall_status": {"status": "failed", "reason": "classification_timeout"}},
                "raw_response": {},
            }
        except requests.exceptions.ConnectionError as exc:
            logger.error("ai_service_text_unreachable", extra={"error": str(exc)})
            return {
                "success": False,
                "error": (
                    f"AI service is not reachable at {self.base_url}. "
                    "Verify the ai-service container and DNS connectivity."
                ),
            }
        except HttpClientError as exc:  # type: ignore[misc]
            logger.error("ai_service_text_http_client_error", extra={"error": str(exc)})
            return {
                "success": False,
                "error": f"AI service request failed: {exc}",
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("ai_service_text_unexpected")
            return {"success": False, "error": f"Unexpected error: {exc}"}


_singleton: Optional[AIServiceClient] = None


def get_ai_service_client() -> AIServiceClient:
    """Process-wide singleton accessor for the AI service client."""

    global _singleton
    if _singleton is None:
        _singleton = AIServiceClient()
    return _singleton


__all__ = ["AIServiceClient", "get_ai_service_client"]

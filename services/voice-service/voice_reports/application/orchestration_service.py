from __future__ import annotations

import hashlib
import os
from typing import Any
import logging
from copy import deepcopy

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.conf import settings
from django.db import transaction
from django.utils import timezone
import uuid

from voice_reports.application.job_service import create_pipeline_job, mark_job_stage
from voice_reports.domain import errors as err
from voice_reports.domain.chart_from_ai_result import contract_dict_from_ai_result
from voice_reports.domain import statuses
from voice_reports.infrastructure.ai_client import get_ai_client
from voice_reports.infrastructure.query_client import get_query_client, validate_sql_via_query_service
from voice_reports.infrastructure.visualization_client import get_visualization_client
from voice_reports.infrastructure.workspace_client import get_workspace_client
from voice_reports.models import VoicePipelineJob, VoiceReport
from voice_reports.services.ai_trace_service import build_ai_trace_payload
from voice_reports.services.forecasting_bridge import ForecastingBridgeError, build_forecast_payload
from voice_reports.utils.trace_builder import stage_trace
from voice_reports.utils.trace_extraction import extract_pipeline_trace, is_valid_trace

logger = logging.getLogger(__name__)
# Allow tiny confidence drift around the minimum threshold (float rounding,
# serialization differences across services) without letting clearly low
# confidence pass.
try:
    _CONFIDENCE_EPSILON = float(os.getenv("VOICE_AI_CLASSIFICATION_CONFIDENCE_EPSILON", "0.005"))
except (TypeError, ValueError):
    _CONFIDENCE_EPSILON = 0.005
_CONFIDENCE_EPSILON = max(0.0, _CONFIDENCE_EPSILON)


def _resolve_audio_path(path_hint: str, report: VoiceReport) -> str:
    """Resolve audio path for worker execution across container boundaries."""

    candidates: list[str] = []
    hint = str(path_hint or "").strip()
    if hint:
        candidates.append(hint)
        if not os.path.isabs(hint):
            candidates.append(os.path.join(str(settings.MEDIA_ROOT), hint))
    try:
        report_path = str(report.audio_file.path or "").strip()
        if report_path:
            candidates.append(report_path)
    except Exception:
        pass
    report_name = str(getattr(report.audio_file, "name", "") or "").strip()
    if report_name:
        candidates.append(os.path.join(str(settings.MEDIA_ROOT), report_name))

    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.abspath(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.exists(normalized):
            return normalized
    return os.path.abspath(candidates[0]) if candidates else ""


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _classification_payload(ai_result: dict[str, Any]) -> dict[str, Any]:
    payload = ai_result if isinstance(ai_result, dict) else {}
    classification = payload.get("classification") if isinstance(payload.get("classification"), dict) else {}
    question_type = str(payload.get("question_type") or "").strip().lower()
    class_type = str(classification.get("type") or question_type or "").strip().lower()
    if class_type in {"forecast", "forecasting"}:
        class_type = "predictive"
    if class_type in {"conversational", "informational", "non_analytical", "non-data"}:
        class_type = "non_data"
    confidence = _safe_float(classification.get("confidence", payload.get("confidence")), 0.0)
    return {
        **classification,
        "type": class_type,
        "confidence": confidence,
        "is_analytical": bool(classification.get("is_analytical") or class_type == "analytical"),
        "is_predictive": bool(classification.get("is_predictive") or class_type == "predictive"),
        "reasoning": str(classification.get("reasoning") or payload.get("message") or ""),
    }


def _ai_sql_gate(ai_result: dict[str, Any]) -> tuple[bool, str, str]:
    payload = ai_result if isinstance(ai_result, dict) else {}
    status_value = str(payload.get("status") or ("success" if payload.get("success") else "failed")).strip().lower()
    classification = _classification_payload(payload)
    class_type = str(classification.get("type") or "").strip().lower()
    confidence = _safe_float(classification.get("confidence"), 0.0)
    min_confidence = _safe_float(os.getenv("VOICE_AI_MIN_CLASSIFICATION_CONFIDENCE", "0.60"), 0.60)

    if status_value in {"failed", "rejected"}:
        return False, err.AI_SERVICE_INVALID_RESPONSE, str(
            payload.get("error")
            or payload.get("message")
            or payload.get("final_user_message")
            or classification.get("reasoning")
            or "AI pipeline did not approve SQL generation."
        )
    if class_type in {"", "invalid", "invalid_input", "non_data", "noise_input", "numeric_only_input", "empty_input", "transcription_failure", "no_speech_detected"}:
        return False, err.AI_SERVICE_INVALID_RESPONSE, str(classification.get("reasoning") or "Question was rejected before SQL generation.")
    if not (classification.get("is_analytical") or classification.get("is_predictive")):
        return False, err.AI_SERVICE_INVALID_RESPONSE, str(classification.get("reasoning") or "Question does not require data analysis.")
    if (confidence + _CONFIDENCE_EPSILON) < min_confidence:
        return (
            False,
            err.AI_SERVICE_INVALID_RESPONSE,
            (
                "AI classification confidence "
                f"{confidence:.4f} is below required {min_confidence:.4f}."
            ),
        )
    return True, "", ""


def _is_predictive_request(ai_result: dict[str, Any], intent: dict[str, Any]) -> bool:
    classification = _classification_payload(ai_result if isinstance(ai_result, dict) else {})
    forecast_payload = intent.get("forecast") if isinstance(intent.get("forecast"), dict) else {}
    return bool(
        classification.get("is_predictive")
        or str(classification.get("type") or "").strip().lower() == "predictive"
        or str(intent.get("query_type") or intent.get("intent_type") or "").strip().lower() in {"predictive", "forecast", "forecasting"}
        or bool(forecast_payload.get("enabled"))
        or bool(intent.get("requires_forecast"))
    )


def _forecast_horizon(intent: dict[str, Any]) -> int | None:
    forecast_payload = intent.get("forecast") if isinstance(intent.get("forecast"), dict) else {}
    for candidate in (
        forecast_payload.get("horizon"),
        intent.get("forecast_horizon"),
        intent.get("horizon"),
    ):
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _forecasting_config(forecast_dataset: dict[str, Any]) -> dict[str, Any]:
    rows = forecast_dataset.get("rows") if isinstance(forecast_dataset.get("rows"), list) else []
    meta = forecast_dataset.get("meta") if isinstance(forecast_dataset.get("meta"), dict) else {}
    model_status = meta.get("forecasting_model_status") if isinstance(meta.get("forecasting_model_status"), dict) else {}
    forecast_rows = [row for row in rows if isinstance(row, dict) and str(row.get("series_type") or "").lower() == "forecast"]
    actual_rows = [row for row in rows if isinstance(row, dict) and str(row.get("series_type") or "").lower() == "actual"]
    fallback_reason = str(meta.get("fallback_reason") or model_status.get("fallback_reason") or "").strip()
    used_fallback = bool(model_status.get("used_fallback") or (fallback_reason and not forecast_rows))
    status_value = "degraded_success" if used_fallback or not forecast_rows else "success"
    return {
        "enabled": True,
        "status": status_value,
        "forecast_available": bool(meta.get("forecast_available") and forecast_rows),
        "actual_rows": actual_rows,
        "forecast_rows": forecast_rows,
        "horizon": int(meta.get("horizon") or len(forecast_rows) or 0),
        "target_column": meta.get("value_column"),
        "date_column": meta.get("time_column"),
        "model_used": model_status.get("provider") or model_status.get("model") or "timesfm",
        "degraded_reason": fallback_reason if used_fallback else "",
        "meta": meta,
        "chart_series_config": meta.get("chart_series_config") if isinstance(meta.get("chart_series_config"), list) else [],
    }


def _visualization_chart_config(viz: dict[str, Any], chart_contract: dict[str, Any]) -> dict[str, Any]:
    requested = str(
        chart_contract.get("type")
        or chart_contract.get("final_chart_type")
        or chart_contract.get("chart_type")
        or chart_contract.get("selected_chart_type")
        or viz.get("requested_chart_type")
        or ""
    ).strip().lower()
    final = str(viz.get("final_chart_type") or viz.get("chart_type") or requested).strip().lower()
    return {
        "chart_contract": chart_contract,
        "requested_chart_type": requested,
        "selected_chart_type": requested,
        "final_chart_type": final,
        "effective_chart_type": final,
        "fallback_used": bool(viz.get("fallback_used")),
        "fallback_reason": viz.get("fallback_reason"),
        "visualization_status": viz.get("status", "success"),
        "render_status": str(viz.get("render_status") or ("success" if str(viz.get("status") or "").lower() == "success" else "")),
        "contract_preserved": bool(viz.get("contract_preserved", True)),
        "metabase_question_id": viz.get("metabase_question_id") or viz.get("question_id"),
        "downgrade_reason": str(viz.get("downgrade_reason") or "").strip(),
        "visualization_trace": viz.get("trace", []),
    }


def _align_chart_contract_with_result(
    chart_contract: dict[str, Any],
    *,
    columns: list[Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bind chart axes to actual result columns without changing chart type.

    This keeps chart-lock strict while fixing predictable alias drift such as
    ``date`` vs ``ds`` and ``orders`` vs ``value`` in forecasting output.
    """

    contract = dict(chart_contract or {})
    available: list[str] = []
    for col in columns or []:
        if isinstance(col, dict):
            name = str(col.get("name") or "").strip()
        else:
            name = str(col or "").strip()
        if name:
            available.append(name)
    if not available and rows and isinstance(rows[0], dict):
        available = [str(k) for k in rows[0].keys()]
    if not available:
        return contract

    available_set = set(available)

    def _resolve_column(requested: str, aliases: tuple[str, ...]) -> str:
        if requested and requested in available_set:
            return requested
        for alias in aliases:
            if alias in available_set:
                return alias
        return requested

    requested_x = str(contract.get("x_axis") or "").strip()
    resolved_x = _resolve_column(requested_x, ("ds", "date", "period", "bucket"))
    if resolved_x in available_set:
        contract["x_axis"] = resolved_x

    raw_y = contract.get("y_axis")
    y_axis = raw_y if isinstance(raw_y, list) else [raw_y] if raw_y else []
    normalized_y = [str(item).strip() for item in y_axis if str(item or "").strip()]
    if normalized_y:
        resolved_y: list[str] = []
        numeric_candidates = ("value", "orders", "total_sales", "sum_total_sales", "frequency")
        for metric in normalized_y:
            chosen = _resolve_column(metric, numeric_candidates)
            if chosen in available_set and chosen not in resolved_y:
                resolved_y.append(chosen)
        if resolved_y:
            contract["y_axis"] = resolved_y
    else:
        # Fallback for partially-empty contracts from upstream: infer measure
        # columns from result rows so visualization does not fail with
        # `missing_metrics` when SQL output is otherwise valid.
        def _is_numeric_column(name: str) -> bool:
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                value = row.get(name)
                if value is None:
                    continue
                if isinstance(value, bool):
                    return False
                if isinstance(value, (int, float)):
                    return True
                return False
            return False

        excluded = {str(contract.get("x_axis") or "").strip(), str(contract.get("series_dimension") or "").strip()}
        excluded.discard("")
        numeric_candidates = [col for col in available if col not in excluded and _is_numeric_column(col)]
        if numeric_candidates:
            chart_type = str(contract.get("chart_type") or contract.get("type") or "").strip().lower()
            if chart_type == "line_multi":
                contract["y_axis"] = numeric_candidates
            else:
                contract["y_axis"] = [numeric_candidates[0]]

    label_column = str(contract.get("label_column") or "").strip()
    resolved_label = _resolve_column(label_column, ("ds", "date", "period", "bucket"))
    if resolved_label in available_set:
        contract["label_column"] = resolved_label

    value_column = str(contract.get("value_column") or "").strip()
    resolved_value = _resolve_column(
        value_column,
        ("value", "orders", "total_sales", "sum_total_sales", "frequency"),
    )
    if resolved_value in available_set:
        contract["value_column"] = resolved_value

    series_dimension = str(contract.get("series_dimension") or "").strip()
    if series_dimension and series_dimension not in available_set and "series_type" in available_set:
        contract["series_dimension"] = "series_type"

    return contract


def _append_trace(job: VoicePipelineJob, stage: str, status: str, details: dict[str, Any] | None = None) -> None:
    trace = job.trace if isinstance(job.trace, dict) else {}
    events = trace.get("events", []) if isinstance(trace.get("events"), list) else []
    events.append(stage_trace(stage, status, details))
    trace["events"] = events
    job.trace = trace


def _build_report_ai_trace(report: VoiceReport) -> dict[str, Any]:
    return build_ai_trace_payload(
        report_id=report.id,
        transcription=report.transcription,
        preprocessing_low=report.preprocessing_low,
        preprocessing_high=report.preprocessing_high,
        intent_json=report.intent_json,
        pipeline_trace=report.pipeline_trace,
        generated_sql=report.generated_sql,
        reviewed_sql=report.final_sql,
        query_result=report.query_result,
        execution_time_ms=report.execution_time_ms,
        row_count=report.row_count,
        chart_type=report.chart_type,
        metabase_question_id=report.metabase_question_id,
        metabase_dashboard_id=report.metabase_dashboard_id,
        embed_url=report.embed_url,
        chart_config=report.chart_config,
        error_message=report.error_message,
    )


def _trace_version_tuple(trace: Any) -> tuple[int, int]:
    """Phase 10 / §12.3: parse the ``trace_version`` field of a trace.

    Unknown / missing versions become ``(0, 0)`` so they cannot overwrite a
    fresher persisted trace. Recognised versions are ``"1.0"`` and ``"2.0"``.
    """

    if not isinstance(trace, dict):
        return (0, 0)
    raw = str(trace.get("trace_version") or "").strip()
    if raw in {"", "0", "0.0"}:
        return (0, 0)
    if raw not in {"1.0", "2.0"}:
        logger.warning("pipeline_trace_unknown_version version=%s", raw)
        return (0, 0)
    parts = raw.split(".")
    try:
        major = int(parts[0]) if parts else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        return (major, minor)
    except (TypeError, ValueError):
        return (0, 0)


def _select_trace_for_persistence(*, existing_trace: Any, ai_result: dict[str, Any]) -> dict[str, Any]:
    """Pick the freshest valid trace.

    Phase 10 / §12.3: instead of picking by "first valid", we now pick by
    explicit ``trace_version``. A fresh trace overwrites the existing one
    only when its version is greater than or equal to the existing one.
    Older traces are explicitly rejected and logged.
    """

    existing = deepcopy(existing_trace) if isinstance(existing_trace, dict) else {}
    extracted_from_result = extract_pipeline_trace(ai_result)
    normalized_from_client = deepcopy(ai_result.get("pipeline_trace")) if isinstance(ai_result.get("pipeline_trace"), dict) else {}

    candidates: list[tuple[tuple[int, int], dict[str, Any], str]] = []
    if is_valid_trace(extracted_from_result):
        candidates.append((_trace_version_tuple(extracted_from_result), extracted_from_result, "extracted"))
    if is_valid_trace(normalized_from_client):
        candidates.append((_trace_version_tuple(normalized_from_client), normalized_from_client, "client"))
    if is_valid_trace(existing):
        candidates.append((_trace_version_tuple(existing), existing, "existing"))

    if not candidates:
        return {}

    candidates.sort(key=lambda item: item[0], reverse=True)
    chosen_version, chosen_trace, chosen_source = candidates[0]

    rejected = [
        {"source": source, "version": list(version)}
        for version, _, source in candidates[1:]
        if version != chosen_version
    ]
    logger.info(
        "Pipeline trace persistence decision chosen_source=%s chosen_version=%s rejected=%s",
        chosen_source,
        list(chosen_version),
        rejected,
    )
    return chosen_trace


def _finalize_failure(
    job: VoicePipelineJob,
    report: VoiceReport,
    *,
    error_code: str,
    message: str,
    fallback_trace: dict[str, Any] | None = None,
) -> VoicePipelineJob:
    mark_job_stage(
        job,
        status=statuses.FAILED,
        stage=statuses.FAILED,
        progress=100,
        error_code=error_code,
        error_message=message,
    )
    _append_trace(job, statuses.FAILED, "failed", {"error_code": error_code, "message": message})
    job.retry_count = int(job.retry_count or 0) + 1
    job.save(update_fields=["retry_count", "trace", "updated_at", "status", "current_stage", "progress", "error_code", "error_message", "completed_at"])

    report.status = VoiceReport.STATUS_FAILED
    report.error_message = message

    # Phase 10: persist a partial trace on failure even when the upstream
    # trace is not "complete" (i.e. lacks late stages). The previous
    # implementation skipped the persistence entirely if the trace did not
    # contain ALL canonical stages, which made post-mortem debugging
    # impossible for early-pipeline failures (e.g. transcription error).
    try:
        partial_trace: dict[str, Any] = {}
        if isinstance(report.pipeline_trace, dict) and report.pipeline_trace:
            partial_trace = deepcopy(report.pipeline_trace)
        elif isinstance(fallback_trace, dict) and fallback_trace:
            partial_trace = deepcopy(fallback_trace)
        elif isinstance(job.trace, dict):
            snapshot = job.trace.get("pipeline_trace_snapshot")
            if isinstance(snapshot, dict) and snapshot:
                partial_trace = deepcopy(snapshot)

        if not partial_trace:
            partial_trace = {
                "trace_version": "2.0",
                "partial": True,
                "stages_captured": [],
            }

        partial_trace.setdefault("trace_version", "2.0")
        partial_trace.setdefault("overall_status", {})
        if isinstance(partial_trace.get("overall_status"), dict):
            partial_trace["overall_status"].update(
                {
                    "status": "failed",
                    "stage": error_code,
                    "final_user_message": message,
                }
            )
        partial_trace.setdefault("root_cause", {})
        if isinstance(partial_trace.get("root_cause"), dict):
            partial_trace["root_cause"].update(
                {"code": error_code, "message": message}
            )
        report.pipeline_trace = partial_trace
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "partial_trace_persist_failed report_id=%s error=%s",
            report.id,
            str(exc),
        )
        if not isinstance(report.pipeline_trace, dict):
            report.pipeline_trace = {
                "trace_version": "2.0",
                "partial": True,
                "stages_captured": [],
                "overall_status": {
                    "status": "failed",
                    "stage": error_code,
                    "final_user_message": message,
                },
                "root_cause": {"code": error_code, "message": message},
            }

    report.ai_trace = _build_report_ai_trace(report)
    report.save(update_fields=["status", "error_message", "pipeline_trace", "ai_trace", "updated_at"])
    return job


def process_pipeline_job(job_id: str) -> VoicePipelineJob:
    max_retries = max(0, int(os.getenv("VOICE_PIPELINE_MAX_RETRIES", "3")))
    lock_ttl = max(5, int(os.getenv("VOICE_PIPELINE_LOCK_TTL_SECONDS", "300")))
    lock_key = f"voice_pipeline_job_lock:{job_id}"

    if not cache.add(lock_key, "1", timeout=lock_ttl):
        job = VoicePipelineJob.objects.get(job_id=job_id)
        _append_trace(job, "lock", "skipped", {"reason": err.LOCKED})
        job.save(update_fields=["trace", "updated_at"])
        return job

    last_valid_trace: dict[str, Any] = {}

    try:
        with transaction.atomic():
            job = VoicePipelineJob.objects.select_related("report", "workspace", "user").select_for_update().get(job_id=job_id)
            report = job.report

            if job.status == statuses.COMPLETED:
                return job
            if job.status == statuses.FAILED and int(job.retry_count or 0) >= max_retries:
                _append_trace(job, "retry", "skipped", {"reason": err.MAX_RETRIES_EXCEEDED})
                job.save(update_fields=["trace", "updated_at"])
                return job

            mark_job_stage(job, status=statuses.QUEUED, stage=statuses.QUEUED, progress=5)
            _append_trace(job, statuses.QUEUED, "success", {})

            payload = job.trace if isinstance(job.trace, dict) else {}
            ctx = get_workspace_client().resolve(
                request=type("Req", (), {"META": {"HTTP_AUTHORIZATION": payload.get("authorization_header", "")}})(),
                workspace_hint=str(job.workspace_id),
                user_id=str(job.user_id),
            )
            dataset_id = str(payload.get("dataset_id") or ctx.dataset_id or "").strip()
            source_id = str(payload.get("source_id") or ctx.source_id or dataset_id or "").strip()
            table_name = str(payload.get("table_name") or ctx.table_name or "").strip()

            if job.input_type == VoicePipelineJob.INPUT_TYPE_AUDIO:
                mark_job_stage(job, status=statuses.TRANSCRIBING, stage=statuses.TRANSCRIBING, progress=15)
                audio_path = _resolve_audio_path(str(job.trace.get("audio_path") or ""), report)
                if not audio_path or not os.path.exists(audio_path):
                    return _finalize_failure(
                        job,
                        report,
                        error_code=err.AI_SERVICE_UNAVAILABLE,
                        message=f"Audio file unavailable for worker processing: {audio_path or 'missing_path'}",
                    )
                ai_result = get_ai_client().process_audio(
                    audio_file=audio_path,
                    user_id=str(job.user_id),
                    workspace_id=ctx.workspace_id,
                    manager_id=ctx.manager_id,
                    dataset_id=dataset_id,
                    source_id=source_id,
                    table_name=table_name,
                    report_id=str(report.id),
                )
                _append_trace(job, statuses.TRANSCRIBING, "success", {"output_summary": {"input_type": "audio"}})
            else:
                mark_job_stage(job, status=statuses.AI_PROCESSING, stage=statuses.AI_PROCESSING, progress=30)
                ai_result = get_ai_client().process_text(
                    text=job.original_question or report.transcription,
                    user_id=str(job.user_id),
                    workspace_id=ctx.workspace_id,
                    manager_id=ctx.manager_id,
                    dataset_id=dataset_id,
                    source_id=source_id,
                    table_name=table_name,
                    report_id=str(report.id),
                )

            if not isinstance(ai_result, dict):
                return _finalize_failure(
                    job,
                    report,
                    error_code=err.AI_SERVICE_UNAVAILABLE,
                    message="AI service returned an invalid response",
                )

            cleaned_question = str(ai_result.get("text") or job.original_question or report.transcription or "").strip()
            generated_sql = str(ai_result.get("reviewed_sql") or ai_result.get("generated_sql") or ai_result.get("sql") or "").strip()
            intent = ai_result.get("intent") if isinstance(ai_result.get("intent"), dict) else {}
            try:
                chart_recommendation = contract_dict_from_ai_result(ai_result)
            except ValueError as exc:
                return _finalize_failure(
                    job,
                    report,
                    error_code=err.AI_SERVICE_INVALID_RESPONSE,
                    message=f"AI chart contract invalid: {exc}",
                )

            report.transcription = cleaned_question
            report.intent_json = intent
            report.generated_sql = generated_sql
            report.final_sql = generated_sql
            report.preprocessing_low = ai_result.get("preprocessing_low")
            report.preprocessing_high = ai_result.get("preprocessing_high")
            selected_trace = _select_trace_for_persistence(existing_trace=report.pipeline_trace, ai_result=ai_result)
            if is_valid_trace(selected_trace):
                report.pipeline_trace = selected_trace
                last_valid_trace = deepcopy(selected_trace)
                job.trace = job.trace if isinstance(job.trace, dict) else {}
                job.trace["pipeline_trace_snapshot"] = deepcopy(selected_trace)
            else:
                logger.warning("Rejected invalid trace for report_id=%s; preserving existing trace.", report.id)
            report.ai_trace = _build_report_ai_trace(report)
            report.save(update_fields=["transcription", "intent_json", "generated_sql", "final_sql", "preprocessing_low", "preprocessing_high", "pipeline_trace", "ai_trace", "updated_at"])
            job.save(update_fields=["trace", "updated_at"])
            logger.info(
                "AI trace persistence report_id=%s pipeline_trace_found=%s pipeline_trace_saved=%s ai_trace_rebuilt=%s",
                report.id,
                bool(ai_result.get("pipeline_trace")),
                isinstance(report.pipeline_trace, dict) and bool(report.pipeline_trace),
                isinstance(report.ai_trace, dict) and bool(report.ai_trace),
            )

            job.cleaned_question = cleaned_question
            job.generated_sql = generated_sql
            _append_trace(job, statuses.AI_PROCESSING, "success", {"classification": _classification_payload(ai_result), "intent": intent})

            if ai_result.get("success") is False:
                return _finalize_failure(
                    job,
                    report,
                    error_code=err.AI_SERVICE_UNAVAILABLE,
                    message=str(ai_result.get("error") or "AI service unavailable"),
                )

            allowed_for_sql, gate_error_code, gate_message = _ai_sql_gate(ai_result)
            if not allowed_for_sql:
                return _finalize_failure(
                    job,
                    report,
                    error_code=gate_error_code,
                    message=gate_message,
                    fallback_trace=last_valid_trace,
                )

            if not generated_sql:
                return _finalize_failure(job, report, error_code=err.AI_SERVICE_INVALID_RESPONSE, message="AI response did not contain generated SQL")

            authorization_header = str(payload.get("authorization_header", ""))
            token = authorization_header.replace("Bearer ", "", 1).strip() if authorization_header else None
            workspace_id_for_query = str(payload.get("workspace_id") or getattr(ctx, "workspace_id", ""))
            is_valid, validation_error, clean_sql = validate_sql_via_query_service(
                sql=generated_sql,
                token=token,
                workspace_id=workspace_id_for_query,
            )
            if not is_valid:
                if validation_error == "query_service_unauthorized":
                    msg = "Query execution failed due to authorization error between services."
                elif validation_error in {"query_service_auth_not_configured"}:
                    msg = "Query execution failed due to missing service authentication configuration."
                else:
                    msg = f"SQL validation failed: {validation_error}" if validation_error else "SQL validation failed."
                return _finalize_failure(job, report, error_code=err.SQL_VALIDATION_FAILED, message=msg)

            mark_job_stage(job, status=statuses.SQL_GENERATED, stage=statuses.SQL_GENERATED, progress=50)
            _append_trace(
                job,
                statuses.SQL_GENERATED,
                "success",
                {
                    "normalized_sql_sha256": hashlib.sha256(
                        (clean_sql or "").encode("utf-8", errors="replace")
                    ).hexdigest(),
                    "normalized_sql_len": len(clean_sql or ""),
                },
            )
            report.final_sql = clean_sql
            report.sql_validated = True
            report.chart_type = str(
                chart_recommendation.get("type")
                or chart_recommendation.get("final_chart_type")
                or chart_recommendation.get("chart_type")
                or chart_recommendation.get("selected_chart_type")
                or report.chart_type
                or ""
            ).strip().lower()
            report.chart_config = {
                **(report.chart_config if isinstance(report.chart_config, dict) else {}),
                "chart_contract": chart_recommendation,
                "requested_chart_type": chart_recommendation.get("chart_type") or chart_recommendation.get("selected_chart_type"),
            }
            report.save(update_fields=["final_sql", "sql_validated", "chart_type", "chart_config", "updated_at"])

            mark_job_stage(job, status=statuses.EXECUTING_QUERY, stage=statuses.EXECUTING_QUERY, progress=70)
            # Phase 7 / CRIT-05: query-service resolves the per-tenant
            # ClickHouse database from ``workspace_id``; the previous
            # ``QUERY_WORKSPACE_DATABASE`` env fallback (which silently
            # routed everything to ``etl``) is gone.
            query_result = get_query_client().execute(
                sql=clean_sql,
                authorization_header=str(payload.get("authorization_header", "")),
                workspace_id=workspace_id_for_query,
            )
            if not isinstance(query_result, dict) or not query_result.get("success"):
                code = str((query_result or {}).get("error") or "")
                if code == err.QUERY_SERVICE_UNAVAILABLE:
                    return _finalize_failure(job, report, error_code=err.QUERY_SERVICE_UNAVAILABLE, message="Query service unavailable")
                if "401" in code or "unauthorized" in code.lower():
                    return _finalize_failure(
                        job,
                        report,
                        error_code=err.QUERY_EXECUTION_FAILED,
                        message="Query execution failed due to authorization error between services.",
                    )
                return _finalize_failure(job, report, error_code=err.QUERY_EXECUTION_FAILED, message=str((query_result or {}).get("error") or "Query execution failed"))

            rows = query_result.get("rows", []) if isinstance(query_result.get("rows"), list) else []
            columns = query_result.get("columns", []) if isinstance(query_result.get("columns"), list) else []
            report.query_result = {"columns": columns, "rows": rows}
            report.row_count = int(query_result.get("row_count") or len(rows))
            report.execution_time_ms = int(query_result.get("execution_time_ms") or 0)
            report.status = VoiceReport.STATUS_EXECUTED
            report.ai_trace = _build_report_ai_trace(report)
            report.save(update_fields=["query_result", "row_count", "execution_time_ms", "status", "ai_trace", "updated_at"])
            job.execution_result_summary = {"row_count": report.row_count, "columns": columns}
            _append_trace(job, statuses.EXECUTING_QUERY, "success", {"row_count": report.row_count, "empty_result": bool(query_result.get("empty_result"))})

            requested_chart = str(chart_recommendation.get("chart_type") or chart_recommendation.get("selected_chart_type") or "").strip().lower()
            empty_result = bool(query_result.get("empty_result") or report.row_count == 0)
            predictive = _is_predictive_request(ai_result, intent)
            if empty_result and (predictive or requested_chart not in {"table", "card"}):
                # Phase 13 / GAP-04 / CRIT-09: typed ``empty_result`` UX. We
                # complete the pipeline as ``empty_result`` (a degraded
                # status) with a stable error code so the frontend can
                # render a placeholder card with the metric and a "your
                # filter returned 0 rows. Try …" message instead of
                # showing "success" with no chart.
                degraded_reason = (
                    "SQL executed successfully but returned no rows. Possible reasons: "
                    "filters too restrictive, date parsing issue, wrong grouping, or missing data."
                )
                report.error_message = degraded_reason
                report.chart_config = {
                    **(report.chart_config if isinstance(report.chart_config, dict) else {}),
                    "empty_result": True,
                    "visualization_status": "empty_result",
                    "fallback_used": False,
                    "fallback_reason": "empty_result",
                    "degraded_reason": degraded_reason,
                    "error_code": "empty_result",
                    "user_facing_message": (
                        "Your query ran successfully but returned no rows. "
                        "Try widening filters, checking the date range, or removing the GROUP BY column."
                    ),
                }
                report.ai_trace = _build_report_ai_trace(report)
                report.save(update_fields=["error_message", "chart_config", "ai_trace", "updated_at"])
                mark_job_stage(job, status=statuses.COMPLETED, stage=statuses.COMPLETED, progress=100)
                _append_trace(
                    job,
                    statuses.VISUALIZING,
                    "empty_result",
                    {
                        "error_code": "empty_result",
                        "degraded_reason": degraded_reason,
                        "skipped": "visualization_not_rendered_for_empty_result",
                    },
                )
                job.trace = job.trace if isinstance(job.trace, dict) else {}
                job.trace["finalized_at"] = timezone.now().isoformat()
                job.save(update_fields=["cleaned_question", "generated_sql", "execution_result_summary", "trace", "updated_at", "status", "current_stage", "progress", "completed_at"])
                return job

            visualization_sql = clean_sql
            forecasting_config: dict[str, Any] = {}
            if predictive:
                try:
                    forecast_dataset = build_forecast_payload(
                        columns=columns,
                        rows=rows,
                        intent=intent,
                        horizon=_forecast_horizon(intent),
                    )
                except ForecastingBridgeError as exc:
                    # Phase 9 / CRIT-09: typed degraded response — keep executed
                    # SQL rows and continue to Metabase with the analytical
                    # series instead of failing the whole job.
                    code = str(exc.code or "forecasting_bridge_error").strip()
                    msg = str(exc.message or "Forecasting could not be completed.").strip()
                    details = exc.details if isinstance(exc.details, dict) else {}
                    forecasting_config = {
                        "status": "degraded",
                        "error_code": code,
                        "error_message": msg,
                        "details": details,
                    }
                    degraded_reason = f"{code}: {msg}" if code else msg
                    report.error_message = degraded_reason
                    report.chart_config = {
                        **(report.chart_config if isinstance(report.chart_config, dict) else {}),
                        "forecasting": forecasting_config,
                        "visualization_status": "forecast_degraded",
                        "fallback_used": True,
                        "fallback_reason": "forecasting_bridge_error",
                        "error_code": code,
                        "degraded_reason": degraded_reason,
                        "user_facing_message": msg,
                    }
                    report.ai_trace = _build_report_ai_trace(report)
                    report.save(update_fields=["error_message", "chart_config", "ai_trace", "updated_at"])
                    _append_trace(
                        job,
                        "FORECASTING",
                        "degraded",
                        {
                            "error_code": code,
                            "degraded_reason": degraded_reason,
                            "details_keys": sorted(details.keys()) if details else [],
                        },
                    )
                else:
                    forecast_columns = forecast_dataset.get("columns") if isinstance(forecast_dataset.get("columns"), list) else columns
                    forecast_rows = forecast_dataset.get("rows") if isinstance(forecast_dataset.get("rows"), list) else rows
                    visualization_sql = str(forecast_dataset.get("sql") or clean_sql)
                    forecasting_config = _forecasting_config(forecast_dataset)
                    report.query_result = {"columns": forecast_columns, "rows": forecast_rows}
                    report.row_count = len(forecast_rows)
                    report.chart_config = {
                        **(report.chart_config if isinstance(report.chart_config, dict) else {}),
                        "forecasting": forecasting_config,
                    }
                    report.ai_trace = _build_report_ai_trace(report)
                    report.save(update_fields=["query_result", "row_count", "chart_config", "ai_trace", "updated_at"])
                    _append_trace(
                        job,
                        "FORECASTING",
                        forecasting_config.get("status", "success"),
                        {
                            "output_summary": {
                                "actual_rows": len(forecasting_config.get("actual_rows", [])),
                                "forecast_rows": len(forecasting_config.get("forecast_rows", [])),
                                "horizon": forecasting_config.get("horizon"),
                                "model_used": forecasting_config.get("model_used"),
                            },
                            "degraded_reason": forecasting_config.get("degraded_reason") or None,
                        },
                    )

            mark_job_stage(job, status=statuses.VISUALIZING, stage=statuses.VISUALIZING, progress=85)
            viz_result = report.query_result if isinstance(report.query_result, dict) else {}
            viz_rows = viz_result.get("rows") if isinstance(viz_result.get("rows"), list) else []
            viz_columns = viz_result.get("columns") if isinstance(viz_result.get("columns"), list) else []
            chart_recommendation = _align_chart_contract_with_result(
                chart_recommendation,
                columns=viz_columns,
                rows=viz_rows,
            )
            viz = get_visualization_client().create_visualization(
                report=report,
                sql=visualization_sql,
                chart_payload=chart_recommendation,
                authorization_header=str(payload.get("authorization_header", "")),
            )
            if not isinstance(viz, dict) or not viz.get("success"):
                v_err = str((viz or {}).get("error") or "")
                detail = str((viz or {}).get("detail") or "").strip()
                if v_err in {"chart_contract_incompatible", "chart_contract_incompatible_locked"}:
                    msg = (
                        f"Visualization failed (chart contract incompatible with renderer). "
                        f"{detail or v_err}"
                    )
                else:
                    msg = detail or str((viz or {}).get("error") or "Visualization failed")
                return _finalize_failure(job, report, error_code=err.VISUALIZATION_FAILED, message=msg)

            degraded = str(viz.get("render_status") or "").lower() == "degraded" or str(
                viz.get("metabase_status") or ""
            ).lower() in {"unavailable", "down"}
            canonical_chart_type = str(
                chart_recommendation.get("type")
                or chart_recommendation.get("final_chart_type")
                or chart_recommendation.get("chart_type")
                or chart_recommendation.get("selected_chart_type")
                or ""
            ).strip().lower()
            viz_final_chart = str(viz.get("final_chart_type") or viz.get("chart_type") or "").strip().lower()
            if canonical_chart_type and canonical_chart_type != "table" and viz_final_chart == "table":
                return _finalize_failure(
                    job,
                    report,
                    error_code=err.VISUALIZATION_FAILED,
                    message="Visualization contract violation: renderer downgraded canonical chart to table.",
                )

            if degraded:
                report.metabase_question_id = None
                report.embed_url = ""
                report.chart_type = canonical_chart_type or viz_final_chart or report.chart_type or ""
                report.chart_config = {
                    **(report.chart_config if isinstance(report.chart_config, dict) else {}),
                    **_visualization_chart_config(viz, chart_recommendation),
                    "metabase_status": str(viz.get("metabase_status") or "unavailable"),
                    "render_status": str(viz.get("render_status") or "degraded"),
                    "user_message": str(viz.get("user_message") or "")
                    or "Chart configuration is ready but Metabase is unavailable",
                    "visualization_status": "degraded",
                }
                if forecasting_config:
                    report.chart_config["forecasting"] = forecasting_config
                report.status = VoiceReport.STATUS_EXECUTED
                report.ai_trace = _build_report_ai_trace(report)
                report.save(
                    update_fields=["metabase_question_id", "embed_url", "chart_type", "chart_config", "status", "ai_trace", "updated_at"]
                )
            else:
                report.metabase_question_id = int(viz.get("question_id")) if str(viz.get("question_id", "")).isdigit() else report.metabase_question_id
                report.embed_url = str(viz.get("embed_url") or "")
                report.chart_type = canonical_chart_type or viz_final_chart or report.chart_type or ""
                report.chart_config = {
                    **(report.chart_config if isinstance(report.chart_config, dict) else {}),
                    **_visualization_chart_config(viz, chart_recommendation),
                }
                if forecasting_config:
                    report.chart_config["forecasting"] = forecasting_config
                report.status = VoiceReport.STATUS_VISUALIZATION_CREATED if str(viz.get("status") or "success") == "success" else VoiceReport.STATUS_EXECUTED
                report.ai_trace = _build_report_ai_trace(report)
                report.save(update_fields=["metabase_question_id", "embed_url", "chart_type", "chart_config", "status", "ai_trace", "updated_at"])

            job.visualization_id = str(viz.get("question_id") or "")
            mark_job_stage(job, status=statuses.COMPLETED, stage=statuses.COMPLETED, progress=100)
            _append_trace(job, statuses.COMPLETED, str(viz.get("status") or "success"), {"visualization_id": job.visualization_id, "final_chart_type": report.chart_type})
            job.trace = job.trace if isinstance(job.trace, dict) else {}
            job.trace["finalized_at"] = timezone.now().isoformat()
            job.save(update_fields=["cleaned_question", "generated_sql", "execution_result_summary", "visualization_id", "trace", "updated_at", "status", "current_stage", "progress", "completed_at"])
            return job
    except Exception as exc:
        logger.exception("Unhandled exception in process_pipeline_job job_id=%s", job_id)
        job = VoicePipelineJob.objects.get(job_id=job_id)
        report = job.report
        return _finalize_failure(
            job,
            report,
            error_code=err.UNEXPECTED_ERROR,
            message=str(exc),
            fallback_trace=last_valid_trace,
        )
    finally:
        cache.delete(lock_key)


def _dispatch_pipeline_async(job_id: str) -> None:
    """Dispatch the pipeline to Celery (CRIT-02 of the audit).

    Synchronous execution from request handlers has been removed. Tests can
    short-circuit Celery via ``CELERY_TASK_ALWAYS_EAGER=true``.
    """

    from voice_reports.tasks import run_pipeline_async  # local import: avoid circular
    run_pipeline_async.delay(job_id)


def enqueue_text_job(*, request, workspace, text: str, payload: dict[str, Any]) -> tuple[VoiceReport, VoicePipelineJob]:
    report = VoiceReport(
        workspace=workspace,
        created_by=request.user,
        transcription=text,
        status=VoiceReport.STATUS_PENDING,
    )
    report.audio_file.save(
        f"text-input/{uuid.uuid4()}.txt",
        ContentFile(text.encode("utf-8")),
        save=False,
    )
    report.save()
    job_payload = dict(payload)
    job_payload["authorization_header"] = str(request.META.get("HTTP_AUTHORIZATION") or "")
    job = create_pipeline_job(
        report=report,
        input_type=VoicePipelineJob.INPUT_TYPE_TEXT,
        original_question=text,
        payload=job_payload,
    )
    mark_job_stage(job, status=statuses.QUEUED, stage=statuses.QUEUED, progress=1)
    _dispatch_pipeline_async(str(job.job_id))
    return report, job


def enqueue_audio_job(
    *,
    request,
    workspace,
    audio_path: str,
    audio_file_name: str = "",
    payload: dict[str, Any],
) -> tuple[VoiceReport, VoicePipelineJob]:
    report = VoiceReport.objects.create(
        workspace=workspace,
        created_by=request.user,
        audio_file=audio_file_name or audio_path,
        transcription="",
        status=VoiceReport.STATUS_PENDING,
        error_message="",
    )
    job_payload = dict(payload)
    job_payload["audio_path"] = audio_path
    job_payload["authorization_header"] = str(request.META.get("HTTP_AUTHORIZATION") or "")
    job = create_pipeline_job(
        report=report,
        input_type=VoicePipelineJob.INPUT_TYPE_AUDIO,
        payload=job_payload,
    )
    mark_job_stage(job, status=statuses.QUEUED, stage=statuses.QUEUED, progress=1)
    _dispatch_pipeline_async(str(job.job_id))
    return report, job

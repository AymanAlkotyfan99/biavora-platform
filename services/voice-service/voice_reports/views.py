"""
Voice Reports Views

API endpoints for voice-driven BI system.
Orchestrates requests through ai-service, query-service, forecasting, and visualization-service.
"""


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import status
from rest_framework.exceptions import UnsupportedMediaType
from django.shortcuts import get_object_or_404
from django.http import Http404
from django.conf import settings
from django.db.models import Sum
from django.db.models.functions import Coalesce
import logging
import os
import uuid
import requests

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
    _SHARED_CLIENT_AVAILABLE = True
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]
    _SHARED_CLIENT_AVAILABLE = False
from bi_platform_shared.logging_utils import log_with_safe_extra

from .models import VoiceReport, SQLEditHistory, VoicePipelineJob
from .constants import normalize_chart_type
from .services.audio_validation import validate_audio_upload
from .services.forecasting_bridge import ForecastingBridgeError, build_forecast_payload
from .services.ai_trace_service import build_ai_trace_payload
from .services.ai_service_client import get_ai_service_client
from .services.subscription_client import get_subscription_client
from .utils.trace_extraction import extract_pipeline_trace, is_valid_trace
from .application.orchestration_service import enqueue_audio_job, enqueue_text_job
from .infrastructure.auth_context import extract_identity_context
from .infrastructure.query_client import get_query_client, validate_sql_via_query_service
from .infrastructure.visualization_client import get_visualization_client
from .infrastructure.workspace_client import get_workspace_client
from users.permissions import IsManager, IsAnalyst, IsManagerOrAnalyst

logger = logging.getLogger(__name__)

LOW_CHANGE_TYPES = {
    "removed_noise",
    "normalized",
    "reduced_repetition",
    "removed_filler_words",
    "removed_noise_tags",
    "removed_noise_tokens",
    "normalized_repeated_characters",
    "normalized_punctuation",
    "normalized_whitespace",
    "removed_control_chars",
    "removed_malformed_symbols",
    "normalized_control_chars",
}
HIGH_ADJUSTMENT_TYPES = {"derived_field", "mapped_column"}


def build_report_ai_trace(report, *, embed_url: str = "") -> dict:
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
        embed_url=embed_url,
        chart_config=report.chart_config,
        error_message=report.error_message,
    )


def _build_async_accepted_response(*, report: VoiceReport, job: VoicePipelineJob):
    """CRIT-02: voice-service now returns 202 Accepted immediately.

    The pipeline runs on a Celery worker; clients poll
    ``GET /voice-reports/jobs/<job_id>/status/`` for progress.
    """

    return Response(
        {
            "success": True,
            "job_id": str(job.job_id),
            "report_id": report.id,
            "status": "queued",
            "stage": job.current_stage or "PENDING",
            "progress_pct": int(job.progress or 0),
            "status_url": f"/voice-reports/jobs/{job.job_id}/status/",
        },
        status=status.HTTP_202_ACCEPTED,
    )


def get_user_workspace(user):
    """
    Get the user's workspace based on their role.
    
    - Manager: Returns their owned workspace
    - Analyst/Executive: Returns workspace they're a member of
    """
    if user.role == 'manager':
        # Manager owns workspace
        workspace = user.owned_workspaces.first()
        return workspace
    else:
        # Analyst or Executive is a member
        membership = user.workspace_memberships.filter(status='active').first()
        if membership:
            return membership.workspace
        return None


def get_report_embed_url(report, metabase_service=None, *, authorization_header: str = ""):
    """
    Generate a fresh question embed URL through visualization-service.
    """
    if not report.metabase_question_id:
        return ""

    embed_url = get_visualization_client().get_question_embed_url(
        report.metabase_question_id,
        authorization_header=authorization_header,
    )
    if embed_url:
        return embed_url

    logger.warning(
        "Failed to generate dynamic embed URL through visualization-service for report=%s question=%s",
        report.id,
        report.metabase_question_id,
    )
    return ""


def _service_headers_with_auth(request):
    headers = {"Content-Type": "application/json"}
    auth_header = request.META.get("HTTP_AUTHORIZATION")
    if auth_header:
        headers["Authorization"] = auth_header
    return headers


def _resolve_dataset_binding_context(
    *,
    request,
    workspace_id: str,
    manager_id: str,
    explicit_dataset_id: str = "",
    explicit_source_id: str = "",
    explicit_table_name: str = "",
) -> dict[str, str]:
    """Resolve dataset binding from explicit request fields only.

    Phase 13 / GAP-08: do **not** auto-fetch the manager's default database
    from query-service when ``dataset_id`` / ``table_name`` are missing —
    that hid misconfiguration and picked an arbitrary dataset. Callers must
    pass ``dataset_id`` and ``table_name`` (or rely on workspace-local
    resolution elsewhere) explicitly.
    """

    dataset_id = str(explicit_dataset_id or "").strip()
    source_id = str(explicit_source_id or "").strip()
    table_name = str(explicit_table_name or "").strip()

    return {
        "workspace_id": str(workspace_id or "").strip(),
        "manager_id": str(manager_id or "").strip(),
        "dataset_id": dataset_id,
        "source_id": source_id or dataset_id,
        "table_name": table_name,
    }


def build_default_preprocessing_low(original_text: str = "") -> dict:
    normalized_text = str(original_text or "")
    return {
        "original_text": normalized_text,
        "cleaned_text": normalized_text,
        "spelling_corrected_text": normalized_text,
        "spelling_changes": [],
        "has_spelling_correction": False,
        "removed_filler_words": [],
        "changes": [],
    }


def build_default_preprocessing_high(corrected_query: str = "") -> dict:
    return {
        "corrected_query": str(corrected_query or ""),
        "term_corrections": [],
        "user_friendly_messages": [],
        "schema_used": {"tables": [], "columns": []},
        "schema_adjustments": [],
        "unresolved_terms": [],
        "unsupported_terms": [],
        "term_resolutions": [],
        "schema_validation_status": "unknown",
        "candidate_columns": {},
        "candidate_tables": [],
        "selected_table": "",
        "selected_columns": [],
        "skipped_schema_terms": [],
        "routing_decision": {},
    }


def build_default_pipeline_trace() -> dict:
    return {
        "request_metadata": {},
        "overall_status": {"status": "unknown"},
        "root_cause": {
            "root_cause_category": "unknown",
            "root_cause_detail": "",
            "analyst_recommended_fix": "",
        },
    }



def normalize_pipeline_trace(payload) -> dict:
    """Return persisted pipeline trace for API consumers without destroying in-flight shapes."""

    if not isinstance(payload, dict) or not payload:
        return build_default_pipeline_trace()
    if is_valid_trace(payload):
        return dict(payload)
    extracted = extract_pipeline_trace(payload) if isinstance(payload, dict) else {}
    if is_valid_trace(extracted):
        return extracted
    if isinstance(payload, dict) and (
        str(payload.get("trace_version") or "").strip()
        or len(payload) >= 3
    ):
        return dict(payload)
    logger.warning("Rejected invalid pipeline trace payload in views.normalize_pipeline_trace")
    return build_default_pipeline_trace()


def extract_pipeline_contract(
    pipeline_trace,
    *,
    confidence=None,
    confidence_breakdown=None,
    degraded=None,
) -> dict:
    trace = pipeline_trace if isinstance(pipeline_trace, dict) else {}
    overall = trace.get("overall_status", {}) if isinstance(trace.get("overall_status"), dict) else {}
    status_value = str(overall.get("status") or trace.get("status") or "").strip().lower()
    breakdown = confidence_breakdown or overall.get("confidence_breakdown") or trace.get("confidence_breakdown")
    score = confidence
    if score is None:
        score = overall.get("confidence", trace.get("confidence"))
    try:
        score = None if score is None else max(0.0, min(1.0, float(score)))
    except (TypeError, ValueError):
        score = None
    derived_degraded = degraded
    if derived_degraded is None:
        derived_degraded = status_value == "degraded" or any(
            isinstance(stage, dict)
            and (
                str(stage.get("status", "")).strip().lower() == "degraded"
                or bool(stage.get("degraded"))
            )
            for stage in trace.values()
        )
    return {
        "status": status_value or "unknown",
        "degraded": bool(derived_degraded),
        "confidence": score,
        "confidence_breakdown": breakdown if isinstance(breakdown, dict) else None,
    }


def extract_report_contract(report) -> dict:
    chart_config = report.chart_config if isinstance(report.chart_config, dict) else {}
    stored = chart_config.get("chart_contract", {}) if isinstance(chart_config.get("chart_contract"), dict) else {}
    if not stored and isinstance(chart_config.get("ai_contract"), dict):
        stored = chart_config.get("ai_contract", {})
    trace_contract = extract_pipeline_contract(report.pipeline_trace)
    return {
        **trace_contract,
        **{key: value for key, value in stored.items() if value is not None},
    }


def _flatten_schema_columns(columns_payload) -> list[str]:
    flattened: list[str] = []
    if isinstance(columns_payload, dict):
        for table_name, columns in columns_payload.items():
            normalized_table = str(table_name or "").strip()
            if not isinstance(columns, list):
                continue
            for column in columns:
                if isinstance(column, dict):
                    column_name = str(column.get("name", "")).strip()
                else:
                    column_name = str(column or "").strip()
                if not column_name:
                    continue
                if normalized_table:
                    flattened.append(f"{normalized_table}.{column_name}")
                else:
                    flattened.append(column_name)
        return flattened
    if isinstance(columns_payload, list):
        return [str(column) for column in columns_payload if str(column or "").strip()]
    return flattened


def _dedupe_non_empty(values) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    if not isinstance(values, list):
        return deduped
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        signature = normalized.lower()
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(normalized)
    return deduped


def _extract_term_corrections_from_mappings(mappings) -> list[dict]:
    corrections: list[dict] = []
    if not isinstance(mappings, list):
        return corrections
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        status = str(mapping.get("status", "")).strip().lower()
        if status not in {"mapped", "derivable"}:
            continue
        requested = str(mapping.get("requested", "")).strip()
        matched_column = str(mapping.get("matched_column", "")).strip()
        matched_table = str(mapping.get("matched_table", "")).strip()
        if not requested or not matched_column:
            continue
        corrections.append(
            {
                "original": requested,
                "corrected": matched_column,
                "matched_column": f"{matched_table}.{matched_column}" if matched_table else matched_column,
            }
        )
    return corrections


def _extract_schema_adjustments_from_mappings(mappings) -> list[dict]:
    adjustments: list[dict] = []
    if not isinstance(mappings, list):
        return adjustments
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        status = str(mapping.get("status", "")).strip().lower()
        requested = str(mapping.get("requested", "")).strip()
        matched_column = str(mapping.get("matched_column", "")).strip()
        matched_table = str(mapping.get("matched_table", "")).strip()
        if status == "mapped" and requested and matched_column:
            fully_qualified = f"{matched_table}.{matched_column}" if matched_table else matched_column
            adjustments.append(
                {
                    "type": "mapped_column",
                    "description": f"Mapped '{requested}' to '{fully_qualified}'.",
                }
            )
        elif status == "derivable" and requested and matched_column:
            fully_qualified = f"{matched_table}.{matched_column}" if matched_table else matched_column
            adjustments.append(
                {
                    "type": "derived_field",
                    "description": f"Derived '{requested}' from '{fully_qualified}'.",
                }
            )
    return adjustments


def _extract_schema_usage_from_mappings(mappings) -> tuple[list[str], list[str]]:
    tables: list[str] = []
    columns: list[str] = []
    if not isinstance(mappings, list):
        return tables, columns
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        status = str(mapping.get("status", "")).strip().lower()
        if status not in {"exact", "mapped", "derivable"}:
            continue
        matched_table = str(mapping.get("matched_table", "")).strip()
        matched_column = str(mapping.get("matched_column", "")).strip()
        if matched_table:
            tables.append(matched_table)
        if matched_column:
            columns.append(f"{matched_table}.{matched_column}" if matched_table else matched_column)
    return _dedupe_non_empty(tables), _dedupe_non_empty(columns)


def normalize_preprocessing_low(payload, fallback_text: str = "") -> dict:
    fallback = build_default_preprocessing_low(fallback_text)
    if not isinstance(payload, dict):
        return fallback

    original_text = str(payload.get("original_text") or fallback_text or "").strip()
    cleaned_text = str(payload.get("cleaned_text") or original_text).strip()
    spelling_corrected_text = str(payload.get("spelling_corrected_text") or cleaned_text or original_text).strip()
    has_spelling_correction = bool(payload.get("has_spelling_correction"))
    spelling_changes = payload.get("spelling_changes", [])
    if not isinstance(spelling_changes, list):
        spelling_changes = []
    removed_filler_words = payload.get("removed_filler_words", [])
    if not isinstance(removed_filler_words, list):
        removed_filler_words = []
    raw_changes = payload.get("changes", [])
    if not isinstance(raw_changes, list):
        raw_changes = []
    if not raw_changes:
        raw_changes = payload.get("detected_changes", [])
    normalized_changes = []
    if isinstance(raw_changes, list):
        for change in raw_changes:
            if not isinstance(change, dict):
                continue
            change_type = str(change.get("type", "normalized")).strip().lower()
            if change_type not in LOW_CHANGE_TYPES:
                change_type = "normalized"
            normalized_changes.append(
                {
                    "type": change_type,
                    "before": str(change.get("before", "")).strip(),
                    "after": str(change.get("after", "")).strip(),
                }
            )

    return {
        "original_text": original_text,
        "cleaned_text": cleaned_text,
        "spelling_corrected_text": spelling_corrected_text,
        "has_spelling_correction": has_spelling_correction,
        "spelling_changes": spelling_changes,
        "removed_filler_words": [str(word).strip() for word in removed_filler_words if str(word).strip()],
        "changes": normalized_changes,
    }


def normalize_preprocessing_high(payload, fallback_query: str = "") -> dict:
    fallback = build_default_preprocessing_high(fallback_query)
    if not isinstance(payload, dict):
        return fallback

    corrected_query = str(
        payload.get("corrected_query")
        or payload.get("final_query")
        or fallback_query
        or ""
    ).strip()
    selected_table = str(payload.get("selected_table", "")).strip()
    selected_columns = _dedupe_non_empty(
        payload.get("selected_columns", []) if isinstance(payload.get("selected_columns"), list) else []
    )
    mappings = payload.get("mappings", []) if isinstance(payload.get("mappings"), list) else []

    term_corrections = []
    raw_corrections = payload.get("term_corrections", [])
    if isinstance(raw_corrections, list):
        for correction in raw_corrections:
            if not isinstance(correction, dict):
                continue
            original_value = (
                correction.get("original")
                or correction.get("from")
                or correction.get("source")
                or ""
            )
            corrected_value = (
                correction.get("corrected")
                or correction.get("to")
                or correction.get("target")
                or ""
            )
            term_corrections.append(
                {
                    "original": str(original_value).strip(),
                    "corrected": str(corrected_value).strip(),
                    "matched_column": str(
                        correction.get("matched_column", "") or correction.get("matched", "")
                    ).strip(),
                    "from": str(original_value).strip(),
                    "to": str(corrected_value).strip(),
                    "type": str(correction.get("type", "")).strip(),
                    "message": str(correction.get("message", "")).strip(),
                }
            )
    if not term_corrections and mappings:
        term_corrections = _extract_term_corrections_from_mappings(mappings)

    raw_schema_used = payload.get("schema_used", {})
    tables = []
    columns = []
    if isinstance(raw_schema_used, dict):
        raw_tables = raw_schema_used.get("tables", [])
        if isinstance(raw_tables, list):
            tables = _dedupe_non_empty(raw_tables)
        columns = _flatten_schema_columns(raw_schema_used.get("columns", []))

    schema_adjustments = []
    raw_adjustments = payload.get("schema_adjustments", [])
    if isinstance(raw_adjustments, list):
        for adjustment in raw_adjustments:
            if not isinstance(adjustment, dict):
                continue
            adjustment_type = str(adjustment.get("type", "mapped_column")).strip().lower()
            if adjustment_type not in HIGH_ADJUSTMENT_TYPES:
                adjustment_type = "mapped_column"
            schema_adjustments.append(
                {
                    "type": adjustment_type,
                    "description": str(adjustment.get("description", "")).strip(),
                }
            )
    if not schema_adjustments and mappings:
        schema_adjustments = _extract_schema_adjustments_from_mappings(mappings)

    if not tables and selected_table:
        tables = [selected_table]
    if not columns and selected_columns:
        columns = [
            f"{selected_table}.{column}" if selected_table else column
            for column in selected_columns
        ]

    if not tables or not columns:
        mapping_tables, mapping_columns = _extract_schema_usage_from_mappings(mappings)
        if not tables and mapping_tables:
            tables = mapping_tables
        if not columns and mapping_columns:
            columns = mapping_columns

    tables = _dedupe_non_empty(tables)
    columns = _dedupe_non_empty(columns)
    if not selected_table and len(tables) == 1:
        selected_table = tables[0]
    if not selected_columns and columns:
        selected_columns = [
            column.split(".", 1)[1]
            if selected_table and column.lower().startswith(f"{selected_table.lower()}.")
            else column.split(".")[-1]
            for column in columns
        ]
        selected_columns = _dedupe_non_empty(selected_columns)

    return {
        "corrected_query": corrected_query,
        "term_corrections": term_corrections,
        "user_friendly_messages": [
            str(message).strip()
            for message in payload.get("user_friendly_messages", [])
            if str(message).strip()
        ]
        if isinstance(payload.get("user_friendly_messages"), list)
        else [],
        "schema_used": {
            "tables": tables,
            "columns": columns,
        },
        "schema_adjustments": schema_adjustments,
        "unresolved_terms": [
            str(term).strip()
            for term in payload.get("unresolved_terms", [])
            if str(term).strip()
        ]
        if isinstance(payload.get("unresolved_terms"), list)
        else [],
        "unsupported_terms": [
            str(term).strip()
            for term in payload.get("unsupported_terms", [])
            if str(term).strip()
        ]
        if isinstance(payload.get("unsupported_terms"), list)
        else [],
        "term_resolutions": payload.get("term_resolutions", [])
        if isinstance(payload.get("term_resolutions"), list)
        else [],
        "schema_validation_status": str(payload.get("schema_validation_status", "unknown")),
        "candidate_columns": payload.get("candidate_columns", {})
        if isinstance(payload.get("candidate_columns"), dict)
        else {},
        "candidate_tables": payload.get("candidate_tables", [])
        if isinstance(payload.get("candidate_tables"), list)
        else [],
        "selected_table": selected_table,
        "selected_columns": selected_columns,
        "skipped_schema_terms": [
            str(term).strip()
            for term in payload.get("skipped_schema_terms", [])
            if str(term).strip()
        ]
        if isinstance(payload.get("skipped_schema_terms"), list)
        else [],
        "routing_decision": payload.get("routing_decision", {})
        if isinstance(payload.get("routing_decision"), dict)
        else {},
    }


def _view_is_predictive(intent: dict) -> bool:
    payload = intent if isinstance(intent, dict) else {}
    forecast_payload = payload.get("forecast") if isinstance(payload.get("forecast"), dict) else {}
    return bool(
        str(payload.get("query_type") or payload.get("intent_type") or "").strip().lower() in {"predictive", "forecast", "forecasting"}
        or bool(payload.get("requires_forecast"))
        or bool(forecast_payload.get("enabled"))
    )


def _view_forecast_horizon(intent: dict) -> int | None:
    payload = intent if isinstance(intent, dict) else {}
    forecast_payload = payload.get("forecast") if isinstance(payload.get("forecast"), dict) else {}
    for candidate in (forecast_payload.get("horizon"), payload.get("forecast_horizon"), payload.get("horizon")):
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _view_forecasting_config(forecast_dataset: dict) -> dict:
    rows = forecast_dataset.get("rows") if isinstance(forecast_dataset.get("rows"), list) else []
    meta = forecast_dataset.get("meta") if isinstance(forecast_dataset.get("meta"), dict) else {}
    model_status = meta.get("forecasting_model_status") if isinstance(meta.get("forecasting_model_status"), dict) else {}
    actual_rows = [row for row in rows if isinstance(row, dict) and str(row.get("series_type") or "").lower() == "actual"]
    forecast_rows = [row for row in rows if isinstance(row, dict) and str(row.get("series_type") or "").lower() == "forecast"]
    fallback_reason = str(meta.get("fallback_reason") or model_status.get("fallback_reason") or "").strip()
    used_fallback = bool(model_status.get("used_fallback") or (fallback_reason and not forecast_rows))
    return {
        "enabled": True,
        "status": "degraded_success" if used_fallback or not forecast_rows else "success",
        "forecast_available": bool(meta.get("forecast_available") and forecast_rows),
        "actual_rows": actual_rows,
        "forecast_rows": forecast_rows,
        "series_type_column": "series_type",
        "horizon": int(meta.get("horizon") or len(forecast_rows) or 0),
        "target_column": meta.get("value_column"),
        "date_column": meta.get("time_column"),
        "model_used": model_status.get("provider") or model_status.get("model") or "timesfm",
        "degraded_reason": fallback_reason if used_fallback else "",
        "meta": meta,
    }


class VoiceUploadView(APIView):
    """
    Accept an audio request and run the canonical BI pipeline.

    voice-service validates and stores the uploaded audio, then delegates all AI
    work to ai-service through the orchestration service.
    """
    permission_classes = [IsAuthenticated, IsManager]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        try:
            if 'audio' not in request.FILES:
                return Response({'success': False, 'error': 'No audio file provided'}, status=status.HTTP_400_BAD_REQUEST)

            audio_file = request.FILES['audio']
            audio_validation = validate_audio_upload(audio_file)
            if not audio_validation.valid:
                log_with_safe_extra(
                    logger,
                    logging.WARNING,
                    "voice_upload_rejected",
                    extra={
                        "uploaded_filename": str(getattr(audio_file, "name", "") or ""),
                        "content_type": str(getattr(audio_file, "content_type", "") or ""),
                        "error_code": audio_validation.error_code,
                        "error": audio_validation.error,
                    },
                )
                return Response(
                    {
                        'success': False,
                        'error': audio_validation.error,
                        'error_code': audio_validation.error_code,
                        'status': 'rejected',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            identity = extract_identity_context(request)
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response({'success': False, 'error': 'User must belong to a workspace'}, status=status.HTTP_400_BAD_REQUEST)

            subscription_client = get_subscription_client()
            access_result = subscription_client.check_access(
                workspace_id=workspace.id,
                authorization_header=request.META.get('HTTP_AUTHORIZATION'),
                consume=True,
            )
            if not access_result.get('success'):
                return Response({'success': False, 'error': 'Subscription service unavailable. Please try again.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            if not access_result.get('allowed'):
                limit_message = 'You have reached your limit. Please subscribe.'
                return Response(
                    {
                        'success': False,
                        'error': limit_message,
                        'message': limit_message,
                        'remaining_requests': access_result.get('remaining_requests', 0),
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            audio_relative_dir = os.path.join("workspaces", str(workspace.id), "audio")
            audio_dir = os.path.join(str(settings.MEDIA_ROOT), audio_relative_dir)
            os.makedirs(audio_dir, exist_ok=True)
            original_name = os.path.basename(str(audio_file.name or f'audio{audio_validation.extension}'))
            if audio_validation.extension and not original_name.lower().endswith(audio_validation.extension):
                original_name = f'{original_name}{audio_validation.extension}'
            stored_filename = f'{uuid.uuid4()}_{original_name}'
            stored_name = os.path.join(audio_relative_dir, stored_filename).replace("\\", "/")
            audio_path = os.path.join(audio_dir, stored_filename)
            with open(audio_path, 'wb+') as destination:
                for chunk in audio_file.chunks():
                    destination.write(chunk)

            ctx = get_workspace_client().resolve(
                request=request,
                workspace_hint=identity.workspace_hint or str(workspace.id),
                user_id=identity.user_id,
                allow_local_resolver=get_user_workspace,
            )
            report, job = enqueue_audio_job(
                request=request,
                workspace=workspace,
                audio_path=audio_path,
                audio_file_name=stored_name,
                payload={
                    'workspace_id': ctx.workspace_id,
                    'manager_id': ctx.manager_id,
                    'dataset_id': str(request.data.get('dataset_id') or ctx.dataset_id).strip(),
                    'source_id': str(request.data.get('source_id') or ctx.source_id).strip(),
                    'table_name': str(request.data.get('table_name') or ctx.table_name).strip(),
                    'input_filename': original_name,
                    'input_content_type': audio_validation.content_type,
                },
            )
            return _build_async_accepted_response(report=report, job=job)
        except UnsupportedMediaType as e:
            return Response(
                {
                    'success': False,
                    'error': str(getattr(e, 'detail', e)),
                    'error_code': 'unsupported_media_type',
                },
                status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        except Exception as e:
            logger.error('Error in VoiceUploadView: %s', e, exc_info=True)
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TextQueryView(APIView):
    """
    Accept text and run the canonical BI pipeline.
    """
    permission_classes = [IsAuthenticated, IsManagerOrAnalyst]

    def post(self, request):
        try:
            text = (request.data.get('text') or '').strip()
            if not text:
                return Response({'success': False, 'error': 'Text is required'}, status=status.HTTP_400_BAD_REQUEST)

            identity = extract_identity_context(request)
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response({'success': False, 'error': 'User must belong to a workspace'}, status=status.HTTP_400_BAD_REQUEST)

            requested_workspace_id = request.data.get('workspace_id')
            if requested_workspace_id is not None and str(requested_workspace_id).strip() and str(requested_workspace_id) != str(workspace.id):
                return Response({'success': False, 'error': 'workspace_id does not match current user workspace'}, status=status.HTTP_403_FORBIDDEN)

            subscription_client = get_subscription_client()
            access_result = subscription_client.check_access(
                workspace_id=workspace.id,
                authorization_header=request.META.get('HTTP_AUTHORIZATION'),
                consume=True,
            )
            if not access_result.get('success'):
                return Response({'success': False, 'error': 'Subscription service unavailable. Please try again.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            if not access_result.get('allowed'):
                limit_message = 'You have reached your limit. Please subscribe.'
                return Response(
                    {
                        'success': False,
                        'error': limit_message,
                        'message': limit_message,
                        'remaining_requests': access_result.get('remaining_requests', 0),
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            ctx = get_workspace_client().resolve(
                request=request,
                workspace_hint=identity.workspace_hint or str(workspace.id),
                user_id=identity.user_id,
                allow_local_resolver=get_user_workspace,
            )
            report, job = enqueue_text_job(
                request=request,
                workspace=workspace,
                text=text,
                payload={
                    'workspace_id': ctx.workspace_id,
                    'manager_id': ctx.manager_id,
                    'dataset_id': str(request.data.get('dataset_id') or ctx.dataset_id).strip(),
                    'source_id': str(request.data.get('source_id') or ctx.source_id).strip(),
                    'table_name': str(request.data.get('table_name') or ctx.table_name).strip(),
                },
            )
            return _build_async_accepted_response(report=report, job=job)
        except Exception as e:
            logger.error('Error in TextQueryView: %s', e, exc_info=True)
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class QueryExecuteView(APIView):
    """
    Re-execute a stored SQL report through query-service and visualization-service.

    This endpoint exists for edited SQL/report reruns; it does not use the legacy
    shared execution engine and never talks to ClickHouse or Metabase directly.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, report_id):
        try:
            if report_id is None:
                return Response({'success': False, 'error': 'Invalid report_id: report_id cannot be null or undefined'}, status=status.HTTP_400_BAD_REQUEST)
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response({'success': False, 'error': 'User must belong to a workspace'}, status=status.HTTP_400_BAD_REQUEST)
            if request.user.role not in ['manager', 'analyst']:
                return Response({'success': False, 'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

            report = get_object_or_404(VoiceReport, id=report_id, workspace=workspace)
            sql = str(request.data.get('sql') or report.final_sql or '').strip()
            if not sql:
                return Response({'success': False, 'error': 'This report does not contain a SQL query.'}, status=status.HTTP_400_BAD_REQUEST)

            authorization_header = str(request.META.get('HTTP_AUTHORIZATION') or '')
            token = authorization_header.replace('Bearer ', '', 1).strip() if authorization_header else None
            is_valid, validation_error, clean_sql = validate_sql_via_query_service(
                sql=sql,
                token=token,
                workspace_id=str(workspace.id) if workspace else '',
            )
            if not is_valid:
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = validation_error
                report.ai_trace = build_report_ai_trace(report)
                report.save(update_fields=['status', 'error_message', 'ai_trace', 'updated_at'])
                return Response({'success': False, 'error': validation_error, 'status': 'failed'}, status=status.HTTP_400_BAD_REQUEST)

            # Phase 7 / CRIT-05: query-service resolves the ClickHouse
            # database from ``workspace_id``; we no longer pass a hardcoded
            # ``etl`` fallback through the request payload.
            query_result = get_query_client().execute(
                sql=clean_sql,
                authorization_header=str(request.META.get('HTTP_AUTHORIZATION') or ''),
                workspace_id=str(workspace.id) if workspace else '',
            )
            if not isinstance(query_result, dict) or not query_result.get('success') or query_result.get('status') == 'failed':
                error_message = str((query_result or {}).get('error') or 'Query execution failed')
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = error_message
                report.ai_trace = build_report_ai_trace(report)
                report.save(update_fields=['status', 'error_message', 'ai_trace', 'updated_at'])
                return Response({'success': False, 'error': error_message, 'status': 'failed'}, status=status.HTTP_400_BAD_REQUEST)

            rows = query_result.get('rows') if isinstance(query_result.get('rows'), list) else []
            columns = query_result.get('columns') if isinstance(query_result.get('columns'), list) else []
            chart_config = report.chart_config if isinstance(report.chart_config, dict) else {}
            chart_contract = request.data.get('chart_contract') if isinstance(request.data.get('chart_contract'), dict) else chart_config.get('chart_contract')
            if not isinstance(chart_contract, dict):
                chart_contract = {}
            if not chart_contract and report.chart_type:
                chart_contract = {
                    'chart_type': normalize_chart_type(report.chart_type, default=''),
                    'locked': True,
                    'reason': 'Stored upstream chart type from original AI response.',
                }

            intent = report.intent_json if isinstance(report.intent_json, dict) else {}
            requested_chart = str(chart_contract.get('chart_type') or chart_contract.get('selected_chart_type') or '').strip().lower()
            empty_result = bool(query_result.get('empty_result') or int(query_result.get('row_count') or len(rows)) == 0)
            predictive = _view_is_predictive(intent)

            report.final_sql = clean_sql
            report.sql_validated = True
            report.query_result = {'columns': columns, 'rows': rows}
            report.row_count = int(query_result.get('row_count') or len(rows))
            report.execution_time_ms = int(query_result.get('execution_time_ms') or 0)
            report.status = VoiceReport.STATUS_EXECUTED
            report.chart_config = {**chart_config, 'chart_contract': chart_contract, 'empty_result': empty_result}
            report.error_message = ''
            report.ai_trace = build_report_ai_trace(report)
            report.save(update_fields=['final_sql', 'sql_validated', 'query_result', 'row_count', 'execution_time_ms', 'status', 'chart_config', 'error_message', 'ai_trace', 'updated_at'])

            if empty_result and (predictive or requested_chart not in {'table', 'card'}):
                degraded_reason = 'SQL executed successfully but returned no rows. Possible reasons: filters too restrictive, date parsing issue, wrong grouping, or missing data.'
                report.error_message = degraded_reason
                report.chart_config = {
                    **(report.chart_config if isinstance(report.chart_config, dict) else {}),
                    'visualization_status': 'degraded_success',
                    'fallback_reason': 'empty_result',
                    'degraded_reason': degraded_reason,
                }
                report.ai_trace = build_report_ai_trace(report)
                report.save(update_fields=['error_message', 'chart_config', 'ai_trace', 'updated_at'])
                return Response({
                    'success': True,
                    'status': 'degraded_success',
                    'report_id': report.id,
                    'row_count': report.row_count,
                    'empty_result': True,
                    'chart_type': report.chart_type,
                    'embed_url': '',
                    'message': degraded_reason,
                })

            visualization_sql = clean_sql
            if predictive:
                try:
                    forecast_dataset = build_forecast_payload(
                        columns=columns,
                        rows=rows,
                        intent=intent,
                        horizon=_view_forecast_horizon(intent),
                    )
                except ForecastingBridgeError as exc:
                    error_message = f'{exc.code}: {exc.message}'
                    report.status = VoiceReport.STATUS_FAILED
                    report.error_message = error_message
                    report.ai_trace = build_report_ai_trace(report)
                    report.save(update_fields=['status', 'error_message', 'ai_trace', 'updated_at'])
                    return Response({'success': False, 'error': error_message, 'status': 'failed'}, status=status.HTTP_502_BAD_GATEWAY)
                forecast_columns = forecast_dataset.get('columns') if isinstance(forecast_dataset.get('columns'), list) else columns
                forecast_rows = forecast_dataset.get('rows') if isinstance(forecast_dataset.get('rows'), list) else rows
                visualization_sql = str(forecast_dataset.get('sql') or clean_sql)
                report.query_result = {'columns': forecast_columns, 'rows': forecast_rows}
                report.row_count = len(forecast_rows)
                report.chart_config = {
                    **(report.chart_config if isinstance(report.chart_config, dict) else {}),
                    'forecasting': _view_forecasting_config(forecast_dataset),
                }
                report.ai_trace = build_report_ai_trace(report)
                report.save(update_fields=['query_result', 'row_count', 'chart_config', 'ai_trace', 'updated_at'])

            viz = get_visualization_client().create_visualization(
                report=report,
                sql=visualization_sql,
                chart_payload=chart_contract,
                authorization_header=str(request.META.get('HTTP_AUTHORIZATION') or ''),
            )
            if not isinstance(viz, dict) or not viz.get('success'):
                error_message = str((viz or {}).get('error') or 'Visualization failed')
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = error_message
                report.ai_trace = build_report_ai_trace(report)
                report.save(update_fields=['status', 'error_message', 'ai_trace', 'updated_at'])
                return Response({'success': False, 'error': error_message, 'status': 'failed'}, status=status.HTTP_502_BAD_GATEWAY)

            report.metabase_question_id = int(viz.get('question_id')) if str(viz.get('question_id', '')).isdigit() else report.metabase_question_id
            report.embed_url = str(viz.get('embed_url') or '')
            report.chart_type = str(viz.get('final_chart_type') or viz.get('chart_type') or report.chart_type or '')
            report.chart_config = {
                **(report.chart_config if isinstance(report.chart_config, dict) else {}),
                'requested_chart_type': viz.get('requested_chart_type') or requested_chart,
                'final_chart_type': viz.get('final_chart_type') or report.chart_type,
                'effective_chart_type': viz.get('final_chart_type') or report.chart_type,
                'fallback_used': bool(viz.get('fallback_used')),
                'fallback_reason': viz.get('fallback_reason'),
                'visualization_status': viz.get('status', 'success'),
                'visualization_trace': viz.get('trace', []),
            }
            report.status = VoiceReport.STATUS_VISUALIZATION_CREATED if str(viz.get('status') or 'success') == 'success' else VoiceReport.STATUS_EXECUTED
            report.error_message = ''
            report.ai_trace = build_report_ai_trace(report)
            report.save(update_fields=['metabase_question_id', 'embed_url', 'chart_type', 'chart_config', 'status', 'error_message', 'ai_trace', 'updated_at'])

            return Response({
                'success': True,
                'status': viz.get('status', 'success'),
                'report_id': report.id,
                'row_count': report.row_count,
                'execution_time_ms': report.execution_time_ms,
                'empty_result': False,
                'chart_type': report.chart_type,
                'requested_chart_type': viz.get('requested_chart_type'),
                'final_chart_type': viz.get('final_chart_type') or report.chart_type,
                'fallback_used': bool(viz.get('fallback_used')),
                'fallback_reason': viz.get('fallback_reason'),
                'embed_url': report.embed_url,
                'metabase_question_id': report.metabase_question_id,
            })
        except Exception as e:
            logger.error('Error in QueryExecuteView: %s', e, exc_info=True)
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SQLEditView(APIView):
    """
    Edit SQL query (Analyst only).
    """
    permission_classes = [IsAuthenticated, IsAnalyst]
    
    def put(self, request, report_id):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace
            )
            
            new_sql = request.data.get('sql')
            
            if not new_sql:
                return Response(
                    {'success': False, 'error': 'SQL is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate new SQL via query-service (CRIT-04: voice-service no longer
            # owns SQL safety; query-service is the single SQL authority).
            authorization_header = str(request.META.get('HTTP_AUTHORIZATION') or '')
            token = authorization_header.replace('Bearer ', '', 1).strip() if authorization_header else None
            is_valid, error_msg, clean_sql = validate_sql_via_query_service(
                sql=str(new_sql),
                token=token,
                workspace_id=str(workspace.id) if workspace else '',
            )

            if not is_valid:
                return Response(
                    {'success': False, 'error': error_msg},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Save old SQL for history
            old_sql = report.final_sql
            
            # Update report
            report.final_sql = clean_sql
            report.sql_edited = True
            report.edited_by = request.user
            report.sql_validated = True
            report.status = VoiceReport.STATUS_PENDING  # Needs re-execution
            report.ai_trace = build_report_ai_trace(report)
            report.save()
            
            # TODO: Create history entry when ReportHistory model is added
            # ReportHistory.objects.create(
            #     report=report,
            #     action='sql_edited',
            #     performed_by=request.user,
            #     changes={
            #         'old_sql': old_sql,
            #         'new_sql': clean_sql
            #     }
            # )
            
            logger.info(f"Report {report.id} SQL edited by analyst {request.user.email}")
            
            return Response({
                'success': True,
                'report_id': report.id,
                'sql': clean_sql,
                'message': 'SQL updated successfully. Ready to re-execute.'
            })
        
        except Exception as e:
            logger.error(f"Error in SQLEditView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ReportListView(APIView):
    """
    List all reports for workspace.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            reports = VoiceReport.objects.filter(
                workspace=workspace
            ).order_by('-created_at')
            
            # Filter by role
            if request.user.role == 'manager':
                # Manager sees only their own reports
                reports = reports.filter(created_by=request.user)
            # Analyst and Executive see all workspace reports
            
            data = []
            for report in reports:
                ai_contract = extract_report_contract(report)
                data.append({
                    'id': report.id,
                    'transcription': report.transcription,
                    'status': report.status,
                    'created_at': report.created_at,
                    'created_by': report.created_by.email,
                    'chart_type': report.chart_type,
                    'final_chart_type': ai_contract.get('final_chart_type') or report.chart_type,
                    'row_count': report.row_count,
                    'execution_time_ms': report.execution_time_ms,
                    'sql': report.final_sql,
                    'embed_url': '',
                    'metabase_question_id': report.metabase_question_id,
                    'metabase_display': (report.chart_config or {}).get('metabase_display') if isinstance(report.chart_config, dict) else None,
                    'confidence': ai_contract.get('confidence'),
                    'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                    'degraded': ai_contract.get('degraded'),
                    'can_edit': request.user.role == 'analyst'
                })
            logger.info(
                "Report list loaded for user=%s workspace=%s count=%s",
                request.user.id,
                workspace.id,
                len(data)
            )
            
            return Response({
                'success': True,
                'reports': data,
                'count': len(data)
            })
        
        except Exception as e:
            logger.error(f"Error in ReportListView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ReportDetailView(APIView):
    """
    Get detailed report information.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, report_id):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace
            )
            
            # TODO: Get history when ReportHistory model is added
            # history = ReportHistory.objects.filter(report=report).order_by('-timestamp')
            # history_data = [{
            #     'action': h.action,
            #     'performed_by': h.performed_by.email,
            #     'timestamp': h.timestamp,
            #     'changes': h.changes
            # } for h in history]
            history_data = []  # Placeholder until ReportHistory is added
            auth_header = str(request.META.get('HTTP_AUTHORIZATION') or '')
            embed_url = get_report_embed_url(report, authorization_header=auth_header)
            preprocessing_low = normalize_preprocessing_low(
                report.preprocessing_low,
                fallback_text=report.transcription,
            )
            preprocessing_high = normalize_preprocessing_high(
                report.preprocessing_high,
                fallback_query=preprocessing_low.get("cleaned_text", report.transcription),
            )
            pipeline_trace = normalize_pipeline_trace(report.pipeline_trace)
            ai_contract = extract_report_contract(report)
            ai_trace = build_report_ai_trace(report, embed_url=embed_url)
            if report.ai_trace != ai_trace:
                report.ai_trace = ai_trace
                report.save(update_fields=['ai_trace', 'updated_at'])
            
            return Response({
                'success': True,
                'report': {
                    'id': report.id,
                    'transcription': report.transcription,
                    'intent': report.intent_json,
                    'generated_sql': report.generated_sql,
                    'final_sql': report.final_sql,
                    'status': report.status,
                    'sql_validated': report.sql_validated,
                    'sql_edited': report.sql_edited,
                    'query_result': report.query_result,
                    'row_count': report.row_count,
                    'execution_time_ms': report.execution_time_ms,
                    'chart_type': report.chart_type,
                    'final_chart_type': ai_contract.get('final_chart_type') or report.chart_type,
                    'selected_chart_type': ai_contract.get('selected_chart_type'),
                    'metabase_question_id': report.metabase_question_id,
                    'metabase_dashboard_id': report.metabase_dashboard_id,
                    'embed_url': embed_url,
                    'visualization_status': (report.chart_config or {}).get('visualization_status') if isinstance(report.chart_config, dict) else None,
                    'metabase_display': (report.chart_config or {}).get('metabase_display') if isinstance(report.chart_config, dict) else None,
                    'preprocessing_low': preprocessing_low,
                    'preprocessing_high': preprocessing_high,
                    'pipeline_trace': pipeline_trace,
                    'ai_trace': ai_trace,
                    'confidence': ai_contract.get('confidence'),
                    'confidence_breakdown': ai_contract.get('confidence_breakdown'),
                    'degraded': ai_contract.get('degraded'),
                    'overall_status': pipeline_trace.get('overall_status'),
                    'root_cause': pipeline_trace.get('root_cause'),
                    'error_message': report.error_message,
                    'created_at': report.created_at,
                    'created_by': report.created_by.email,
                    'edited_by': report.edited_by.email if report.edited_by else None,
                    'history': history_data
                }
            })
        
        except Exception as e:
            logger.error(f"Error in ReportDetailView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request, report_id):
        """Delete report (Manager only)."""
        if request.user.role != 'manager':
            return Response(
                {'success': False, 'error': 'Only managers can delete reports'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace,
                created_by=request.user  # Can only delete own reports
            )
            
            report.delete()
            
            logger.info(f"Report {report_id} deleted by {request.user.email}")
            
            return Response({
                'success': True,
                'message': 'Report deleted successfully'
            })
        
        except Http404:
            return Response(
                {'success': False, 'error': 'Report not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error deleting report: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AITraceDetailView(APIView):
    """
    Analyst-facing explainability payload for the full AI pipeline.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, report_id):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace
            )
            ai_trace = build_report_ai_trace(report, embed_url='')

            if report.ai_trace != ai_trace:
                report.ai_trace = ai_trace
                report.save(update_fields=['ai_trace', 'updated_at'])

            return Response({
                'success': True,
                'report_id': report.id,
                'ai_trace': ai_trace,
            })
        except Exception as e:
            logger.error("Error in AITraceDetailView: %s", e, exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WorkspaceDashboardView(APIView):
    """
    Get workspace dashboard for embedded viewing (Executive).
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get dashboard ID from any report
            report = VoiceReport.objects.filter(
                workspace=workspace,
                metabase_dashboard_id__isnull=False
            ).first()
            
            if not report:
                return Response({
                    'success': False,
                    'error': 'No dashboard available yet. Create some reports first.'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Generate fresh embed URL through visualization-service.
            embed_url = get_visualization_client().get_dashboard_embed_url(
                report.metabase_dashboard_id,
                authorization_header=str(request.META.get('HTTP_AUTHORIZATION') or ''),
            )
            if not embed_url:
                return Response({
                    'success': False,
                    'error': 'Failed to generate dashboard embed URL'
                }, status=status.HTTP_502_BAD_GATEWAY)
            
            return Response({
                'success': True,
                'dashboard_url': embed_url,
                'dashboard_id': report.metabase_dashboard_id
            })
        
        except Exception as e:
            logger.error(f"Error in WorkspaceDashboardView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DashboardStatsView(APIView):
    """
    Return dashboard counters for the current user scope.
    """
    permission_classes = [IsAuthenticated]

    SUCCESS_STATUSES = (
        VoiceReport.STATUS_VISUALIZATION_CREATED,
        VoiceReport.STATUS_EXECUTED,
        VoiceReport.STATUS_COMPLETED,  # legacy
    )

    PROCESSING_STATUSES = (
        VoiceReport.STATUS_PENDING,
        VoiceReport.STATUS_PROCESSING,
        VoiceReport.STATUS_PENDING_EXECUTION,  # legacy
        VoiceReport.STATUS_EXECUTING,  # legacy
    )

    def get(self, request):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            reports = VoiceReport.objects.filter(workspace=workspace)

            # Preserve list visibility semantics:
            # managers only see their own reports; others see workspace reports.
            if request.user.role == 'manager':
                reports = reports.filter(created_by=request.user)

            total_reports = reports.count()
            completed_reports = reports.filter(status__in=self.SUCCESS_STATUSES).count()
            failed_reports = reports.filter(status=VoiceReport.STATUS_FAILED).count()
            processing_reports = reports.filter(status__in=self.PROCESSING_STATUSES).count()
            total_rows = reports.aggregate(
                total_rows=Coalesce(Sum('row_count'), 0)
            )['total_rows']

            payload = {
                'success': True,
                'total_reports': total_reports,
                'completed_reports': completed_reports,
                'failed_reports': failed_reports,
                'processing_reports': processing_reports,
                'total_rows': int(total_rows or 0),
            }
            logger.info(
                "Dashboard stats loaded for user=%s workspace=%s payload=%s",
                request.user.id,
                workspace.id,
                payload
            )
            return Response(payload)
        except Exception as e:
            logger.error("Error in DashboardStatsView: %s", e, exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class JobStatusView(APIView):
    """Canonical async job status endpoint (CRIT-02).

    Returns the contract documented in the audit roadmap:

        {
            "job_id": str,
            "status": str,            # PENDING|QUEUED|...|COMPLETED|FAILED
            "stage": str,             # current pipeline stage
            "progress_pct": int,      # 0..100
            "error": {                # null when there is no error
                "code": str,
                "message": str,
            } | null,
        }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        workspace = get_user_workspace(request.user)
        if not workspace:
            return Response(
                {'success': False, 'error': 'User must belong to a workspace'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        job = get_object_or_404(VoicePipelineJob, job_id=job_id, workspace=workspace)
        error_payload = None
        if job.error_code or job.error_message:
            error_payload = {
                'code': job.error_code or 'UNKNOWN',
                'message': job.error_message or '',
            }
        return Response(
            {
                'success': True,
                'job_id': str(job.job_id),
                'report_id': job.report_id,
                'status': job.status,
                'stage': job.current_stage or job.status,
                'progress_pct': int(job.progress or 0),
                'error': error_payload,
            }
        )


class HealthCheckView(APIView):
    """
    Health check for all services.
    """
    permission_classes = []  # Public endpoint
    
    def get(self, request):
        """Check connectivity to ai-service, query-service and visualization-service."""
        health = {
            'ai_service': False,
            'query_service': False,
            'visualization_service': False,
        }
        
        try:
            ai_service = get_ai_service_client()
            url = f"{ai_service.base_url}/health/"
            if _SHARED_CLIENT_AVAILABLE:
                response = get_default_client().get(url, timeout=(2.0, 5.0), attach_internal_api_key=False)
            else:
                response = requests.get(url, timeout=5)
            health['ai_service'] = response.status_code == 200
        except Exception:
            pass

        try:
            query_service_url = os.getenv('QUERY_SERVICE_URL', 'http://query-service:8006').rstrip('/')
            url = f"{query_service_url}/query/health/"
            if _SHARED_CLIENT_AVAILABLE:
                response = get_default_client().get(url, timeout=(2.0, 5.0), attach_internal_api_key=False)
            else:
                response = requests.get(url, timeout=5)
            health['query_service'] = response.status_code == 200
        except Exception:
            pass

        try:
            health['visualization_service'] = get_visualization_client().health()
        except Exception:
            pass
        
        all_healthy = all(health.values())
        
        return Response({
            'success': all_healthy,
            'services': health,
            'message': 'All services healthy' if all_healthy else 'Some services unavailable'
        }, status=status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE)







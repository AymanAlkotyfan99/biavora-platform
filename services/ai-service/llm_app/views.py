import json
import logging
import os

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dagster_pipeline.jobs import run_full_ai_pipeline
from shared.chart_contract import build_chart_contract_from_intent
from shared.internal_api_auth import require_internal_api_key

logger = logging.getLogger(__name__)

_INTENT_FAILURE_DETAILS_MAX_CHARS = int(os.getenv("AI_INTENT_FAILURE_DETAILS_MAX_CHARS", "24000"))


def _load_forecasting_symbols():
    try:
        from forecasting.pipeline import ForecastingError, build_forecast_dataset, detect_forecast_request
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Forecasting module not found. Check PYTHONPATH and container mount."
        ) from exc
    return ForecastingError, build_forecast_dataset, detect_forecast_request


def _canonical_status(status_value: object) -> str:
    normalized = str(status_value or "").strip().lower()
    if normalized == "degraded":
        return "degraded_success"
    if normalized in {"success", "failed", "rejected"}:
        return normalized
    return "failed"


def _canonical_classification(classification_payload: dict) -> dict:
    label = str(classification_payload.get("classification") or classification_payload.get("question_type") or "").strip().lower()
    class_type = str(classification_payload.get("classification_type") or classification_payload.get("type") or "").strip().upper()
    if label in {"predictive", "forecast", "forecasting"} or class_type == "PREDICTIVE":
        canonical_type = "predictive"
    elif label == "analytical" or class_type == "ANALYTICAL":
        canonical_type = "analytical"
    elif label in {"conversational", "non_data"} or class_type == "NON_DATA":
        canonical_type = "non_data"
    else:
        canonical_type = "invalid"
    return {
        "is_analytical": canonical_type in {"analytical", "predictive"},
        "is_predictive": canonical_type == "predictive",
        "type": canonical_type,
        "confidence": float(classification_payload.get("confidence", 0.0) or 0.0),
        "reasoning": str(classification_payload.get("classification_reason") or classification_payload.get("reasoning") or ""),
    }


def _canonical_chart_contract(chart_contract: dict) -> dict:
    chart_type = str(
        chart_contract.get("type")
        or chart_contract.get("final_chart_type")
        or chart_contract.get("chart_type")
        or chart_contract.get("selected_chart_type")
        or ""
    ).strip().lower()
    y_axis = chart_contract.get("y_axis")
    if isinstance(y_axis, str):
        y_axis = [y_axis]
    return {
        "type": chart_type,
        "chart_type": chart_type,
        "final_chart_type": chart_type,
        "x_axis": chart_contract.get("x_axis"),
        "y_axis": y_axis if isinstance(y_axis, list) else [],
        "series": chart_contract.get("series"),
        "label_column": chart_contract.get("label_column"),
        "value_column": chart_contract.get("value_column"),
        "metric_type": chart_contract.get("metric_type"),
        "time_column": chart_contract.get("time_column"),
        "time_grain": chart_contract.get("time_grain"),
        "locked": bool(chart_contract.get("locked", chart_contract.get("explicit_chart_lock", chart_contract.get("chart_lock", True)))),
        "chart_lock": bool(chart_contract.get("chart_lock", chart_contract.get("explicit_chart_lock", chart_contract.get("locked", True)))),
        "explicit_chart_lock": bool(chart_contract.get("explicit_chart_lock", chart_contract.get("locked", True))),
        "fallback_allowed": bool(chart_contract.get("fallback_allowed", False)),
        "reason": str(chart_contract.get("reason") or chart_contract.get("chart_reason") or ""),
    }


def _canonical_sql_review(review_payload: dict) -> dict:
    status_value = str(review_payload.get("status") or "").strip().lower()
    return {
        "approved": status_value in {"approved", "corrected", "passed", "fallback_compiler"},
        "reason": "; ".join(str(note) for note in review_payload.get("notes", []) if str(note).strip())
        or str(review_payload.get("reason") or review_payload.get("reason_category") or ""),
        "corrected_sql": review_payload.get("reviewed_sql") if status_value == "corrected" else None,
    }


@csrf_exempt
@require_internal_api_key
def intent_test_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    question = (data.get("question") or "").strip()
    if not question:
        return JsonResponse({"error": "No question provided"}, status=400)
    user_id = (data.get("user_id") or "").strip()
    manager_id = (data.get("manager_id") or "").strip()
    dataset_id = (data.get("dataset_id") or "").strip()
    source_id = (data.get("source_id") or "").strip()
    workspace_id = (data.get("workspace_id") or "").strip()
    report_id = (data.get("report_id") or "").strip()
    table_name = (data.get("table_name") or "").strip()

    pipeline_result = run_full_ai_pipeline(
        text=question,
        user_id=(user_id or None),
        manager_id=(manager_id or user_id or None),
        dataset_id=(dataset_id or None),
        source_id=(source_id or None),
        workspace_id=(workspace_id or None),
        report_id=(report_id or None),
        table_name=(table_name or None),
    )

    preprocess_low = (
        pipeline_result.get("preprocess", {})
        if isinstance(pipeline_result.get("preprocess"), dict)
        else {}
    )
    preprocess_high = (
        pipeline_result.get("preprocess_high", {})
        if isinstance(pipeline_result.get("preprocess_high"), dict)
        else {}
    )
    query_execution = (
        pipeline_result.get("query_execution", {})
        if isinstance(pipeline_result.get("query_execution"), dict)
        else {}
    )
    visualization = (
        pipeline_result.get("visualization", {})
        if isinstance(pipeline_result.get("visualization"), dict)
        else {}
    )
    forecasting = (
        pipeline_result.get("forecasting", {})
        if isinstance(pipeline_result.get("forecasting"), dict)
        else {}
    )
    final_route = str(pipeline_result.get("final_route", "")).strip().lower()
    selected_chart_type = str(visualization.get("selected_chart_type", "")).strip().lower()
    reason_chart_selected = str(visualization.get("reason_chart_selected", "")).strip()
    chart_locked = bool(visualization.get("chart_locked", False))
    chart_selector_source = str(visualization.get("chart_selector_source", "")).strip()
    chart_selector_model = str(visualization.get("chart_selector_model", "")).strip()
    chart_selector_confidence = visualization.get("chart_selector_confidence", 0.0)
    chart_payload = visualization.get("downstream_result")
    if selected_chart_type:
        base_payload = chart_payload if isinstance(chart_payload, dict) else {}
        chart_payload = {
            **base_payload,
            "type": selected_chart_type,
            "chart_type": selected_chart_type,
            "reason_chart_selected": reason_chart_selected or str(base_payload.get("reason_chart_selected", "")).strip(),
            "chart_locked": chart_locked,
            "chart_selector_source": chart_selector_source,
            "chart_selector_model": chart_selector_model,
            "chart_selector_confidence": chart_selector_confidence,
        }
    if final_route == "forecasting" and not chart_payload:
        downstream = forecasting.get("downstream_result", {}) if isinstance(forecasting.get("downstream_result"), dict) else {}
        chart_payload = downstream.get("visualization_payload")
    intent = (
        pipeline_result.get("intent_extraction", {})
        if isinstance(pipeline_result.get("intent_extraction"), dict)
        else {}
    )

    if str(pipeline_result.get("status", "")).strip().lower() in {"success", "degraded"}:
        normalized_intent = (
            query_execution.get("normalized_intent", {})
            if isinstance(query_execution.get("normalized_intent"), dict)
            else {}
        )
        classification_payload = (
            pipeline_result.get("intent", {})
            if isinstance(pipeline_result.get("intent"), dict)
            else {}
        )
        route_name = str(pipeline_result.get("final_route", "")).strip().lower()
        if isinstance(normalized_intent, dict):
            normalized_intent = {
                **normalized_intent,
                "question_type": (
                    str(classification_payload.get("question_type") or "").strip().lower()
                    or ("predictive" if route_name == "forecasting" else "analytical")
                ),
                "requires_forecast": bool(
                    classification_payload.get("requires_forecast")
                    or route_name == "forecasting"
                    or str(normalized_intent.get("intent_type", "")).strip().lower() == "predictive"
                ),
            }
        validated_intent = (
            intent.get("validated_intent", {})
            if isinstance(intent.get("validated_intent"), dict)
            else {}
        )
        chart_contract = build_chart_contract_from_intent(
            normalized_intent if isinstance(normalized_intent, dict) else validated_intent,
            result_shape=query_execution.get("result_preview") if isinstance(query_execution.get("result_preview"), dict) else {},
            visualization=visualization,
            user_text=question,
            final_route=final_route,
        )
        canonical_classification = _canonical_classification(classification_payload)
        canonical_chart = _canonical_chart_contract(chart_contract)
        canonical_review = _canonical_sql_review(query_execution.get("sql_review", {}) if isinstance(query_execution.get("sql_review"), dict) else {})
        schema_mapping = {
            "selected_table": str((normalized_intent or validated_intent or {}).get("table", "")) if isinstance((normalized_intent or validated_intent), dict) else "",
            "selected_columns": query_execution.get("referenced_columns", []) if isinstance(query_execution.get("referenced_columns"), list) else [],
            "resolved_terms": {},
            "unresolved_terms": preprocess_high.get("unresolved_terms", []) if isinstance(preprocess_high.get("unresolved_terms"), list) else [],
            "schema_valid": bool(preprocess_high.get("schema_valid", True)),
        }
        payload = {
            "status": _canonical_status(pipeline_result.get("status")),
            "error": False,
            "question": question,
            "normalized_question": str(preprocess_low.get("cleaned_text") or question),
            "input_type": "text",
            "classification": canonical_classification,
            "schema_mapping": schema_mapping,
            "chart_contract": canonical_chart,
            "sql_review": canonical_review,
            "trace": pipeline_result.get("pipeline_trace", {}),
            "original_question": question,
            "cleaned_question": str(preprocess_low.get("cleaned_text") or question),
            "legacy_classification": (
                str(classification_payload.get("question_type") or "").strip().lower()
                or ("predictive" if route_name == "forecasting" else "analytical")
            ),
            "intent": normalized_intent or validated_intent,
            "generated_intent": normalized_intent or validated_intent,
            "chart_recommendation": chart_contract,
            "validated_intent": validated_intent,
            "sql": query_execution.get("sql_query", ""),
            "generated_sql": query_execution.get("generated_sql", query_execution.get("sql_query", "")),
            "reviewed_sql": query_execution.get("reviewed_sql", query_execution.get("sql_query", "")),
            "legacy_sql_review": query_execution.get("sql_review", {}),
            "sql_validation": {
                "status": (
                    "valid"
                    if bool(query_execution.get("reviewed_sql") or query_execution.get("sql_query"))
                    else "invalid"
                ),
                "details": query_execution.get("sql_review", {}),
            },
            "chart": chart_payload,
            "selected_chart_type": chart_contract.get("selected_chart_type", ""),
            "chart_config": chart_contract,
            "confidence": pipeline_result.get(
                "confidence",
                (
                    pipeline_result.get("intent", {})
                    if isinstance(pipeline_result.get("intent"), dict)
                    else {}
                ).get("confidence", 0.5),
            ),
            "confidence_breakdown": pipeline_result.get("confidence_breakdown"),
            "raw_intent": intent.get("extracted_intent", {}),
            "preprocessing_low": preprocess_low,
            "preprocessing_high": preprocess_high,
            "pipeline_trace": pipeline_result.get("pipeline_trace"),
            "trace": pipeline_result.get("pipeline_trace"),
            "overall_status": pipeline_result.get("overall_status"),
            "root_cause": pipeline_result.get("root_cause"),
            "dagster_runtime": pipeline_result.get("dagster_runtime"),
            "final_route": pipeline_result.get("final_route"),
            "final_user_message": pipeline_result.get("final_user_message"),
        }
        return JsonResponse(payload)

    payload = {
        "status": _canonical_status(pipeline_result.get("status") or "failed"),
        "error": True,
        "question": question,
        "normalized_question": str(preprocess_low.get("cleaned_text") or question),
        "input_type": "text",
        "classification": _canonical_classification(
            pipeline_result.get("intent", {}) if isinstance(pipeline_result.get("intent"), dict) else {}
        ),
        "schema_mapping": {
            "selected_table": "",
            "selected_columns": [],
            "resolved_terms": {},
            "unresolved_terms": [],
            "schema_valid": False,
        },
        "intent": {},
        "chart_contract": _canonical_chart_contract({}),
        "sql": "",
        "sql_review": {"approved": False, "reason": pipeline_result.get("message", "Pipeline failed."), "corrected_sql": None},
        "trace": pipeline_result.get("pipeline_trace", {}),
        "error_code": pipeline_result.get("stage", "pipeline_failed"),
        "message": pipeline_result.get("message", "Pipeline failed."),
        "stage": pipeline_result.get("stage", "pipeline"),
        "retryable": False,
        "details": pipeline_result,
        "preprocessing_low": preprocess_low,
        "preprocessing_high": preprocess_high,
        "pipeline_trace": pipeline_result.get("pipeline_trace"),
        "overall_status": pipeline_result.get("overall_status"),
        "root_cause": pipeline_result.get("root_cause"),
        "dagster_runtime": pipeline_result.get("dagster_runtime"),
        "final_route": pipeline_result.get("final_route"),
        "final_user_message": pipeline_result.get("final_user_message"),
    }
    if payload.get("error"):
        # Historically this endpoint returned HTTP 422 with the full pipeline dump
        # in ``details``, which confused clients (non-JSON 422 tooling) and produced
        # huge payloads. Failures are signaled by ``error: true``; HTTP 200 keeps
        # voice-service and gateways on a single success path for transport errors.
        details = payload.get("details")
        if isinstance(details, dict):
            try:
                raw = json.dumps(details, default=str)
            except TypeError:
                raw = str(details)
            if len(raw) > _INTENT_FAILURE_DETAILS_MAX_CHARS:
                payload = {
                    **payload,
                    "details_truncated": True,
                    "details_size_chars": len(raw),
                    "details": {
                        "message": "Full pipeline details omitted; see logs or raise AI_INTENT_FAILURE_DETAILS_MAX_CHARS.",
                        "stage": details.get("stage"),
                        "status": details.get("status"),
                        "message_short": str(details.get("message", ""))[:2000],
                    },
                }
        logger.warning(
            "intent_pipeline_failed status=%s stage=%s question_len=%s",
            payload.get("status"),
            payload.get("stage"),
            len(question or ""),
        )
        return JsonResponse(payload, status=200)
    return JsonResponse(payload)


@csrf_exempt
@require_internal_api_key
def forecast_detect_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    try:
        _, _, detect_forecast_request = _load_forecasting_symbols()
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=500)

    intent = data.get("intent", {})
    question_type = data.get("question_type")
    final_route = data.get("final_route")
    request_meta = detect_forecast_request(
        intent=intent if isinstance(intent, dict) else {},
        question_type=str(question_type or "").strip() or None,
        final_route=str(final_route or "").strip() or None,
    )
    return JsonResponse(
        {
            "requires_forecast": bool(request_meta.requires_forecast),
            "question_type": str(request_meta.question_type),
            "reason": str(request_meta.reason),
        }
    )


@csrf_exempt
@require_internal_api_key
def forecast_dataset_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    try:
        ForecastingError, build_forecast_dataset, _ = _load_forecasting_symbols()
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=500)

    columns = data.get("columns", [])
    rows = data.get("rows", [])
    intent = data.get("intent", {})
    horizon = data.get("horizon")

    try:
        result = build_forecast_dataset(
            columns=columns if isinstance(columns, list) else [],
            rows=rows if isinstance(rows, list) else [],
            intent=intent if isinstance(intent, dict) else {},
            horizon=horizon,
        )
        return JsonResponse(result)
    except ForecastingError as exc:
        return JsonResponse({"error": exc.to_dict()}, status=422)

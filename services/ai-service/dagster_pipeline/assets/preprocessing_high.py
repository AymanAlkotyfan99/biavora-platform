import time
from typing import Any

from dagster import AssetExecutionContext, asset

from dagster_pipeline import ASSET_RETRY_POLICY, pipeline_failure_hook
from preprocessing_high.preprocess_high_task import run_preprocess_high
from preprocessing_high.schemas import HighPreprocessConfig
from reasoning_app.intent_classification_task import route_intent_classification
from shared.dataset_binding import DatasetBindingError, normalize_dataset_context, validate_dataset_context
from shared.pipeline_trace import make_attempt, utc_now_iso
from shared.query_service_auth import set_forwarded_query_service_bearer_token
from shared.stage_contract import stage_allows_progress


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def preprocessing_high_asset(
    context: AssetExecutionContext,
    pipeline_request_asset: dict[str, Any],
    intent_classification_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    low_progress_ok = stage_allows_progress(
        intent_classification_asset.get("status"),
        degraded=bool(intent_classification_asset.get("degraded")),
    )
    if not low_progress_ok:
        context.log.warning(
            "High preprocessing continuing with degraded low preprocessing | status=%s",
            intent_classification_asset.get("status"),
        )

    routing_result = route_intent_classification(
        cleaned_text=str(intent_classification_asset.get("cleaned_text", "")),
        classification_result=intent_classification_asset,
        user_id=str(pipeline_request_asset.get("user_id") or "").strip(),
    )
    context.log.info(
        "Classification gate completed | gate_status=%s next_stage=%s",
        routing_result.get("status"),
        routing_result.get("next_stage"),
    )

    if routing_result.get("status") == "rejected":
        attempts = [
            make_attempt(
                attempt_number=1,
                input_payload={"routing": routing_result},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="intent_classification_gate",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="business",
                error_message=str(routing_result.get("message", "Question rejected by classification gate.")),
            )
        ]
        return {
            "status": "rejected",
            "final_query": "",
            "schema_valid": False,
            "error_type": "business",
            "action_taken": "stop",
            "message": routing_result.get(
                "message",
                "The question is not analytical and cannot be processed.",
            ),
            "routing": routing_result,
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "business", "message": str(routing_result.get("message", ""))}],
            "debug_metadata": {"classification": routing_result.get("classification")},
        }

    if not stage_allows_progress(routing_result.get("status"), degraded=bool(routing_result.get("degraded"))):
        context.log.warning("Intent routing returned non-progress status. Falling back to analytical route.")
        routing_result = {
            "status": "success",
            "route": "analytical",
            "next_step": "metabase",
            "classification": intent_classification_asset,
            "payload": {
                "cleaned_text": str(intent_classification_asset.get("cleaned_text", "")),
                "user_id": str(pipeline_request_asset.get("user_id") or "").strip(),
                "route": "analytical",
            },
        }

    payload = routing_result.get("payload", {}) or {}
    effective_user_id = str(payload.get("user_id") or "").strip()
    if not effective_user_id:
        effective_user_id = HighPreprocessConfig.from_env().default_user_id
    try:
        dataset_scope = validate_dataset_context(normalize_dataset_context(pipeline_request_asset))
    except DatasetBindingError:
        dataset_scope = normalize_dataset_context(pipeline_request_asset)

    result = run_preprocess_high(
        cleaned_text=str(payload.get("cleaned_text", intent_classification_asset.get("cleaned_text", ""))),
        user_id=effective_user_id,
        route=str(routing_result.get("route", "analytical")).strip().lower() or "analytical",
        dataset_scope=dataset_scope,
    )
    # Preserve resolved dataset binding when callers omit table/dataset fields.
    resolved_table = str(result.get("selected_table", "")).strip()
    if not str(dataset_scope.get("table_name", "")).strip() and resolved_table:
        dataset_scope["table_name"] = resolved_table
    if not str(dataset_scope.get("dataset_id", "")).strip():
        fallback_dataset = str(dataset_scope.get("source_id", "")).strip() or resolved_table
        if fallback_dataset:
            dataset_scope["dataset_id"] = fallback_dataset
    if not str(dataset_scope.get("source_id", "")).strip():
        fallback_source = str(dataset_scope.get("dataset_id", "")).strip() or resolved_table
        if fallback_source:
            dataset_scope["source_id"] = fallback_source
    result["routing"] = routing_result
    if not str(result.get("final_query", "")).strip():
        result["final_query"] = str(payload.get("cleaned_text") or intent_classification_asset.get("cleaned_text") or "").strip()
    if not str(result.get("final_query", "")).strip():
        result["final_query"] = "show total records by date"
    result.setdefault("started_at", stage_started_at)
    result.setdefault("finished_at", utc_now_iso())
    if not result.get("duration_ms"):
        result["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
    result.setdefault("attempts", [])
    result["attempts_count"] = len(result.get("attempts", []))
    result.setdefault("warnings", [])
    result.setdefault("errors", [])
    result.setdefault("debug_metadata", {})
    result["routing_decision"] = {
        "route": routing_result.get("route"),
        "next_step": routing_result.get("next_step"),
    }
    result["debug_metadata"]["classification"] = routing_result.get("classification")
    result["debug_metadata"]["routing_decision"] = {
        "route": routing_result.get("route"),
        "next_step": routing_result.get("next_step"),
    }
    result["debug_metadata"]["dataset_scope"] = dataset_scope
    result["dataset_scope"] = dataset_scope
    access_token = str(pipeline_request_asset.get("access_token") or "").strip()
    if access_token:
        set_forwarded_query_service_bearer_token(access_token)
    context.log.info(
        "High preprocessing completed | status=%s schema_valid=%s",
        result.get("status"),
        result.get("schema_valid"),
    )
    return result

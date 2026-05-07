import time
from typing import Any

from dagster import AssetExecutionContext, asset

from dagster_pipeline import ASSET_RETRY_POLICY, pipeline_failure_hook
from shared.pipeline_trace import make_attempt, utc_now_iso
from shared.stage_contract import normalize_stage_status, stage_allows_progress


_ALLOWED_STEPS = {"metabase", "forecasting"}
_PREDICTIVE_LABELS = {"predictive", "forecast", "forecasting"}


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def routing_asset(
    context: AssetExecutionContext,
    intent_extraction_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    if not stage_allows_progress(intent_extraction_asset.get("status"), degraded=bool(intent_extraction_asset.get("degraded"))):
        message = str(intent_extraction_asset.get("message") or "Routing skipped because intent extraction did not allow progress.")
        context.log.warning("Routing stopped by upstream gate | intent_status=%s message=%s", intent_extraction_asset.get("status"), message)
        attempts = [
            make_attempt(
                attempt_number=1,
                input_payload={"intent_status": intent_extraction_asset.get("status")},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="upstream_stage_guard",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="upstream_rejected",
                error_message=message,
            )
        ]
        return {
            "status": "skipped",
            "next_step": "stop",
            "error_type": "upstream_rejected",
            "action_taken": "stop",
            "message": message,
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "upstream_rejected", "message": message}],
            "debug_metadata": {
                "upstream_status": intent_extraction_asset.get("status"),
                "upstream_stage": "intent_extraction",
            },
            "upstream_status": intent_extraction_asset.get("status"),
            "upstream_stage": "intent_extraction",
            "classification": intent_extraction_asset,
        }

    next_step = str(intent_extraction_asset.get("next_step", "metabase")).strip().lower()
    intent_type = str(intent_extraction_asset.get("intent_type", "analytical")).strip().lower()
    extracted_intent = (
        intent_extraction_asset.get("extracted_intent", {})
        if isinstance(intent_extraction_asset.get("extracted_intent"), dict)
        else {}
    )
    validated_intent = (
        intent_extraction_asset.get("validated_intent", {})
        if isinstance(intent_extraction_asset.get("validated_intent"), dict)
        else {}
    )
    predictive_signal = (
        intent_type in _PREDICTIVE_LABELS
        or str(validated_intent.get("intent_type", "")).strip().lower() in _PREDICTIVE_LABELS
        or str(validated_intent.get("question_type", "")).strip().lower() in _PREDICTIVE_LABELS
        or bool(validated_intent.get("requires_forecast"))
        or str(extracted_intent.get("intent_type", "")).strip().lower() in _PREDICTIVE_LABELS
    )
    if predictive_signal:
        next_step = "forecasting"
        intent_type = "predictive"
        validated_intent["intent_type"] = "predictive"
        validated_intent["question_type"] = "predictive"
        validated_intent["requires_forecast"] = True
    if next_step not in _ALLOWED_STEPS:
        context.log.error("Routing produced unsupported next_step=%s", next_step)
        attempts = [
            make_attempt(
                attempt_number=1,
                input_payload={"next_step": next_step},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="route_validator",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="logic",
                error_message=f"Unsupported routing target: {next_step}",
            )
        ]
        return {
            "status": "failed",
            "next_step": "metabase",
            "error_type": "logic",
            "action_taken": "stop",
            "message": f"Unsupported routing target: {next_step}",
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "logic", "message": f"Unsupported routing target: {next_step}"}],
            "debug_metadata": {},
        }

    routed_result = {
        "status": normalize_stage_status("success"),
        "legacy_status": "routed",
        "next_step": next_step,
        "intent_type": intent_type or "analytical",
        "query": intent_extraction_asset.get("query", ""),
        "schema": intent_extraction_asset.get("schema", {}),
        "extracted_intent": extracted_intent,
        "validated_intent": validated_intent,
        "attempts": [
            make_attempt(
                attempt_number=1,
                input_payload={
                    "intent_type": intent_extraction_asset.get("intent_type", "analytical"),
                    "next_step": next_step,
                },
                output_payload={"next_step": next_step},
                success=True,
                retry_triggered=False,
                model_or_method_used="route_selector",
                duration_ms=0,
                validation_result={"is_valid": True},
            )
        ],
        "attempts_count": 1,
        "started_at": stage_started_at,
        "finished_at": utc_now_iso(),
        "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
        "warnings": [],
        "errors": [],
        "debug_metadata": {
            "classification": intent_extraction_asset.get("debug_metadata", {}),
            "predictive_signal": predictive_signal,
            "dataset_scope": (
                intent_extraction_asset.get("debug_metadata", {})
                if isinstance(intent_extraction_asset.get("debug_metadata"), dict)
                else {}
            ).get("dataset_scope", {}),
            "bound_table": (
                intent_extraction_asset.get("debug_metadata", {})
                if isinstance(intent_extraction_asset.get("debug_metadata"), dict)
                else {}
            ).get("selected_table", ""),
        },
    }
    context.log.info(
        "Routing asset completed | next_step=%s intent_type=%s",
        routed_result["next_step"],
        routed_result["intent_type"],
    )
    return routed_result

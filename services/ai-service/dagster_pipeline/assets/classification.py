import time
from typing import Any

from dagster import AssetExecutionContext, asset

from dagster_pipeline import ASSET_RETRY_POLICY, pipeline_failure_hook
from reasoning_app.intent_classification_task import run_intent_classification
from shared.pipeline_trace import utc_now_iso


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def classification_asset(
    context: AssetExecutionContext,
    preprocessing_low_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    question = str(
        preprocessing_low_asset.get("cleaned_text")
        or preprocessing_low_asset.get("text")
        or ""
    ).strip()

    result = run_intent_classification(cleaned_text=question, raw_text=question, source="pipeline")
    if not result:
        result = {
            "status": "failed",
            "type": "INVALID",
            "classification_type": "INVALID",
            "classification": "invalid_input",
            "question_type": "invalid_input",
            "is_analytical": False,
            "confidence": 0.0,
            "classification_reason": "Classifier returned empty payload.",
            "reasoning": "Classifier returned empty payload.",
            "route": "stop",
            "requires_forecast": False,
            "error_type": "model",
            "action_taken": "stop",
            "attempts": [],
            "attempts_count": 0,
            "warnings": [],
            "errors": [{"type": "classifier_empty_payload", "message": "LLM classifier returned empty payload."}],
            "debug_metadata": {"classification_source": "empty_payload_rejected"},
        }

    result.setdefault("started_at", stage_started_at)
    result.setdefault("finished_at", utc_now_iso())
    if not result.get("duration_ms"):
        result["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
    result.setdefault("type", str(result.get("classification_type", "ANALYTICAL")).upper())
    result.setdefault("reasoning", str(result.get("classification_reason", "")).strip() or "No reasoning provided.")
    result.setdefault("cleaned_text", question)
    context.log.info(f"Classification result: {result}")
    return result

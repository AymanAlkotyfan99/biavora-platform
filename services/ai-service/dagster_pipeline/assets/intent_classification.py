import time
from typing import Any

from dagster import AssetExecutionContext, asset

from dagster_pipeline import ASSET_RETRY_POLICY, pipeline_failure_hook
from shared.pipeline_trace import utc_now_iso


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def intent_classification_asset(
    context: AssetExecutionContext,
    pipeline_request_asset: dict[str, Any],
    preprocessing_low_asset: dict[str, Any],
    classification_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    # Keep legacy asset API stable while forcing dependency through classification_asset.
    result = dict(classification_asset or {})
    result.setdefault("started_at", stage_started_at)
    result.setdefault("finished_at", utc_now_iso())
    if not result.get("duration_ms"):
        result["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
    result.setdefault("attempts", [])
    result["attempts_count"] = len(result.get("attempts", []))
    result.setdefault("warnings", [])
    result.setdefault("errors", [])
    result.setdefault("debug_metadata", {})
    result["debug_metadata"]["cleaned_text_chars"] = len(str(preprocessing_low_asset.get("cleaned_text", "")))
    result["debug_metadata"]["dataset_context"] = {
        "workspace_id": pipeline_request_asset.get("workspace_id"),
        "dataset_id": pipeline_request_asset.get("dataset_id") or pipeline_request_asset.get("source_id"),
        "manager_id": pipeline_request_asset.get("manager_id") or pipeline_request_asset.get("user_id"),
        "table_name": pipeline_request_asset.get("table_name"),
    }
    context.log.info(
        "Intent classification completed | status=%s is_analytical=%s classification=%s route=%s requires_forecast=%s",
        result.get("status"),
        result.get("is_analytical"),
        result.get("classification"),
        (result.get("debug_metadata", {}) if isinstance(result.get("debug_metadata"), dict) else {}).get("route"),
        result.get("requires_forecast"),
    )
    return result

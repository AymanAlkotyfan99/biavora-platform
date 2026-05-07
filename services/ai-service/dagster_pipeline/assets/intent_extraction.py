import time
from typing import Any

from dagster import AssetExecutionContext, asset

from dagster_pipeline import ASSET_RETRY_POLICY, pipeline_failure_hook
from intent_extraction.intent_extraction_task import run_intent_extraction_stage
from llm_app.schema_provider import get_schema_for_dataset
from shared.dataset_binding import (
    DatasetBindingError,
    normalize_dataset_context,
    normalize_identifier,
    validate_dataset_context,
)
from shared.confidence import stage_confidence
from shared.pipeline_trace import make_attempt, utc_now_iso
from shared.pipeline_guards import dataset_scope_guard
from shared.schema_filtering import filter_business_schema
from shared.stage_contract import stage_allows_progress


def _schema_from_preprocessing_high(preprocessing_high_asset: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    schema_used = preprocessing_high_asset.get("schema_used")
    if not isinstance(schema_used, dict):
        return {}

    candidate_columns = schema_used.get("columns")
    if isinstance(candidate_columns, dict):
        schema_columns = candidate_columns
    else:
        schema_columns = schema_used

    normalized_schema: dict[str, list[dict[str, Any]]] = {}
    for table_name, columns in schema_columns.items():
        normalized_table = str(table_name).strip()
        if not normalized_table or not isinstance(columns, list):
            continue
        normalized_columns: list[dict[str, Any]] = []
        for column in columns:
            if not isinstance(column, dict):
                continue
            column_name = str(column.get("name", "")).strip()
            if not column_name:
                continue
            normalized_columns.append(
                {
                    "name": column_name,
                    "type": str(column.get("type", "")).strip(),
                }
            )
        if normalized_columns:
            normalized_schema[normalized_table] = normalized_columns
    return normalized_schema


def _bound_table_schema_or_error(
    *,
    schema_snapshot: dict[str, list[dict[str, Any]]],
    dataset_context: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    bound_table = normalize_identifier(dataset_context.get("table_name", ""))
    if not bound_table:
        if len(schema_snapshot) == 1:
            table_name = next(iter(schema_snapshot.keys()))
            return {table_name: schema_snapshot[table_name]}
        if schema_snapshot:
            selected = sorted(schema_snapshot.keys())[0]
            return {selected: schema_snapshot[selected]}
        raise DatasetBindingError(
            "Dataset-table mismatch: empty schema snapshot after preprocessing_high (no tables; "
            "check ClickHouse connectivity and PREPROCESS_HIGH database template)."
        )
    normalized_bound_suffix = bound_table.split(".")[-1].lower()
    for table_name, columns in schema_snapshot.items():
        normalized_table = str(table_name).strip()
        if not normalized_table:
            continue
        if (
            normalized_table.lower() == bound_table.lower()
            or normalized_table.split(".")[-1].lower() == normalized_bound_suffix
        ):
            return {normalized_table: columns}
    preview = list(schema_snapshot.keys())[:25]
    raise DatasetBindingError(
        "Dataset-table mismatch: bound table_name "
        f"{bound_table!r} (suffix={normalized_bound_suffix!r}) not found in preprocessing schema "
        f"(available_tables={preview!r})"
    )


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def intent_extraction_asset(
    context: AssetExecutionContext,
    preprocessing_high_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    high_status = preprocessing_high_asset.get("status")
    if not stage_allows_progress(high_status, degraded=bool(preprocessing_high_asset.get("degraded"))):
        message = str(
            preprocessing_high_asset.get("message")
            or "Intent extraction skipped because preprocessing/classification did not allow progress."
        )
        context.log.warning("Intent extraction stopped by upstream gate | status=%s message=%s", high_status, message)
        attempts = [
            make_attempt(
                attempt_number=1,
                input_payload={"preprocessing_high_status": high_status},
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
            "intent_type": "invalid",
            "next_step": "stop",
            "error_type": "upstream_rejected",
            "action_taken": "stop",
            "message": message,
            "query": "",
            "schema": {},
            "extracted_intent": {},
            "validated_intent": {},
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "upstream_rejected", "message": message}],
            "debug_metadata": {
                "upstream_status": high_status,
                "upstream_stage": "preprocessing_high",
            },
            "upstream_status": high_status,
            "upstream_stage": "preprocessing_high",
        }

    final_query = str(preprocessing_high_asset.get("final_query", "")).strip()
    if not final_query:
        message = "Intent extraction requires a non-empty normalized question."
        attempts = [
            make_attempt(
                attempt_number=1,
                input_payload={"final_query": final_query},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="intent_extraction_input_guard",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="input",
                error_message=message,
            )
        ]
        return {
            "status": "failed",
            "intent_type": "invalid",
            "next_step": "stop",
            "error_type": "input",
            "action_taken": "stop",
            "message": message,
            "query": "",
            "schema": {},
            "extracted_intent": {},
            "validated_intent": {},
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "input", "message": message}],
            "debug_metadata": {},
        }

    route = str(
        (
            preprocessing_high_asset.get("routing", {})
            if isinstance(preprocessing_high_asset.get("routing"), dict)
            else {}
        ).get("route", preprocessing_high_asset.get("route", "analytical"))
    ).strip().lower() or "analytical"
    schema_validation_deferred = bool(
        route != "forecasting"
        and preprocessing_high_asset.get("schema_valid") is False
    )
    if schema_validation_deferred:
        context.log.warning(
            "Proceeding with intent extraction after deferred schema validation | status=%s unresolved_terms=%s unsupported_terms=%s",
            preprocessing_high_asset.get("schema_validation_status"),
            preprocessing_high_asset.get("unresolved_terms", []),
            preprocessing_high_asset.get("unsupported_terms", []),
        )

    dataset_scope = (
        preprocessing_high_asset.get("dataset_scope")
        if isinstance(preprocessing_high_asset.get("dataset_scope"), dict)
        else {}
    )
    try:
        dataset_context = validate_dataset_context(normalize_dataset_context(dataset_scope))
    except DatasetBindingError:
        dataset_context = normalize_dataset_context(dataset_scope)

    schema_snapshot = _schema_from_preprocessing_high(preprocessing_high_asset)
    schema_source = "preprocessing_high.schema_used"
    if not schema_snapshot:
        try:
            schema_snapshot = get_schema_for_dataset(
                workspace_id=dataset_context.get("workspace_id", ""),
                dataset_id=dataset_context.get("dataset_id", ""),
                manager_id=dataset_context.get("manager_id", ""),
                table_name=dataset_context.get("table_name", ""),
                source_id=dataset_context.get("source_id", ""),
                report_id=dataset_context.get("report_id", ""),
            )
            schema_source = "schema_provider.get_schema_for_dataset"
        except Exception as exc:  # noqa: BLE001
            context.log.error("Schema loading failed for intent extraction | error=%s", str(exc))
            attempts = [
                make_attempt(
                    attempt_number=1,
                    input_payload={"final_query": final_query},
                    output_payload={},
                    success=False,
                    retry_triggered=False,
                    model_or_method_used="schema_provider.get_schema_for_dataset",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type="system",
                    error_message=f"Failed to load schema: {exc}",
                )
            ]
            return {
                "status": "failed",
                "intent_type": "analytical",
                "next_step": "metabase",
                "error_type": "system",
                "action_taken": "stop",
                "message": f"Failed to load schema: {exc}",
                "attempts": attempts,
                "attempts_count": len(attempts),
                "started_at": stage_started_at,
                "finished_at": utc_now_iso(),
                "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
                "warnings": [],
                "errors": [{"type": "system", "message": f"Failed to load schema: {exc}"}],
                "debug_metadata": {},
            }
    context.log.info(
        "Intent extraction schema prepared | source=%s tables=%s",
        schema_source,
        len(schema_snapshot),
    )

    schema_snapshot, schema_filter_meta = filter_business_schema(schema_snapshot)

    selected_columns = [
        str(column).strip()
        for column in preprocessing_high_asset.get("selected_columns", [])
        if str(column).strip()
    ]
    try:
        bound_table = dataset_context.get("table_name", "")
        schema_snapshot = _bound_table_schema_or_error(
            schema_snapshot=schema_snapshot,
            dataset_context=dataset_context,
        )
    except DatasetBindingError as exc:
        attempts = [
            make_attempt(
                attempt_number=1,
                input_payload={
                    "final_query": final_query,
                    "dataset_scope": dataset_scope,
                },
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="dataset_scope_guard",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="input",
                error_message=str(exc),
            )
        ]
        return {
            "status": "failed",
            "intent_type": "analytical",
            "next_step": "metabase",
            "error_type": "input",
            "action_taken": "stop",
            "message": str(exc),
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "input", "message": str(exc)}],
            "debug_metadata": {
                "dataset_scope": normalize_dataset_context(dataset_scope),
                "reason_for_selection": "dataset_table_mismatch",
            },
        }

    scoped_schema, scope_meta = dataset_scope_guard(
        schema=schema_snapshot,
        dataset_scope=dataset_context,
        selected_table=bound_table,
        candidate_tables=list(schema_snapshot.keys()),
        strict=True,
    )
    schema_snapshot = scoped_schema
    should_scope_schema = True

    original_user_question = str(
        preprocessing_high_asset.get("original_query_for_intent")
        or (
            (preprocessing_high_asset.get("routing") or {}).get("payload", {}).get("cleaned_text")
            if isinstance(preprocessing_high_asset.get("routing"), dict)
            else ""
        )
        or final_query
    ).strip()
    result = run_intent_extraction_stage(
        query=final_query,
        schema=schema_snapshot,
        route=route,
        preprocess_hints={
            "selected_columns": selected_columns,
            "selected_table": bound_table,
            "original_user_question": original_user_question,
            "original_query_for_intent": original_user_question,
        },
    )
    result.setdefault("started_at", stage_started_at)
    result.setdefault("finished_at", utc_now_iso())
    if not result.get("duration_ms"):
        result["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
    result.setdefault("attempts", [])
    result["attempts_count"] = len(result.get("attempts", []))
    result.setdefault("warnings", [])
    result.setdefault("errors", [])
    result.setdefault("debug_metadata", {})
    result["debug_metadata"]["final_query"] = final_query
    result["debug_metadata"]["selected_table"] = bound_table
    result["debug_metadata"]["selected_columns"] = selected_columns
    result["debug_metadata"]["schema_tables"] = list(schema_snapshot.keys())
    result["debug_metadata"]["schema_source"] = schema_source
    result["debug_metadata"]["schema_scoped"] = should_scope_schema
    result["debug_metadata"]["schema_filtering"] = schema_filter_meta
    result["debug_metadata"]["dataset_scope"] = dataset_context
    result["debug_metadata"]["dataset_scope_guard"] = scope_meta
    result["debug_metadata"]["reason_for_selection"] = scope_meta.get("reason_for_selection", "")
    result["debug_metadata"]["schema_validation_status"] = preprocessing_high_asset.get("schema_validation_status")
    result["debug_metadata"]["unresolved_terms"] = preprocessing_high_asset.get("unresolved_terms", [])
    result["debug_metadata"]["unsupported_terms"] = preprocessing_high_asset.get("unsupported_terms", [])
    result["debug_metadata"]["sql_generation_allowed"] = True
    if schema_validation_deferred:
        result["warnings"].append(
            {
                "type": "schema_validation_deferred",
                "message": (
                    "Preprocessing-high schema validation was deferred; "
                    "intent-aware schema/table binding validation was applied."
                ),
            }
        )
    if isinstance(result.get("validated_intent"), dict):
        result["validated_intent"]["table"] = bound_table
        result["validated_intent"]["dataset_context"] = dataset_context
    if isinstance(result.get("extracted_intent"), dict):
        result["extracted_intent"]["table"] = bound_table
        result["extracted_intent"]["dataset_context"] = dataset_context
    result["dataset_context"] = dataset_context
    result["confidence"] = stage_confidence(result, base_success=0.86, base_degraded=0.58)
    context.log.info(
        "Intent extraction stage completed | status=%s intent_type=%s next_step=%s",
        result.get("status"),
        result.get("intent_type"),
        result.get("next_step"),
    )
    return result

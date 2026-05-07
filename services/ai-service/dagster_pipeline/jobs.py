from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from dagster import AssetSelection, define_asset_job

from dagster_pipeline.assets import pipeline_result_asset, transcription_asset
from shared.pipeline_trace import build_pipeline_trace_template, finalize_trace


ai_service_pipeline_job = define_asset_job(
    name="ai_service_pipeline_job",
    selection=AssetSelection.assets(pipeline_result_asset).upstream(),
)

ai_service_transcription_job = define_asset_job(
    name="ai_service_transcription_job",
    selection=AssetSelection.assets(transcription_asset).upstream(),
)


def _build_request_config(
    *,
    audio_path: Optional[str] = None,
    text: Optional[str] = None,
    request_id: Optional[str] = None,
    language: Optional[str] = None,
    initial_prompt: Optional[str] = None,
    user_id: Optional[str] = None,
    manager_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    source_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    report_id: Optional[str] = None,
    table_name: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "ops": {
            "pipeline_request_asset": {
                "config": {
                    "audio_path": audio_path,
                    "text": text,
                    "request_id": request_id,
                    "language": language,
                    "initial_prompt": initial_prompt,
                    "user_id": user_id,
                    "manager_id": manager_id,
                    "dataset_id": dataset_id,
                    "source_id": source_id,
                    "workspace_id": workspace_id,
                    "report_id": report_id,
                    "table_name": table_name,
                    "access_token": access_token,
                }
            }
        }
    }


def _execute_job(job_name: str, run_config: dict[str, Any]):
    from dagster_pipeline.definitions import defs

    job_def = defs.get_job_def(job_name)
    return job_def.execute_in_process(
        run_config=run_config,
        raise_on_error=False,
    )


def _safe_getattr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:  # noqa: BLE001
        return default


def _extract_dagster_runtime(result: Any, *, job_name: str) -> dict[str, Any]:
    run_id = _safe_getattr(result, "run_id") or _safe_getattr(_safe_getattr(result, "dagster_run"), "run_id")
    all_events = list(_safe_getattr(result, "all_events", []) or [])

    steps: dict[str, dict[str, Any]] = {}
    step_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    materializations: list[dict[str, Any]] = []

    for event in all_events:
        event_type = str(
            _safe_getattr(event, "event_type_value")
            or _safe_getattr(_safe_getattr(event, "event_type"), "value")
            or _safe_getattr(event, "event_type")
            or "UNKNOWN"
        )
        step_key = str(_safe_getattr(event, "step_key") or "")
        timestamp = _safe_getattr(event, "timestamp")
        message = str(_safe_getattr(event, "message") or "")

        if step_key:
            step_entry = steps.setdefault(
                step_key,
                {
                    "op_name": step_key,
                    "step_key": step_key,
                    "status": "pending",
                    "retry_attempts": 0,
                    "retry_policy": {"max_retries": 2, "delay_seconds": 1.0},
                    "started_at": None,
                    "finished_at": None,
                },
            )
            if "STEP_START" in event_type and not step_entry["started_at"]:
                step_entry["status"] = "running"
                step_entry["started_at"] = timestamp
            if "STEP_UP_FOR_RETRY" in event_type or "STEP_RESTARTED" in event_type:
                step_entry["retry_attempts"] += 1
                step_entry["status"] = "retrying"
            if "STEP_FAILURE" in event_type:
                step_entry["status"] = "failed"
                step_entry["finished_at"] = timestamp
            if "STEP_SUCCESS" in event_type:
                step_entry["status"] = "success"
                step_entry["finished_at"] = timestamp

            step_events[step_key].append(
                {
                    "event_type": event_type,
                    "timestamp": timestamp,
                    "message": message,
                }
            )

        if "ASSET_MATERIALIZATION" in event_type:
            event_data = _safe_getattr(event, "event_specific_data")
            asset_key_obj = _safe_getattr(event_data, "asset_key")
            path = _safe_getattr(asset_key_obj, "path", None)
            asset_key = "/".join(path) if isinstance(path, (list, tuple)) else str(asset_key_obj or "")
            materializations.append(
                {
                    "asset_key": asset_key,
                    "timestamp": timestamp,
                    "message": message,
                }
            )

    step_list = []
    for step_key, step_info in steps.items():
        step_info["step_events"] = step_events.get(step_key, [])
        step_list.append(step_info)

    return {
        "dagster_run_id": str(run_id or ""),
        "job_name": job_name,
        "steps": step_list,
        "step_events": dict(step_events),
        "materializations": materializations,
        "orchestration_timings": {
            "event_count": len(all_events),
        },
        "upstream_downstream_context": {
            "mode": "execute_in_process",
            "note": "Step dependencies are inferred by Dagster asset graph.",
        },
    }


def _attach_runtime_to_payload(payload: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    payload["dagster_runtime"] = runtime
    trace = payload.get("pipeline_trace")
    if not isinstance(trace, dict):
        return payload

    section = trace.get("dagster_runtime")
    if not isinstance(section, dict):
        return payload

    section["status"] = "success" if runtime.get("dagster_run_id") else "failed"
    section["started_at"] = section.get("started_at") or trace.get("overall_status", {}).get("started_at")
    section["finished_at"] = section.get("finished_at") or section.get("started_at")
    section["duration_ms"] = section.get("duration_ms", 0)
    section["attempts"] = [
        {
            "attempt_number": 1,
            "input": {"job_name": runtime.get("job_name")},
            "output": {
                "dagster_run_id": runtime.get("dagster_run_id"),
                "steps_count": len(runtime.get("steps", [])),
            },
            "success": bool(runtime.get("dagster_run_id")),
            "retry_triggered": False,
            "retry_reason": "",
            "model_or_method_used": "dagster.execute_in_process",
            "duration_ms": 0,
            "validation_result": {"is_valid": bool(runtime.get("dagster_run_id"))},
            "error_type": "",
            "error_message": "",
        }
    ]
    section["attempts_count"] = len(section["attempts"])
    section["final_output"] = runtime
    section["errors"] = []
    section["warnings"] = []
    section["debug_metadata"] = {
        "step_count": len(runtime.get("steps", [])),
        "event_count": runtime.get("orchestration_timings", {}).get("event_count", 0),
    }
    return payload


def _build_orchestration_failure_payload(
    *,
    message: str,
    stage: str,
    runtime: dict[str, Any],
    request_metadata: dict[str, Any],
) -> dict[str, Any]:
    trace = build_pipeline_trace_template(request_metadata=request_metadata)
    finalize_trace(
        trace,
        overall_status="failed",
        final_route="stop",
        final_user_message=message,
        root_cause_category="orchestration",
        root_cause_detail=message,
        analyst_recommended_fix="Inspect Dagster run/step events and retry history.",
    )
    payload = {
        "status": "failed",
        "stage": stage,
        "message": message,
        "pipeline_trace": trace,
        "overall_status": trace.get("overall_status"),
        "root_cause": trace.get("root_cause"),
        "final_route": "stop",
        "final_user_message": message,
    }
    return _attach_runtime_to_payload(payload, runtime)


def run_transcription_pipeline(
    *,
    audio_path: Optional[str] = None,
    text: Optional[str] = None,
    request_id: Optional[str] = None,
    language: Optional[str] = None,
    initial_prompt: Optional[str] = None,
) -> dict[str, Any]:
    run_config = _build_request_config(
        audio_path=audio_path,
        text=text,
        request_id=request_id,
        language=language,
        initial_prompt=initial_prompt,
    )
    result = _execute_job("ai_service_transcription_job", run_config=run_config)
    runtime = _extract_dagster_runtime(result, job_name="ai_service_transcription_job")
    if not result.success:
        return {
            "status": "failed",
            "text": "",
            "error_type": "system",
            "action_taken": "stop",
            "retry_count": 0,
            "message": "Dagster transcription job failed.",
            "dagster_runtime": runtime,
        }
    try:
        payload = result.output_for_node("transcription_asset")
        if isinstance(payload, dict):
            payload["dagster_runtime"] = runtime
        return payload
    except Exception:  # noqa: BLE001
        return {
            "status": "failed",
            "text": "",
            "error_type": "system",
            "action_taken": "stop",
            "retry_count": 0,
            "message": "Dagster transcription output was not materialized.",
            "dagster_runtime": runtime,
        }


def run_full_ai_pipeline(
    *,
    audio_path: Optional[str] = None,
    text: Optional[str] = None,
    request_id: Optional[str] = None,
    language: Optional[str] = None,
    initial_prompt: Optional[str] = None,
    user_id: Optional[str] = None,
    manager_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    source_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    report_id: Optional[str] = None,
    table_name: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict[str, Any]:
    run_config = _build_request_config(
        audio_path=audio_path,
        text=text,
        request_id=request_id,
        language=language,
        initial_prompt=initial_prompt,
        user_id=user_id,
        manager_id=manager_id,
        dataset_id=dataset_id,
        source_id=source_id,
        workspace_id=workspace_id,
        report_id=report_id,
        table_name=table_name,
        access_token=access_token,
    )
    result = _execute_job("ai_service_pipeline_job", run_config=run_config)
    runtime = _extract_dagster_runtime(result, job_name="ai_service_pipeline_job")
    if not result.success:
        return _build_orchestration_failure_payload(
            message="Dagster AI pipeline job failed.",
            stage="dagster_orchestration",
            runtime=runtime,
            request_metadata={
                "audio_path": audio_path,
                "text": text,
                "request_id": request_id,
                "language": language,
                "initial_prompt": initial_prompt,
                "user_id": user_id,
                "manager_id": manager_id,
                "dataset_id": dataset_id,
                "source_id": source_id,
                "workspace_id": workspace_id,
                "report_id": report_id,
                "table_name": table_name,
            },
        )
    try:
        payload = result.output_for_node("pipeline_result_asset")
        if isinstance(payload, dict):
            payload = _attach_runtime_to_payload(payload, runtime)
        return payload
    except Exception:  # noqa: BLE001
        return _build_orchestration_failure_payload(
            message="Dagster pipeline result asset was not materialized.",
            stage="dagster_orchestration",
            runtime=runtime,
            request_metadata={
                "audio_path": audio_path,
                "text": text,
                "request_id": request_id,
                "language": language,
                "initial_prompt": initial_prompt,
                "user_id": user_id,
                "manager_id": manager_id,
                "dataset_id": dataset_id,
                "source_id": source_id,
                "workspace_id": workspace_id,
                "report_id": report_id,
                "table_name": table_name,
            },
        )

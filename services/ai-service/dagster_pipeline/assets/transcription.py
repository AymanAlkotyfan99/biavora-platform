import hashlib
import time
from typing import Any, Optional

from dagster import AssetExecutionContext, Config, asset

from dagster_pipeline import ASSET_RETRY_POLICY, pipeline_failure_hook
from shared.pipeline_trace import make_attempt, utc_now_iso
from whisper_app.transcription_task import transcribe_audio_task


class PipelineRequestConfig(Config):
    audio_path: Optional[str] = None
    text: Optional[str] = None
    request_id: Optional[str] = None
    language: Optional[str] = None
    initial_prompt: Optional[str] = None
    user_id: Optional[str] = None
    manager_id: Optional[str] = None
    dataset_id: Optional[str] = None
    source_id: Optional[str] = None
    workspace_id: Optional[str] = None
    report_id: Optional[str] = None
    table_name: Optional[str] = None
    access_token: Optional[str] = None


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def pipeline_request_asset(context: AssetExecutionContext, config: PipelineRequestConfig) -> dict[str, Any]:
    payload = {
        "audio_path": str(config.audio_path or "").strip() or None,
        "text": str(config.text or "").strip() or None,
        "request_id": str(config.request_id or "").strip() or None,
        "language": str(config.language or "").strip() or None,
        "initial_prompt": str(config.initial_prompt or "").strip() or None,
        "user_id": str(config.user_id or "").strip() or None,
        "manager_id": str(config.manager_id or "").strip() or None,
        "dataset_id": str(config.dataset_id or "").strip() or None,
        "source_id": str(config.source_id or "").strip() or None,
        "workspace_id": str(config.workspace_id or "").strip() or None,
        "report_id": str(config.report_id or "").strip() or None,
        "table_name": str(config.table_name or "").strip() or None,
        "access_token": str(config.access_token or "").strip() or None,
    }
    context.log.info(
        "Pipeline request received | has_audio=%s has_text=%s user_id_present=%s",
        bool(payload["audio_path"]),
        bool(payload["text"]),
        bool(payload["user_id"]),
    )
    return payload


@asset(
    group_name="ai_pipeline",
    retry_policy=ASSET_RETRY_POLICY,
    hooks={pipeline_failure_hook},
)
def transcription_asset(
    context: AssetExecutionContext,
    pipeline_request_asset: dict[str, Any],
) -> dict[str, Any]:
    stage_started_at = utc_now_iso()
    stage_started_perf = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    audio_path = pipeline_request_asset.get("audio_path")
    text = pipeline_request_asset.get("text")

    if text and not audio_path:
        context.log.info("Skipping audio transcription and using provided text payload directly.")
        attempts.append(
            make_attempt(
                attempt_number=1,
                input_payload={"text": str(text)},
                output_payload={"text": str(text)},
                success=True,
                retry_triggered=False,
                model_or_method_used="request_text_passthrough",
                duration_ms=0,
                validation_result={"is_valid": bool(str(text).strip())},
            )
        )
        return {
            "status": "success",
            "text": str(text),
            "error_type": "none",
            "action_taken": "stop",
            "retry_count": 0,
            "source": "request_text",
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [],
            "debug_metadata": {"input_mode": "text"},
        }

    if not audio_path:
        context.log.warning("Transcription input invalid: missing both audio_path and text.")
        attempts.append(
            make_attempt(
                attempt_number=1,
                input_payload={"audio_path": audio_path, "text": text},
                output_payload={},
                success=False,
                retry_triggered=False,
                model_or_method_used="input_validation",
                duration_ms=0,
                validation_result={"is_valid": False},
                error_type="input",
                error_message="Missing audio_path and text.",
            )
        )
        return {
            "status": "failed",
            "text": "",
            "error_type": "input",
            "action_taken": "stop",
            "retry_count": 0,
            "message": "Missing audio_path and text.",
            "attempts": attempts,
            "attempts_count": len(attempts),
            "started_at": stage_started_at,
            "finished_at": utc_now_iso(),
            "duration_ms": int((time.perf_counter() - stage_started_perf) * 1000),
            "warnings": [],
            "errors": [{"type": "input", "message": "Missing audio_path and text."}],
            "debug_metadata": {"input_mode": "invalid"},
        }

    transcription_started_perf = time.perf_counter()
    result = transcribe_audio_task(
        audio_path=audio_path,
        request_id=pipeline_request_asset.get("request_id"),
        language=pipeline_request_asset.get("language"),
        initial_prompt=pipeline_request_asset.get("initial_prompt"),
    )
    attempts.append(
        make_attempt(
            attempt_number=1,
            input_payload={
                "audio_path": audio_path,
                "request_id": pipeline_request_asset.get("request_id"),
                "language": pipeline_request_asset.get("language"),
            },
            output_payload={
                "status": result.get("status"),
                "transcript_sha256": hashlib.sha256(
                    str(result.get("text", "")).encode("utf-8", errors="replace")
                ).hexdigest(),
                "transcript_char_len": len(str(result.get("text", ""))),
                "retry_count": result.get("retry_count", 0),
            },
            success=result.get("status") == "success",
            retry_triggered=False,
            model_or_method_used="whisper_transcribe_audio_task",
            duration_ms=int((time.perf_counter() - transcription_started_perf) * 1000),
            validation_result={"is_valid": result.get("status") == "success"},
            error_type="" if result.get("status") == "success" else str(result.get("error_type", "")),
            error_message=str(result.get("message", "")) if result.get("status") != "success" else "",
        )
    )
    result["attempts"] = attempts
    result["attempts_count"] = len(attempts)
    result["started_at"] = stage_started_at
    result["finished_at"] = utc_now_iso()
    result["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
    result["warnings"] = []
    result["errors"] = (
        []
        if result.get("status") == "success"
        else [{"type": str(result.get("error_type", "unknown")), "message": str(result.get("message", ""))}]
    )
    result["debug_metadata"] = {
        "input_mode": "audio",
        "audio_path_provided": bool(audio_path),
        "retry_count": result.get("retry_count", 0),
    }
    context.log.info(
        "Transcription asset completed | status=%s text_chars=%s",
        result.get("status"),
        len(str(result.get("text", ""))),
    )
    return result

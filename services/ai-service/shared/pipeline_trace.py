"""Pipeline trace builder (Phase 10).

Phase 10 changes versus the legacy implementation:

1. Every trace carries a ``trace_version`` (``"2.0"``). Consumers can use it
   to evolve the schema safely.
2. Persistence helpers (``select_trace_for_persistence``) reject trace
   payloads with an *older* version than the one already stored, so a slow
   late-arriving response can no longer overwrite a fresher trace.
3. Unknown versions emit a structured warning instead of silently passing
   through.
4. ``schema_provenance`` is a first-class section so we can detect schema
   drift (audit §12.5) and so the frontend can show which schema fingerprint
   produced the answer.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

from shared.stage_contract import normalize_stage_status


logger = logging.getLogger("ai_service.pipeline_trace")


# Phase 10 / §12.3: every trace emitted by ai-service is tagged with this
# version so downstream consumers can compare and reject older overwrites.
TRACE_VERSION = "2.0"

KNOWN_TRACE_VERSIONS = ("1.0", "2.0")


PIPELINE_TRACE_SECTIONS = [
    "request_metadata",
    "transcription",
    "preprocessing_low",
    "classification",
    "routing",
    "preprocessing_high",
    "predictive_intent",
    "intent_extraction",
    "schema_provenance",  # Phase 10 / audit §12.5
    "sql_generation",
    "sql_review",
    "sql_validation",
    "query_execution",
    "forecasting",
    "visualization",
    # Legacy keys kept for backwards compatibility with previously stored traces.
    "input_validation",
    "analytical_intent",
    "final_response",
    "dagster_runtime",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_ms(started_at: str | None, finished_at: str | None) -> int | None:
    if not started_at or not finished_at:
        return None
    try:
        start_dt = datetime.fromisoformat(started_at)
        end_dt = datetime.fromisoformat(finished_at)
    except ValueError:
        return None
    delta = end_dt - start_dt
    return max(0, int(delta.total_seconds() * 1000))


def _empty_attempt_template() -> dict[str, Any]:
    return {
        "attempt_number": 1,
        "input": None,
        "output": None,
        "success": False,
        "retry_triggered": False,
        "retry_reason": "",
        "model_or_method_used": "",
        "duration_ms": 0,
        "validation_result": {},
        "error_type": "",
        "error_message": "",
    }


def make_attempt(
    *,
    attempt_number: int,
    input_payload: Any = None,
    output_payload: Any = None,
    success: bool,
    retry_triggered: bool,
    retry_reason: str = "",
    model_or_method_used: str = "",
    duration_ms: int = 0,
    validation_result: dict[str, Any] | None = None,
    error_type: str = "",
    error_message: str = "",
) -> dict[str, Any]:
    attempt = _empty_attempt_template()
    attempt.update(
        {
            "attempt_number": max(1, int(attempt_number)),
            "input": input_payload,
            "output": output_payload,
            "success": bool(success),
            "retry_triggered": bool(retry_triggered),
            "retry_reason": str(retry_reason or ""),
            "model_or_method_used": str(model_or_method_used or ""),
            "duration_ms": max(0, int(duration_ms or 0)),
            "validation_result": deepcopy(validation_result or {}),
            "error_type": str(error_type or ""),
            "error_message": str(error_message or ""),
        }
    )
    return attempt


def create_stage_section(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "not_started",
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "attempts_count": 0,
        "attempts": [],
        "final_output": None,
        "errors": [],
        "warnings": [],
        "debug_metadata": {},
    }


def set_stage_from_values(
    section: dict[str, Any],
    *,
    status: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    attempts: list[dict[str, Any]] | None = None,
    final_output: Any = None,
    errors: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    debug_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_started = started_at or section.get("started_at") or utc_now_iso()
    normalized_finished = finished_at or utc_now_iso()
    normalized_attempts = list(attempts or [])

    section["status"] = normalize_stage_status(status)
    section["started_at"] = normalized_started
    section["finished_at"] = normalized_finished
    section["duration_ms"] = _duration_ms(normalized_started, normalized_finished)
    section["attempts"] = normalized_attempts
    section["attempts_count"] = len(normalized_attempts)
    section["final_output"] = final_output
    section["errors"] = list(errors or [])
    section["warnings"] = list(warnings or [])
    section["debug_metadata"] = deepcopy(debug_metadata or {})
    return section


def build_pipeline_trace_template(request_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    trace: dict[str, Any] = {}
    for section_name in PIPELINE_TRACE_SECTIONS:
        trace[section_name] = create_stage_section(section_name)

    request_attempt = make_attempt(
        attempt_number=1,
        input_payload=deepcopy(request_metadata or {}),
        output_payload=deepcopy(request_metadata or {}),
        success=True,
        retry_triggered=False,
        model_or_method_used="request_ingestion",
        duration_ms=0,
        validation_result={"is_valid": True},
    )
    set_stage_from_values(
        trace["request_metadata"],
        status="success",
        attempts=[request_attempt],
        final_output=deepcopy(request_metadata or {}),
        debug_metadata={"request_id": (request_metadata or {}).get("request_id")},
    )

    # Phase 10 / audit §12.5: ``schema_provenance`` carries the schema
    # fingerprint used to ground the pipeline so we can detect ETL drift
    # and so consumers can prove which schema produced the answer.
    trace["schema_provenance"] = create_stage_section("schema_provenance")

    trace["overall_status"] = {
        "status": "pending",
        "final_route": "",
        "final_user_message": "",
        "started_at": utc_now_iso(),
        "finished_at": None,
        "duration_ms": None,
    }
    trace["root_cause"] = {
        "root_cause_category": "unknown",
        "root_cause_detail": "",
        "analyst_recommended_fix": "",
    }
    # Phase 10 / §12.3: every trace carries an explicit version.
    trace["trace_version"] = TRACE_VERSION
    return trace


def attach_schema_provenance(
    trace: dict[str, Any],
    *,
    schema_fingerprint: str,
    schema_source: str,
    selected_table: str = "",
    selected_columns: list[str] | None = None,
    schema_loaded_at: Optional[str] = None,
) -> None:
    """Persist schema-provenance metadata onto the trace (audit §12.5)."""

    payload = {
        "schema_fingerprint": str(schema_fingerprint or ""),
        "schema_source": str(schema_source or ""),
        "selected_table": str(selected_table or ""),
        "selected_columns": list(selected_columns or []),
        "loaded_at": str(schema_loaded_at or utc_now_iso()),
    }
    set_stage_from_values(
        trace.setdefault("schema_provenance", create_stage_section("schema_provenance")),
        status="success" if schema_fingerprint else "skipped",
        final_output=payload,
        debug_metadata={"audit": "12.5"},
    )


def parse_trace_version(trace: dict[str, Any] | None) -> tuple[int, int]:
    """Parse ``trace_version`` into a comparable tuple.

    Unknown versions log a warning (Phase 10 / audit §12.3) and are treated
    as ``(0, 0)`` so they never overwrite a known version.
    """

    raw = ""
    if isinstance(trace, dict):
        raw = str(trace.get("trace_version") or "").strip()
    if not raw:
        return (0, 0)
    if raw not in KNOWN_TRACE_VERSIONS:
        logger.warning(
            "pipeline_trace.unknown_version",
            extra={"trace_version": raw, "known": list(KNOWN_TRACE_VERSIONS)},
        )
        return (0, 0)
    parts = raw.split(".")
    try:
        major = int(parts[0]) if parts else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        return (major, minor)
    except (TypeError, ValueError):
        return (0, 0)


def select_trace_for_persistence(
    *,
    candidate: dict[str, Any] | None,
    existing: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Pick the trace that should be persisted.

    Phase 10 / §12.3: a candidate trace overwrites the existing trace ONLY
    when its version is greater than or equal to the existing one. A
    late-arriving response with an older version is rejected to prevent
    silent regressions.
    """

    if not isinstance(candidate, dict):
        return existing if isinstance(existing, dict) else None
    if not isinstance(existing, dict):
        return candidate

    candidate_version = parse_trace_version(candidate)
    existing_version = parse_trace_version(existing)
    if candidate_version >= existing_version:
        return candidate

    logger.warning(
        "pipeline_trace.older_overwrite_rejected",
        extra={
            "candidate_version": candidate.get("trace_version"),
            "existing_version": existing.get("trace_version"),
        },
    )
    return existing


def attach_stage(trace: dict[str, Any], section_name: str, stage_payload: dict[str, Any]) -> None:
    target = trace.get(section_name)
    if not isinstance(target, dict):
        trace[section_name] = create_stage_section(section_name)
        target = trace[section_name]

    attempts = stage_payload.get("attempts", [])
    errors = stage_payload.get("errors", [])
    warnings = stage_payload.get("warnings", [])
    debug_metadata = stage_payload.get("debug_metadata", {})
    started_at = stage_payload.get("started_at")
    finished_at = stage_payload.get("finished_at")
    status = stage_payload.get("status", "unknown")

    set_stage_from_values(
        target,
        status=str(status),
        started_at=started_at,
        finished_at=finished_at,
        attempts=attempts if isinstance(attempts, list) else [],
        final_output=stage_payload.get("final_output"),
        errors=errors if isinstance(errors, list) else [],
        warnings=warnings if isinstance(warnings, list) else [],
        debug_metadata=debug_metadata if isinstance(debug_metadata, dict) else {},
    )


def finalize_trace(
    trace: dict[str, Any],
    *,
    overall_status: str,
    final_route: str,
    final_user_message: str,
    root_cause_category: str,
    root_cause_detail: str,
    analyst_recommended_fix: str,
) -> dict[str, Any]:
    now_iso = utc_now_iso()
    started = trace.get("overall_status", {}).get("started_at")
    trace["overall_status"] = {
        "status": normalize_stage_status(overall_status),
        "final_route": str(final_route or ""),
        "final_user_message": str(final_user_message or ""),
        "started_at": started or now_iso,
        "finished_at": now_iso,
        "duration_ms": _duration_ms(started or now_iso, now_iso),
    }
    trace["root_cause"] = {
        "root_cause_category": str(root_cause_category or "unknown"),
        "root_cause_detail": str(root_cause_detail or ""),
        "analyst_recommended_fix": str(analyst_recommended_fix or ""),
    }
    # Phase 10 / §12.3: ensure the version sticks even when callers
    # finalize a trace they constructed manually.
    trace.setdefault("trace_version", TRACE_VERSION)
    return trace


def stage_payload(
    *,
    status: str,
    final_output: Any,
    attempts: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    debug_metadata: dict[str, Any] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    started = started_at or utc_now_iso()
    finished = finished_at or utc_now_iso()
    return {
        "status": status,
        "started_at": started,
        "finished_at": finished,
        "attempts": list(attempts or []),
        "attempts_count": len(list(attempts or [])),
        "final_output": final_output,
        "errors": list(errors or []),
        "warnings": list(warnings or []),
        "debug_metadata": deepcopy(debug_metadata or {}),
        "duration_ms": _duration_ms(started, finished),
    }

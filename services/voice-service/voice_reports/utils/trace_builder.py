from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def stage_trace(stage: str, status: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = details or {}
    normalized_status = {
        "completed": "success",
        "started": "failed",
        "error": "failed",
        "partial_success": "degraded_success",
    }.get(str(status or "").strip().lower(), str(status or "").strip().lower() or "failed")
    return {
        "stage": stage,
        "stage_name": stage,
        "status": normalized_status,
        "input_summary": payload.get("input_summary", {}),
        "output_summary": payload.get("output_summary", {}),
        "error": payload.get("error"),
        "degraded_reason": payload.get("degraded_reason"),
        "service": payload.get("service", "voice-service"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": payload,
    }

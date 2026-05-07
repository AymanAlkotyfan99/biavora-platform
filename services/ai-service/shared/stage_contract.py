"""Stage status contract (Phase 9 / Phase 10).

The canonical statuses align with ``bi_platform_shared.contracts.trace.StageStatus``:

* ``success``    — stage finished with full output.
* ``degraded``   — stage finished but quality dropped (LLM fallback, partial schema).
* ``failed``     — stage raised; pipeline cannot continue.
* ``rejected``   — input was inadmissible (e.g. non-data question).
* ``skipped``    — stage genuinely did no work (route not selected).
* ``delegated``  — work belongs to a downstream service (audit §12.2).

The ``delegated`` status replaces the former ``"skipped"`` placeholder for
forecasting/visualization assets, which were routinely misread as failures.
"""

from __future__ import annotations

from typing import Any


CANONICAL_STAGE_STATUSES = {
    "success",
    "failed",
    "skipped",
    "degraded",
    "rejected",
    "delegated",
    "finalized",
}

_STATUS_ALIASES = {
    "ok": "success",
    "passed": "success",
    "completed": "success",
    "done": "success",
    "routed": "success",
    "running": "success",
    "in_progress": "success",
    "processing": "success",
    "error": "failed",
    "failure": "failed",
    "deferred": "delegated",
    "handed_off": "delegated",
    "partial": "degraded",
    "partial_success": "degraded",
    "warn": "degraded",
    "warning": "degraded",
    "cancelled": "failed",
    "canceled": "failed",
    "not_applicable": "skipped",
    "na": "skipped",
    "n/a": "skipped",
    "empty_result": "degraded",
}


def normalize_stage_status(status: Any, *, degraded: bool = False) -> str:
    normalized = str(status or "").strip().lower()
    canonical = _STATUS_ALIASES.get(normalized, normalized or "unknown")
    if canonical == "success" and degraded:
        return "degraded"
    if canonical in CANONICAL_STAGE_STATUSES:
        return canonical
    return "unknown"


def stage_allows_progress(status: Any, *, degraded: bool = False) -> bool:
    """Phase 9: ``delegated`` allows downstream stages to continue, like
    ``success``, because the work happens elsewhere — not because it
    failed.
    """

    normalized = normalize_stage_status(status, degraded=degraded)
    return normalized in {"success", "degraded", "delegated", "finalized"}


"""
Unified stage-status enum for the agent pipeline trace.

This replaces the ad-hoc string statuses (``"ok"``, ``"failed"``,
``"skipped"``, ``"degraded_success"``) that drifted across services and
caused frontend misclassification of healthy runs as failures.
"""

from __future__ import annotations

from enum import Enum


class StageStatus(str, Enum):
    """Canonical, normalized status of a single pipeline stage."""

    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    DELEGATED = "delegated"

    @classmethod
    def normalize(cls, raw: str | None) -> "StageStatus":
        """Map any legacy / ad-hoc status string into the canonical enum.

        Unknown statuses fall back to ``FAILED`` rather than silently
        becoming ``SUCCESS``: an unrecognized status is itself a defect we
        want surfaced.
        """

        if raw is None:
            return cls.SKIPPED
        token = str(raw).strip().lower()
        if not token:
            return cls.SKIPPED
        aliases = {
            "ok": cls.SUCCESS,
            "success": cls.SUCCESS,
            "succeeded": cls.SUCCESS,
            "completed": cls.SUCCESS,
            "done": cls.SUCCESS,
            "passed": cls.SUCCESS,
            "degraded": cls.DEGRADED,
            "degraded_success": cls.DEGRADED,
            "partial": cls.DEGRADED,
            "warning": cls.DEGRADED,
            "failed": cls.FAILED,
            "failure": cls.FAILED,
            "error": cls.FAILED,
            "rejected": cls.REJECTED,
            "denied": cls.REJECTED,
            "blocked": cls.REJECTED,
            "skipped": cls.SKIPPED,
            "noop": cls.SKIPPED,
            "not_applicable": cls.SKIPPED,
            "delegated": cls.DELEGATED,
            "deferred": cls.DELEGATED,
            "handed_off": cls.DELEGATED,
        }
        return aliases.get(token, cls.FAILED)


__all__ = ["StageStatus"]

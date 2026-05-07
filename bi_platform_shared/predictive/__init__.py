"""Shared predictive-question detector."""

from bi_platform_shared.predictive.detector import (
    PREDICTIVE_KEYWORDS,
    PREDICTIVE_PATTERNS,
    is_predictive,
)

__all__ = ["PREDICTIVE_KEYWORDS", "PREDICTIVE_PATTERNS", "is_predictive"]

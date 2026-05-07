"""Deterministic time semantics detection (PART 1 - CRITICAL AI LOGIC).

This module runs BEFORE preprocessing_high and BEFORE any LLM processing to detect
time-series intent from the raw user question. It ensures time expressions are
NEVER lost during preprocessing.

Phase: Pre-LLM Detection
Priority: CRITICAL - Must run first in pipeline
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# Time expression patterns (comprehensive list)
TIME_KEYWORDS = {
    # Explicit time phrases
    "over time",
    "through time",
    "across time",
    "throughout time",
    "over the years",
    "over the months",
    "over the weeks",
    "over the days",
    
    # Trend/growth keywords
    "trend",
    "trending",
    "growth",
    "growing",
    "decline",
    "declining",
    "change",
    "changing",
    "evolution",
    "evolving",
    "progression",
    "progressing",
    
    # Temporal grouping
    "by day",
    "by week",
    "by month",
    "by quarter",
    "by year",
    "per day",
    "per week",
    "per month",
    "per quarter",
    "per year",
    "each day",
    "each week",
    "each month",
    "each quarter",
    "each year",
    "every day",
    "every week",
    "every month",
    "every quarter",
    "every year",
    
    # Frequency keywords
    "daily",
    "weekly",
    "monthly",
    "by date",
    "quarterly",
    "yearly",
    "annual",
    "annually",
    
    # Time series verbs
    "track",
    "tracking",
    "monitor",
    "monitoring",
    "follow",
    "following",
    "watch",
    "watching",
    "observe",
    "observing",
}

# Granularity mapping
GRANULARITY_PATTERNS = {
    "day": [
        r"\bday\b",
        r"\bdaily\b",
        r"\bper day\b",
        r"\bby day\b",
        r"\bby\s+date\b",
        r"\beach day\b",
        r"\bevery day\b",
    ],
    "week": [
        r"\bweek\b",
        r"\bweekly\b",
        r"\bper week\b",
        r"\bby week\b",
        r"\beach week\b",
        r"\bevery week\b",
    ],
    "month": [
        r"\bmonth\b",
        r"\bmonthly\b",
        r"\bper month\b",
        r"\bby month\b",
        r"\beach month\b",
        r"\bevery month\b",
    ],
    "quarter": [
        r"\bquarter\b",
        r"\bquarterly\b",
        r"\bper quarter\b",
        r"\bby quarter\b",
        r"\beach quarter\b",
        r"\bevery quarter\b",
    ],
    "year": [
        r"\byear\b",
        r"\byearly\b",
        r"\bannual\b",
        r"\bannually\b",
        r"\bper year\b",
        r"\bby year\b",
        r"\beach year\b",
        r"\bevery year\b",
    ],
}


@dataclass(frozen=True)
class TimeSemantics:
    """Time semantics detection result."""
    
    is_time_series: bool
    time_grouping_detected: bool
    time_column: str
    time_granularity: str
    detected_keywords: list[str]
    confidence: float
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "is_time_series": self.is_time_series,
            "time_grouping_detected": self.time_grouping_detected,
            "time_column": self.time_column,
            "time_granularity": self.time_granularity,
            "detected_keywords": self.detected_keywords,
            "confidence": self.confidence,
        }


def extract_longest_time_keyword(question: str) -> str:
    """Return the longest TIME_KEYWORDS substring found in ``question`` (for diagnostics / repair hints)."""

    ql = str(question or "").lower()
    best = ""
    for kw in sorted(TIME_KEYWORDS, key=len, reverse=True):
        if kw in ql:
            return kw
    return best


def detect_time_semantics(question: str, available_columns: list[str] | None = None) -> TimeSemantics:
    """Detect time-series intent from raw user question.
    
    This function runs BEFORE any preprocessing or LLM processing to ensure
    time expressions are never lost.
    
    Args:
        question: Raw user question (unprocessed)
        available_columns: List of available column names from schema
        
    Returns:
        TimeSemantics object with detection results
        
    Rules:
        - If ANY time keyword is found → is_time_series = True
        - Default time_column = "ds" (if exists in schema)
        - Default time_granularity = "day"
        - Confidence based on number of matches
    """
    if not question or not isinstance(question, str):
        return TimeSemantics(
            is_time_series=False,
            time_grouping_detected=False,
            time_column="",
            time_granularity="",
            detected_keywords=[],
            confidence=0.0,
        )
    
    question_lower = question.lower().strip()
    detected_keywords = []
    
    # Check for time keywords
    for keyword in TIME_KEYWORDS:
        if keyword in question_lower:
            detected_keywords.append(keyword)
    
    # If no keywords found, not a time series
    if not detected_keywords:
        return TimeSemantics(
            is_time_series=False,
            time_grouping_detected=False,
            time_column="",
            time_granularity="",
            detected_keywords=[],
            confidence=0.0,
        )
    
    # Detect granularity
    time_granularity = "day"  # Default
    for granularity, patterns in GRANULARITY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, question_lower, re.IGNORECASE):
                time_granularity = granularity
                break
        if time_granularity != "day":
            break
    
    # Detect time column
    time_column = "ds"  # Default
    if available_columns:
        # Look for common time column names
        time_column_candidates = ["ds", "date", "time", "timestamp", "period", "day", "week", "month"]
        for candidate in time_column_candidates:
            if candidate in [col.lower() for col in available_columns]:
                time_column = candidate
                break
    
    # Calculate confidence
    confidence = min(1.0, len(detected_keywords) * 0.3)
    
    logger.info(
        "time_semantics_detected",
        extra={
            "is_time_series": True,
            "time_grouping_detected": True,
            "time_column": time_column,
            "time_granularity": time_granularity,
            "detected_keywords": detected_keywords,
            "confidence": confidence,
        },
    )
    
    return TimeSemantics(
        is_time_series=True,
        time_grouping_detected=True,
        time_column=time_column,
        time_granularity=time_granularity,
        detected_keywords=detected_keywords,
        confidence=confidence,
    )


def preserve_time_expressions(question: str) -> str:
    """Ensure time expressions are NEVER removed during preprocessing.
    
    This function should be called during preprocessing to protect time keywords.
    
    Args:
        question: Question text
        
    Returns:
        Question with time expressions preserved (unchanged)
    """
    # This is a no-op function that serves as a contract:
    # Preprocessing MUST NOT remove time expressions
    return question


def enrich_intent_with_time_semantics(
    intent: dict[str, Any],
    time_semantics: TimeSemantics,
) -> dict[str, Any]:
    """Enrich intent JSON with time semantics metadata.
    
    Args:
        intent: Intent JSON from LLM
        time_semantics: Detected time semantics
        
    Returns:
        Enriched intent with time metadata
    """
    enriched = dict(intent) if isinstance(intent, dict) else {}
    
    if time_semantics.is_time_series:
        enriched["is_time_series"] = True
        enriched["time_grouping_detected"] = time_semantics.time_grouping_detected
        enriched["group_by_time"] = True
        enriched["time_dimension"] = "ds"
        enriched["time_column"] = time_semantics.time_column or "ds"
        enriched["time_granularity"] = time_semantics.time_granularity
        enriched["time_semantics_confidence"] = time_semantics.confidence
        
        # Ensure dimensions include time column
        dimensions = enriched.get("dimensions", [])
        if not isinstance(dimensions, list):
            dimensions = []
        tc = time_semantics.time_column or "ds"
        if tc and tc not in dimensions:
            dimensions.insert(0, tc)
        enriched["dimensions"] = dimensions
    
    return enriched

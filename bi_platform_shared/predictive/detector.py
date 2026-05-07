"""
Single canonical predictive-question detector.

Replaces the four duplicated copies of ``_PREDICTIVE_KEYWORDS`` and
``_PREDICTIVE_PATTERNS`` that lived in:

    ai-service/intent_extraction/llm_extractor.py
    ai-service/reasoning_app/intent_classification_task.py
    ai-service/shared/sql_review.py
    ai-service/dagster_pipeline/assets/execution.py
    voice-service/voice_reports/services/forecasting_bridge.py

Adds explicit Arabic and French coverage so multi-language users get the same
"this is a forecast" routing decision regardless of phrasing.
"""

from __future__ import annotations

import re
from typing import FrozenSet, Iterable, Tuple


PREDICTIVE_KEYWORDS: FrozenSet[str] = frozenset({
    # English
    "forecast",
    "forecasts",
    "forecasting",
    "predict",
    "prediction",
    "predicting",
    "projected",
    "projection",
    "projections",
    "estimate",
    "estimates",
    "estimating",
    "anticipate",
    "expected",
    "expectation",
    "trend",
    "trends",
    "trending",
    "extrapolate",
    "extrapolation",
    "outlook",
    "future",
    "upcoming",
    # Arabic (forecast / predict / future / coming months)
    "توقع",
    "توقعات",
    "تنبؤ",
    "تنبؤات",
    "مستقبل",
    "مستقبلية",
    "سيكون",
    "ستكون",
    "القادمة",
    "القادم",
    "المقبل",
    "المقبلة",
    "الأشهر القادمة",
    "الأيام القادمة",
    # French (forecast / predict / coming months / next quarter)
    "prévision",
    "prévisions",
    "prévoir",
    "prévu",
    "prévue",
    "prévues",
    "prédire",
    "prédiction",
    "prochain",
    "prochains",
    "prochaine",
    "prochaines",
    "futur",
    "future",
    "tendance",
    "estimer",
    "estimation",
})


PREDICTIVE_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"\bnext\s+\d+\s+(day|days|week|weeks|month|months|quarter|quarters|year|years)\b", re.IGNORECASE),
    re.compile(r"\bnext\s+(week|month|quarter|year|period)\b", re.IGNORECASE),
    re.compile(r"\b(in|over|for)\s+(the\s+)?(next|coming|upcoming)\s+\d+", re.IGNORECASE),
    re.compile(r"\b(by|until)\s+(end of|the end of)\s+(this|next)\s+(week|month|quarter|year)\b", re.IGNORECASE),
    re.compile(r"\bwill\s+(be|reach|hit|exceed|drop|decline|grow|increase)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+will\b", re.IGNORECASE),
    re.compile(r"\bgoing\s+to\s+(be|reach|hit|happen)\b", re.IGNORECASE),
    re.compile(r"\bالأشهر\s+القادمة\b"),
    re.compile(r"\bالربع\s+القادم\b"),
    re.compile(r"\bالسنة\s+القادمة\b"),
    re.compile(r"\bprochain[s]?\s+(jour[s]?|semaine[s]?|mois|trimestre[s]?|année[s]?)\b", re.IGNORECASE),
    re.compile(r"\bdu\s+prochain\s+(trimestre|mois|semestre|année)\b", re.IGNORECASE),
)


def _tokenize(text: str) -> Iterable[str]:
    return (t for t in re.split(r"\s+", text.strip().lower()) if t)


def is_predictive(text: str) -> bool:
    """Return True when the question is asking for a forecast/projection.

    The check is intentionally conservative: it matches on whole-word keyword
    presence OR an explicit forward-looking time pattern (e.g. ``next 30
    days``). This is the deterministic pre-check used both by the classifier
    pre-pass and by the SQL review intent-alignment guard.
    """

    if not text:
        return False
    raw = str(text)
    lowered = raw.lower()

    # 1) Whole-word keyword match in English/Arabic/French.
    for kw in PREDICTIVE_KEYWORDS:
        if " " in kw:
            if kw in lowered:
                return True
        else:
            # Arabic / French letters break \b in some Python re builds, so do a
            # whitespace-aware fallback for non-ASCII tokens.
            if not kw.isascii():
                if kw in lowered:
                    return True
            else:
                if re.search(rf"\b{re.escape(kw)}\b", lowered):
                    return True

    # 2) Forward-looking phrase patterns.
    for pattern in PREDICTIVE_PATTERNS:
        if pattern.search(raw):
            return True

    return False


__all__ = ["PREDICTIVE_KEYWORDS", "PREDICTIVE_PATTERNS", "is_predictive"]

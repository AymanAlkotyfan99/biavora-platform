from __future__ import annotations

import json
import logging
import os
from typing import Any

from shared.chart_recommender import recommend_chart
from shared.chart_types import ChartType, normalize_chart_type


logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "google/gemma-3n-e4b-it:free"


def _to_bool(value: str | None, *, default: bool = True) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _extract_json_block(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _schema_columns(columns: list[Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for column in (columns or []):
        if isinstance(column, dict):
            name = str(column.get("name") or "").strip()
            col_type = str(column.get("type") or "").strip()
        else:
            name = str(column or "").strip()
            col_type = ""
        if not name:
            continue
        normalized.append({"name": name, "type": col_type})
    return normalized


def _prompt(*, question: str, intent: dict[str, Any], columns: list[dict[str, str]]) -> str:
    payload = {
        "question": str(question or "").strip(),
        "intent": intent if isinstance(intent, dict) else {},
        "schema_columns": columns,
        "allowed_chart_types": [
            ChartType.LINE.value,
            ChartType.LINE_MULTI.value,
            ChartType.BAR.value,
            ChartType.BAR_GROUPED.value,
            ChartType.BAR_STACKED.value,
            ChartType.PIE.value,
            ChartType.AREA.value,
            ChartType.SCATTER.value,
            ChartType.HISTOGRAM.value,
            ChartType.MAP.value,
            ChartType.COMBO_LINE_BAR.value,
            ChartType.CARD.value,
            ChartType.TABLE.value,
        ],
    }
    return (
        "You are a BI chart selector. Choose the single best chart type for the analytical question.\n"
        "Return strict JSON only with keys: chart_type, confidence, reasoning.\n"
        "STRICT CHART SELECTION RULES:\n"
        "- explicit chart request > percentage/share > distribution > relationship > comparison > time series.\n"
        "- If explicit chart type is requested, respect it unless impossible.\n"
        "- Percentage/share/ratio/proportion/contribution with one dimension + one metric => pie.\n"
        "- Use pie even with month/day/year labels unless user explicitly asks trend/evolution/over time.\n"
        "- Distribution/histogram => histogram (do not pick line because a time column exists).\n"
        "- Relationship/correlation between numeric metrics => scatter.\n"
        "- Trend/evolution over time => line/line_multi only when not overridden by higher-priority rules.\n"
        "- chart_type must be one value from allowed_chart_types.\n"
        "- confidence must be a number from 0 to 1.\n"
        "- reasoning must be short and concrete.\n\n"
        f"INPUT:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def _deterministic_fallback(*, question: str, intent: dict[str, Any], execution_result: dict[str, Any]) -> dict[str, Any]:
    fallback = recommend_chart(
        dataframe=execution_result,
        intent=intent if isinstance(intent, dict) else {},
        metadata={"query": question},
    )
    chart_type = normalize_chart_type(str(fallback.get("chart_type") or fallback.get("type") or ""), default=ChartType.TABLE.value)
    return {
        "chart_type": chart_type,
        "confidence": float(fallback.get("confidence", 0.6) or 0.6),
        "reasoning": str(fallback.get("reasoning") or "deterministic_fallback").strip(),
        "source": "deterministic_fallback",
        "model": "",
        "locked": True,
    }


def recommend_chart_with_gemma(
    *,
    question: str,
    intent: dict[str, Any],
    execution_result: dict[str, Any],
) -> dict[str, Any]:
    fallback = _deterministic_fallback(
        question=question,
        intent=intent if isinstance(intent, dict) else {},
        execution_result=execution_result if isinstance(execution_result, dict) else {},
    )
    fallback["source"] = "deterministic_policy"
    fallback["reasoning"] = "deterministic policy enforced"
    fallback["locked"] = True
    return fallback

"""Derive a :class:`~bi_platform_shared.contracts.chart.ChartContract` dict from ai-service payloads.

Kept free of Django imports so unit tests can validate chart-lock behaviour
without loading the full voice-service project stack.
"""

from __future__ import annotations

import logging
from typing import Any

from bi_platform_shared.contracts.chart import ChartContract, ChartTypeEnum, normalize_chart_type

logger = logging.getLogger(__name__)


def _intent_chart_contract_candidates(intent: dict[str, Any]) -> dict[str, Any]:
    """Build chart-contract fields from ``validated_intent`` / ``extracted_intent``."""

    if not isinstance(intent, dict) or not intent:
        return {}
    for key in ("validated_intent", "extracted_intent"):
        block = intent.get(key)
        if not isinstance(block, dict):
            continue
        chart_type = (
            str(block.get("final_chart_type") or "").strip()
            or str(block.get("selected_chart_type") or "").strip()
            or str(block.get("chart_type") or "").strip()
        )
        if not chart_type:
            continue
        metrics = block.get("metrics")
        y_axis: list[str] = []
        if isinstance(metrics, list):
            y_axis = [str(m).strip() for m in metrics if str(m or "").strip()]
        elif isinstance(metrics, str) and metrics.strip():
            y_axis = [metrics.strip()]
        x_axis = (
            str(block.get("time_column") or "").strip()
            or str(block.get("x_axis") or "").strip()
            or str(block.get("period") or "").strip()
        ) or None
        locked = bool(block.get("chart_lock") or block.get("explicit_chart_lock") or block.get("locked"))
        return {
            "chart_type": chart_type.lower(),
            "x_axis": x_axis,
            "y_axis": y_axis,
            "locked": locked,
            "explicit_chart_lock": locked,
            "chart_source": "ai_service_intent",
        }
    return {}


def contract_dict_from_ai_result(ai_result: dict[str, Any]) -> dict[str, Any]:
    """Strict: require a valid chart contract from ai-service (no table fallback)."""

    payload = ai_result if isinstance(ai_result, dict) else {}
    raw_contract = payload.get("chart_contract") if isinstance(payload.get("chart_contract"), dict) else {}
    if not raw_contract:
        legacy = payload.get("chart") if isinstance(payload.get("chart"), dict) else {}
        if legacy:
            raw_contract = legacy
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    if not raw_contract and isinstance(intent.get("chart_contract"), dict):
        raw_contract = intent["chart_contract"]
    if not raw_contract:
        raw_contract = _intent_chart_contract_candidates(intent)

    if not raw_contract:
        raise ValueError("missing_chart_contract_from_ai")

    try:
        return ChartContract.model_validate(raw_contract).model_dump(mode="json")
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "ai_chart_contract_invalid",
            extra={"error": str(exc), "raw_chart_type": raw_contract.get("chart_type")},
        )
        raise ValueError(f"invalid_chart_contract_from_ai:{exc}") from exc

"""Regression: chart contract must survive missing top-level ``chart_contract`` (intent fallbacks)."""

from __future__ import annotations

import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
# voice-service → services → BI-Voice-Agent (repo root containing bi_platform_shared)
REPO_ROOT = Path(__file__).resolve().parents[3]
for path in (SERVICE_ROOT, REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from voice_reports.domain.chart_from_ai_result import contract_dict_from_ai_result  # noqa: E402


def test_compare_sales_customers_line_multi_from_validated_intent():
    ai_result = {
        "chart_contract": {},
        "intent": {
            "validated_intent": {
                "final_chart_type": "line_multi",
                "time_column": "ds",
                "metrics": ["total_sales", "customers"],
                "chart_lock": True,
            }
        },
    }
    contract = contract_dict_from_ai_result(ai_result)
    assert contract["chart_type"] == "line_multi"
    assert contract["x_axis"] == "ds"
    assert contract["y_axis"] == ["total_sales", "customers"]
    assert contract.get("locked") is True


def test_missing_contract_raises():
    try:
        contract_dict_from_ai_result({"chart_contract": {}, "intent": {}})
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "missing_chart_contract_from_ai" in str(exc)

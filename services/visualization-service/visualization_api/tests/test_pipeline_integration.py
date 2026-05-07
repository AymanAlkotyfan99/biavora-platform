import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock


AI_SERVICE_PATH = os.path.abspath("services/ai-service")
if AI_SERVICE_PATH not in sys.path:
    sys.path.insert(0, AI_SERVICE_PATH)

from shared.chart_recommender import recommend_chart  # noqa: E402


SERVICE_PATH = Path(__file__).resolve().parents[1] / "services" / "metabase_service.py"
spec = importlib.util.spec_from_file_location("metabase_service_under_test", SERVICE_PATH)
metabase_service = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(metabase_service)
MetabaseService = metabase_service.MetabaseService


class _FakeResponse:
    status_code = 201
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _service():
    service = MetabaseService()
    service._request = MagicMock(return_value=_FakeResponse({"id": 456}))
    return service


def test_full_pipeline_ai_to_visualization_for_grouped_bar():
    data = {
        "columns": [
            {"name": "region", "type": "String"},
            {"name": "sales", "type": "Float64"},
            {"name": "profit", "type": "Float64"},
        ],
        "rows": [{"region": "north", "sales": 12, "profit": 3}],
    }
    intent = {
        "intent": "comparison",
        "metrics": [{"column": "sales"}, {"column": "profit"}],
        "dimensions": ["region"],
    }
    recommendation = recommend_chart(dataframe=data, intent=intent, metadata={})
    assert recommendation["chart_type"] == "bar_grouped"

    voice_settings = {
        "selected_chart_type": recommendation["chart_type"],
        "chart_type": recommendation["chart_type"],
        "display": recommendation["chart_type"],
        "graph.dimensions": ["region"],
        "graph.metrics": ["sales", "profit"],
        "category_columns": ["region"],
        "numeric_columns": ["sales", "profit"],
        "reasoning": recommendation["reasoning"],
    }
    service = _service()
    result = service.create_question(name="integration", sql="SELECT ...", visualization_settings=voice_settings)
    assert result == 456
    payload = service._request.call_args.kwargs["json"]
    assert payload["display"] == "bar"
    assert payload["visualization_settings"]["fallback_applied"] is False


def test_pipeline_edge_case_empty_dataset_falls_back_to_table():
    recommendation = recommend_chart(
        dataframe={"columns": [{"name": "x", "type": "String"}], "rows": []},
        intent={"intent": "comparison"},
        metadata={},
    )
    assert recommendation["chart_type"] == "table"


def test_pipeline_edge_case_ambiguous_multi_metrics_prefers_line_multi():
    recommendation = recommend_chart(
        dataframe={
            "columns": [
                {"name": "period", "type": "Date"},
                {"name": "sales", "type": "Float64"},
                {"name": "orders", "type": "Float64"},
            ],
            "rows": [{"period": "2026-01-01", "sales": 10, "orders": 5}],
        },
        intent={
            "intent": "time_series",
            "metrics": [{"column": "sales"}, {"column": "orders"}],
            "dimensions": ["period"],
        },
        metadata={},
    )
    assert recommendation["chart_type"] == "line_multi"

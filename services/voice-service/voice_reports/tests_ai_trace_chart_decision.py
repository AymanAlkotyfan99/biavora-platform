import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[0] / "services" / "ai_trace_service.py"
spec = importlib.util.spec_from_file_location("voice_ai_trace_under_test", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)
build_ai_trace_payload = mod.build_ai_trace_payload


def test_ai_trace_includes_chart_decision_chain():
    trace = build_ai_trace_payload(
        report_id=1,
        transcription="show sales as pie chart",
        preprocessing_low={},
        preprocessing_high={},
        intent_json={},
        pipeline_trace={},
        generated_sql="SELECT 1",
        reviewed_sql="SELECT 1",
        query_result={"columns": ["category", "value"], "rows": [{"category": "a", "value": 1}]},
        execution_time_ms=10,
        row_count=1,
        chart_type="bar",
        metabase_question_id=1,
        metabase_dashboard_id=1,
        embed_url="",
        chart_config={
            "upstream_chart_type": "pie",
            "selected_chart_type": "bar",
            "chart_type": "bar",
            "chart_locked": True,
            "explicit_chart_lock": True,
            "overwritten_by": "report-service",
            "fallback_reason": "shape_fallback",
            "reason_chart_selected": "shape_fallback",
        },
        error_message="",
    )
    decision = trace.get("chart_decision_trace", {})
    assert decision.get("upstream_chart") == "pie"
    assert decision.get("final_chart") == "bar"
    assert decision.get("overwritten") is True
    assert decision.get("overwritten_by") == "report-service"
    chain = decision.get("decision_chain", [])
    assert isinstance(chain, list) and len(chain) >= 2


def test_ai_trace_visualization_prefers_canonical_chart_contract():
    trace = build_ai_trace_payload(
        report_id=2,
        transcription="relationship between sales and orders",
        preprocessing_low={},
        preprocessing_high={},
        intent_json={},
        pipeline_trace={},
        generated_sql="SELECT total_sales, orders FROM etl.sales",
        reviewed_sql="SELECT total_sales, orders FROM etl.sales",
        query_result={"columns": ["total_sales", "orders"], "rows": [{"total_sales": 10, "orders": 3}]},
        execution_time_ms=10,
        row_count=1,
        chart_type="table",
        metabase_question_id=22,
        metabase_dashboard_id=None,
        embed_url="",
        chart_config={
            "chart_type": "table",
            "render_status": "success",
            "contract_preserved": True,
            "chart_contract": {"type": "scatter", "chart_type": "scatter", "locked": True},
        },
        error_message="",
    )
    assert trace["visualization"]["chart_type"] == "scatter"
    assert trace["visualization"]["metabase_question_id"] == 22
    assert trace["visualization"]["render_status"] == "success"
    assert trace["visualization"]["contract_preserved"] is True

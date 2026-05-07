import unittest
import sys
import types

if "clickhouse_connect" not in sys.modules:
    sys.modules["clickhouse_connect"] = types.SimpleNamespace(get_client=lambda **_kwargs: None)
if "jwt" not in sys.modules:
    sys.modules["jwt"] = types.SimpleNamespace(encode=lambda *_args, **_kwargs: "")

from voice_reports.services.ai_trace_service import build_ai_trace_payload


class AITraceServiceTests(unittest.TestCase):
    def test_classification_error_is_cleared_when_preprocessing_high_succeeds_with_corrections(self):
        trace = build_ai_trace_payload(
            report_id=10,
            transcription="How do customers impact totol sales?",
            preprocessing_low={"cleaned_text": "How do customers impact totol sales?"},
            preprocessing_high={
                "status": "success",
                "final_query": "How do customers relationship total sales?",
                "term_corrections": [{"from": "totol", "to": "total_sales", "type": "fuzzy_phrase"}],
                "user_friendly_messages": ["Corrected 'totol' to 'total_sales'."],
            },
            intent_json={"intent_type": "analytical"},
            pipeline_trace={
                "classification": {
                    "status": "failed",
                    "final_output": {"message": "temporary upstream issue"},
                    "errors": [{"type": "system", "message": "temporary upstream issue"}],
                },
                "preprocessing_high": {
                    "status": "success",
                    "final_output": {"final_query": "How do customers relationship total sales?"},
                    "errors": [],
                },
            },
            generated_sql="SELECT customers, total_sales FROM sales_3months_realistic_csv",
            reviewed_sql="SELECT customers, total_sales FROM sales_3months_realistic_csv",
            query_result={"columns": ["customers", "total_sales"], "rows": [{"customers": 10, "total_sales": 100.0}]},
            execution_time_ms=12,
            row_count=1,
            chart_type="scatter",
            metabase_question_id=1,
            metabase_dashboard_id=2,
            embed_url="",
            chart_config={},
            error_message="",
        )

        self.assertFalse(bool(trace["classification"]["error"]))
        self.assertIn("term_corrections", trace["preprocessing_high"])
        self.assertTrue(trace["preprocessing_high"]["term_corrections"])

    def test_classification_error_is_cleared_when_preprocessing_high_is_degraded(self):
        trace = build_ai_trace_payload(
            report_id=11,
            transcription="How does sales change over time?",
            preprocessing_low={"cleaned_text": "How does sales change over time?"},
            preprocessing_high={
                "status": "degraded",
                "final_query": "How does total_sales change over time?",
                "term_corrections": [{"from": "sales", "to": "total_sales", "type": "mapped"}],
            },
            intent_json={"intent_type": "analytical"},
            pipeline_trace={
                "classification": {
                    "status": "failed",
                    "final_output": {"message": "temporary upstream issue"},
                    "errors": [{"type": "system", "message": "temporary upstream issue"}],
                },
                "preprocessing_high": {
                    "status": "degraded",
                    "final_output": {"final_query": "How does total_sales change over time?"},
                    "errors": [],
                },
            },
            generated_sql="SELECT toDate(ds) AS period, SUM(total_sales) AS sum_total_sales FROM etl.sales GROUP BY period",
            reviewed_sql="SELECT toDate(ds) AS period, SUM(total_sales) AS sum_total_sales FROM etl.sales GROUP BY period",
            query_result={"columns": ["period", "sum_total_sales"], "rows": [{"period": "2023-01-01", "sum_total_sales": 100.0}]},
            execution_time_ms=19,
            row_count=1,
            chart_type="line",
            metabase_question_id=2,
            metabase_dashboard_id=3,
            embed_url="",
            chart_config={},
            error_message="",
        )

        self.assertFalse(bool(trace["classification"]["error"]))

    def test_forecasting_horizon_parses_numeric_hint_without_raising(self):
        trace = build_ai_trace_payload(
            report_id=12,
            transcription="Forecast total sales for next 7 days",
            preprocessing_low={"cleaned_text": "Forecast total sales for next 7 days"},
            preprocessing_high={},
            intent_json={"question_type": "predictive"},
            pipeline_trace={
                "classification": {"status": "success", "final_output": {"question_type": "predictive"}},
                "forecasting": {"status": "success", "final_output": {}},
            },
            generated_sql="SELECT ds, total_sales FROM etl.sales",
            reviewed_sql="SELECT ds, total_sales FROM etl.sales",
            query_result={
                "columns": ["ds", "value", "series_type"],
                "rows": [
                    {"ds": "2026-05-01", "value": 100.0, "series_type": "actual"},
                    {"ds": "2026-05-02", "value": 110.0, "series_type": "forecast"},
                ],
            },
            execution_time_ms=10,
            row_count=2,
            chart_type="line_multi",
            metabase_question_id=3,
            metabase_dashboard_id=4,
            embed_url="",
            chart_config={
                "forecasting": {
                    "status": "success",
                    "request": {"requires_forecast": True, "horizon": "next 7 days"},
                    "meta": {"time_column": "ds", "value_column": "total_sales"},
                }
            },
            error_message="",
        )

        self.assertIn("forecasting", trace)
        self.assertEqual(trace["forecasting"]["horizon"], 7)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("services/ai-service"))

from forecasting.dagster_handler import run_forecasting_handler
from forecasting.pipeline import build_forecast_dataset, detect_forecast_request
from intent_extraction.routing import build_sql_from_intent


class ForecastingPipelineTests(unittest.TestCase):
    def test_predictive_invariant_forces_requires_forecast(self):
        request = detect_forecast_request(
            intent={"intent_type": "predictive", "requires_forecast": False},
            question_type="predictive",
            final_route="metabase",
        )
        self.assertTrue(request.requires_forecast)
        self.assertEqual(request.question_type, "predictive")
        self.assertEqual(request.reason, "predictive_invariant")

    @patch.dict(os.environ, {"TIMESFM_MIN_POINTS": "5"}, clear=False)
    @patch("forecasting.pipeline.forecast")
    def test_actual_vs_forecast_visualization_has_explicit_series_metadata(self, mock_forecast):
        mock_forecast.return_value = {
            "point_forecast": [16, 17],
            "model_status": {"provider": "test", "used_fallback": False},
            "quantiles": {},
        }
        rows = [
            {"ds": "2026-01-01", "value": 10},
            {"ds": "2026-01-02", "value": 11},
            {"ds": "2026-01-03", "value": 12},
            {"ds": "2026-01-04", "value": 13},
            {"ds": "2026-01-05", "value": 14},
        ]
        result = build_forecast_dataset(
            columns=["ds", "value"],
            rows=rows,
            intent={"time_column": "ds", "metric": "value", "forecast_horizon": 2},
        )
        self.assertTrue(result["meta"]["forecast_available"])
        self.assertEqual(result["meta"]["forecast_boundary_index"], 5)
        self.assertEqual(result["meta"]["forecast_start_date"], "2026-01-06")
        self.assertIn("series_label", result["columns"])
        self.assertIn("preferred_color_role", result["columns"])
        roles = {row["series_type"]: row["preferred_color_role"] for row in result["rows"]}
        self.assertEqual(roles["actual"], "actual")
        self.assertEqual(roles["forecast"], "forecast")
        config_by_type = {item["series_type"]: item for item in result["meta"]["chart_series_config"]}
        self.assertNotEqual(config_by_type["actual"]["preferred_color"], config_by_type["forecast"]["preferred_color"])

    @patch.dict(os.environ, {"TIMESFM_MIN_POINTS": "5"}, clear=False)
    @patch("forecasting.dagster_handler.build_forecast_dataset")
    def test_forecasting_handler_preserves_chart_series_config(self, mock_build_forecast_dataset):
        mock_build_forecast_dataset.return_value = {
            "columns": ["ds", "value", "series_type", "series_label", "preferred_color_role"],
            "rows": [
                {"ds": "2026-01-01", "value": 10, "series_type": "actual", "series_label": "Actual", "preferred_color_role": "actual"},
                {"ds": "2026-01-02", "value": 12, "series_type": "forecast", "series_label": "Forecast", "preferred_color_role": "forecast"},
            ],
            "sql": "SELECT ds, value, series_type FROM forecast",
            "meta": {
                "forecast_available": True,
                "visualization_mode": "historical_plus_forecast",
                "fallback_reason": "",
                "chart_series_config": [
                    {"series_type": "actual", "series_label": "Actual", "preferred_color_role": "actual", "preferred_color": "#2563eb"},
                    {"series_type": "forecast", "series_label": "Forecast", "preferred_color_role": "forecast", "preferred_color": "#f97316"},
                ],
            },
        }
        result = run_forecasting_handler(
            {
                "historical_data": {"columns": ["ds", "value"], "rows": [{"ds": "2026-01-01", "value": 10}]},
                "intent": {"intent_type": "predictive", "forecast_horizon": 1},
            }
        )
        payload = result["visualization_payload"]
        self.assertEqual(result["status"], "success")
        self.assertFalse(result["degraded"])
        self.assertEqual(payload["chart_type"], "line")
        self.assertEqual(payload["series_type_field"], "series_type")
        self.assertEqual(payload["preferred_color_role_field"], "preferred_color_role")
        self.assertEqual({item["series_type"] for item in payload["chart_series_config"]}, {"actual", "forecast"})

    @patch.dict(os.environ, {"TIMESFM_MIN_POINTS": "20"}, clear=False)
    def test_time_column_selection_skips_metadata_and_falls_back_historical_when_insufficient(self):
        columns = ["_extracted_at", "ds", "value"]
        rows = [
            {"_extracted_at": "2026-01-01", "ds": "2026-01-01", "value": 10},
            {"_extracted_at": "2026-01-02", "ds": "2026-01-02", "value": 12},
            {"_extracted_at": "2026-01-03", "ds": "2026-01-03", "value": 13},
        ]
        result = build_forecast_dataset(columns=columns, rows=rows, intent={"time_column": "ds"})
        meta = result["meta"]
        self.assertEqual(meta["time_column"], "ds")
        self.assertEqual(meta["selected_time_column_reason"], "intent_requested_time_column")
        self.assertFalse(meta["forecast_available"])
        self.assertEqual(meta["visualization_mode"], "historical_only")

    @patch.dict(os.environ, {"TIMESFM_MIN_POINTS": "5"}, clear=False)
    def test_inconsistent_spacing_returns_historical_only_mode(self):
        columns = ["ds", "value"]
        rows = [
            {"ds": "2026-01-01", "value": 1},
            {"ds": "2026-01-02", "value": 2},
            {"ds": "2026-01-10", "value": 3},
            {"ds": "2026-01-11", "value": 4},
            {"ds": "2026-02-15", "value": 5},
            {"ds": "2026-02-16", "value": 6},
        ]
        result = build_forecast_dataset(columns=columns, rows=rows, intent={"granularity": "day"})
        meta = result["meta"]
        self.assertFalse(meta["forecast_available"])
        self.assertEqual(meta["visualization_mode"], "historical_only")
        self.assertIn("spacing", meta["fallback_reason"])

    @patch.dict(os.environ, {"TIMESFM_MIN_POINTS": "20"}, clear=False)
    def test_technical_time_column_hint_is_rejected_and_business_time_is_used(self):
        columns = ["_cleaned_at", "ds", "value"]
        rows = [
            {"_cleaned_at": "2026-01-01", "ds": "2026-01-01", "value": 10},
            {"_cleaned_at": "2026-01-02", "ds": "2026-01-02", "value": 12},
            {"_cleaned_at": "2026-01-03", "ds": "2026-01-03", "value": 13},
        ]
        result = build_forecast_dataset(columns=columns, rows=rows, intent={"time_column": "_cleaned_at"})
        self.assertEqual(result["meta"]["time_column"], "ds")

    def test_predictive_sql_builder_enforces_ds_value_group_and_order(self):
        schema = {
            "sales_fact": [
                {"name": "order_date", "type": "DateTime"},
                {"name": "total_sales", "type": "Float64"},
            ]
        }
        intent = {
            "intent_type": "predictive",
            "table": "sales_fact",
            "metric": "total_sales",
            "time_column": "order_date",
            "granularity": "day",
            "forecast_horizon": 7,
            "requires_forecast": True,
            "question_type": "predictive",
        }
        normalized, sql = build_sql_from_intent(query="Forecast total sales for next 7 days", intent=intent, schema=schema)
        self.assertIn(" AS ds", sql)
        self.assertIn(" AS value", sql)
        self.assertIn("GROUP BY ds", sql)
        self.assertIn("ORDER BY ds ASC", sql)
        self.assertEqual(normalized["requires_forecast"], True)
        self.assertEqual(normalized["question_type"], "predictive")
        self.assertIn("aggregation", normalized)
        self.assertEqual(str(normalized.get("aggregation", "")).upper(), "SUM")
        self.assertEqual(normalized["intent"], "forecast")

    def test_predictive_sql_builder_does_not_wrap_ds_in_todate(self):
        schema = {
            "sales_fact": [
                {"name": "ds", "type": "Date"},
                {"name": "total_sales", "type": "Float64"},
            ]
        }
        intent = {
            "intent_type": "predictive",
            "table": "sales_fact",
            "metric": "total_sales",
            "time_column": "ds",
            "granularity": "day",
            "forecast_horizon": 7,
            "requires_forecast": True,
            "question_type": "predictive",
        }
        _, sql = build_sql_from_intent(query="Forecast total sales for next 7 days", intent=intent, schema=schema)
        self.assertIn("SELECT ds AS ds", sql)
        self.assertNotIn("toDate(ds)", sql)

    def test_population_dataset_does_not_switch_tables_for_sales_question(self):
        schema = {
            "population_distribution_csv": [
                {"name": "ds", "type": "Date"},
                {"name": "population_total", "type": "Float64"},
            ]
        }
        intent = {
            "intent_type": "predictive",
            "table": "population_distribution_csv",
            "metric": "total_sales",
            "time_column": "ds",
            "granularity": "day",
            "forecast_horizon": 7,
            "requires_forecast": True,
            "question_type": "predictive",
        }
        with self.assertRaises(Exception):
            build_sql_from_intent(query="Forecast total sales", intent=intent, schema=schema)

    @patch("intent_extraction.routing.validate_sql")
    def test_predictive_sql_builder_auto_selects_best_table_when_not_provided(self, _mock_validate_sql):
        schema = {
            "events": [
                {"name": "id", "type": "UInt64"},
                {"name": "created_at", "type": "DateTime"},
            ],
            "orders_fact": [
                {"name": "ds", "type": "Date"},
                {"name": "orders_count", "type": "Float64"},
            ],
        }
        intent = {
            "intent_type": "predictive",
            "table": "",
            "metric": "orders_count",
            "time_column": "ds",
            "granularity": "day",
            "forecast_horizon": 7,
            "requires_forecast": True,
            "question_type": "predictive",
        }
        normalized, _sql = build_sql_from_intent(
            query="Predict number of orders for next week",
            intent=intent,
            schema=schema,
        )
        self.assertEqual(normalized["table"], "orders_fact")

    @patch("forecasting.dagster_handler.build_forecast_dataset")
    def test_forecasting_handler_marks_forecast_error_as_degraded(self, mock_build_forecast_dataset):
        from forecasting.pipeline import ForecastingError

        mock_build_forecast_dataset.side_effect = ForecastingError("timesfm_unavailable", "TimesFM unavailable")
        result = run_forecasting_handler(
            {
                "historical_data": {"columns": ["ds", "value"], "rows": [{"ds": "2026-01-01", "value": 10}]},
                "intent": {"intent_type": "predictive"},
            }
        )
        self.assertEqual(result.get("status"), "degraded")
        self.assertTrue(result.get("degraded"))
        self.assertEqual(result.get("degradation_reason"), "timesfm_unavailable")

    @patch.dict(os.environ, {"TIMESFM_MIN_POINTS": "5"}, clear=False)
    @patch("forecasting.pipeline.forecast")
    def test_predict_next_7_days_returns_90_actual_plus_7_forecast_sorted_daily(self, mock_forecast):
        mock_forecast.return_value = {
            "point_forecast": [2300, 2310, 2320, 2330, 2340, 2350, 2360],
            "model_status": {"provider": "test", "used_fallback": False},
            "quantiles": {},
        }
        start = date(2023, 1, 1)
        rows = []
        for idx in range(90):
            current = start + timedelta(days=idx)
            rows.append(
                {
                    "ds": f"{current.month}/{current.day}/{current.year}",
                    "total_sales": 1000 + idx,
                }
            )

        result = build_forecast_dataset(
            columns=["ds", "total_sales"],
            rows=rows,
            intent={"time_column": "ds", "metric": "total_sales", "granularity": "day", "forecast_horizon": 7},
        )
        output_rows = result["rows"]
        actual_rows = [row for row in output_rows if row.get("series_type") == "actual"]
        forecast_rows = [row for row in output_rows if row.get("series_type") == "forecast"]

        self.assertEqual(len(actual_rows), 90)
        self.assertEqual(len(forecast_rows), 7)
        self.assertEqual(actual_rows[0]["ds"], "2023-01-01")
        self.assertEqual(actual_rows[-1]["ds"], "2023-03-31")
        self.assertEqual([row["ds"] for row in forecast_rows], [
            "2023-04-01",
            "2023-04-02",
            "2023-04-03",
            "2023-04-04",
            "2023-04-05",
            "2023-04-06",
            "2023-04-07",
        ])

        sorted_ds = [row["ds"] for row in output_rows]
        self.assertEqual(sorted_ds, sorted(sorted_ds))
        self.assertEqual(result["meta"]["granularity"], "day")
        self.assertEqual(result["meta"]["forecast_start_date"], "2023-04-01")

    @patch.dict(os.environ, {"TIMESFM_MIN_POINTS": "5"}, clear=False)
    @patch("forecasting.pipeline.forecast")
    def test_forecasting_handler_visualization_payload_line_and_daily(self, mock_forecast):
        mock_forecast.return_value = {
            "point_forecast": [11, 12, 13, 14, 15, 16, 17],
            "model_status": {"provider": "test", "used_fallback": False},
            "quantiles": {},
        }
        rows = [
            {"ds": f"1/{day}/2023", "value": float(day)}
            for day in range(1, 91)
        ]
        result = run_forecasting_handler(
            {
                "historical_data": {"columns": ["ds", "value"], "rows": rows},
                "intent": {"intent_type": "predictive", "time_column": "ds", "metric": "value", "granularity": "day", "forecast_horizon": 7},
            }
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["visualization_payload"]["chart_type"], "line")
        self.assertEqual(result["forecast_meta"].get("granularity"), "day")


if __name__ == "__main__":
    unittest.main()

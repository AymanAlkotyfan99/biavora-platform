from __future__ import annotations

import json
import logging
import os
import unittest
from unittest.mock import patch

from intent_extraction.error_handler import (
    IntentExtractionModelOutputError,
    IntentExtractionSchemaMismatchError,
    IntentExtractionSystemError,
)
from intent_extraction.intent_extraction_task import (
    _apply_chart_intent_fallback,
    intent_extraction_task,
    run_intent_extraction_stage,
)
from intent_extraction.llm_extractor import extract_structured_intent, infer_intent_type
from intent_extraction.predictive_parser import parse_predictive_intent
from intent_extraction.routing import build_sql_from_intent
from intent_extraction.schemas import IntentExtractionConfig
from intent_extraction.validation import validate_structured_intent


TEST_SCHEMA = {
    "sales_fact": [
        {"name": "region", "type": "String"},
        {"name": "order_date", "type": "Date"},
        {"name": "revenue", "type": "Float64"},
        {"name": "profit", "type": "Float64"},
        {"name": "orders", "type": "Int64"},
        {"name": "customer_id", "type": "UInt64"},
    ]
}


class IntentTypeDetectionTests(unittest.TestCase):
    def test_predictive_keyword_detection(self):
        self.assertEqual(
            infer_intent_type(query="Predict revenue for next quarter", hinted_intent_type=None),
            "predictive",
        )

    def test_analytical_default_detection(self):
        self.assertEqual(
            infer_intent_type(query="Show total revenue by region", hinted_intent_type=None),
            "analytical",
        )

    def test_hinted_intent_type_takes_priority(self):
        self.assertEqual(
            infer_intent_type(query="show revenue", hinted_intent_type="predictive"),
            "predictive",
        )

    def test_next_keyword_forces_predictive_detection(self):
        self.assertEqual(
            infer_intent_type(query="What is revenue for next period?", hinted_intent_type=None),
            "predictive",
        )

    def test_what_will_be_forces_predictive_detection(self):
        self.assertEqual(
            infer_intent_type(query="What will be the total sales for next month?", hinted_intent_type=None),
            "predictive",
        )


class PredictiveParserTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.setdefault("CLICKHOUSE_DATABASE", "etl")
        self._validate_patcher = patch("intent_extraction.routing.validate_sql", lambda _sql: None)
        self._validate_patcher.start()

    def tearDown(self) -> None:
        if hasattr(self, "_validate_patcher"):
            self._validate_patcher.stop()

    def test_parser_accepts_ds_string_column_as_time_dimension(self):
        schema = {
            "sales_3months_realistic_csv": [
                {"name": "ds", "type": "String"},
                {"name": "total_sales", "type": "Float64"},
                {"name": "orders", "type": "Int64"},
            ]
        }

        parsed = parse_predictive_intent(
            query="Forecast total sales for the next 7 days",
            schema=schema,
        )

        self.assertEqual(parsed["intent_type"], "predictive")
        self.assertEqual(parsed["time_column"], "ds")
        self.assertEqual(parsed["metric"], "total_sales")
        self.assertEqual(parsed["horizon"], 7)

    def test_predictive_sql_builder_casts_string_date_for_week_grouping(self):
        schema = {
            "sales_3months_realistic_csv": [
                {"name": "ds", "type": "String"},
                {"name": "customers", "type": "UInt64"},
            ]
        }
        intent = parse_predictive_intent(
            query="Predict the number of customers for the next 2 weeks",
            schema=schema,
        )
        intent["granularity"] = "week"
        _, sql = build_sql_from_intent(
            query="Predict the number of customers for the next 2 weeks",
            intent=intent,
            schema=schema,
        )
        self.assertIn("toStartOfWeek(coalesce(parseDateTimeBestEffortUSOrNull(ds), parseDateTimeBestEffortOrNull(ds)))", sql)

    def test_predictive_sql_builder_casts_string_date_for_day_grouping(self):
        schema = {
            "sales_3months_realistic_csv": [
                {"name": "ds", "type": "String"},
                {"name": "customers", "type": "UInt64"},
            ]
        }
        intent = parse_predictive_intent(
            query="Predict the number of customers for the next 7 days",
            schema=schema,
        )
        intent["granularity"] = "day"
        _, sql = build_sql_from_intent(
            query="Predict the number of customers for the next 7 days",
            intent=intent,
            schema=schema,
        )
        self.assertIn("toDate(coalesce(parseDateTimeBestEffortUSOrNull(ds), parseDateTimeBestEffortOrNull(ds)))", sql)


class IntentExtractionTaskTests(unittest.TestCase):
    def test_validate_structured_intent_allows_count_star_metric(self):
        intent = {
            "intent_type": "analytical",
            "metrics": ["*"],
            "metric_specs": [{"column": "*", "aggregation": "COUNT"}],
            "dimensions": ["region"],
            "filters": [],
            "time_range": "all_time",
            "aggregation": "COUNT",
            "target_column": "*",
            "table": "sales_fact",
            "order_by": [{"column": "region", "direction": "ASC"}],
            "limit": 5,
            "ranking": {"direction": "DESC"},
            "operations": ["aggregation", "grouping", "ranking", "limiting"],
            "ambiguities": [],
        }
        validated = validate_structured_intent(intent=intent, schema=TEST_SCHEMA)
        self.assertEqual(validated["metrics"], ["*"])
        self.assertEqual(validated["aggregation"], "COUNT")
        self.assertEqual(validated["table"], "sales_fact")
        self.assertEqual(validated["limit"], 5)
        self.assertEqual(validated["order_by"][0]["direction"], "ASC")

    @patch("intent_extraction.intent_extraction_task.extract_structured_intent")
    def test_stage_uses_deterministic_fallback_when_llm_is_unavailable(self, mock_extract):
        mock_extract.side_effect = IntentExtractionSystemError("Ollama unavailable")

        result = run_intent_extraction_stage(query="Show total revenue by region", schema=TEST_SCHEMA)

        self.assertIn(result["status"], {"success", "degraded"})
        self.assertEqual(result["intent_type"], "analytical")
        if result["status"] == "degraded":
            self.assertEqual(result.get("degradation_reason"), "intent_extraction_llm_fallback")
            self.assertTrue(result.get("debug_metadata", {}).get("llm_fallback_used"))
            self.assertTrue(result.get("warnings"))

    @patch("intent_extraction.intent_extraction_task.validate_structured_intent")
    @patch("intent_extraction.intent_extraction_task.extract_structured_intent")
    def test_stage_applies_percentage_and_pie_fallback_before_validation(
        self,
        mock_extract,
        mock_validate,
    ):
        extracted = {
            "intent_type": "analytical",
            "intent": "aggregation",
            "metrics": ["revenue"],
            "metric_specs": [{"column": "revenue", "aggregation": "SUM"}],
            "dimensions": ["order_date"],
            "filters": [],
            "time_range": "all_time",
            "aggregation": "SUM",
            "target_column": "revenue",
            "table": "sales_fact",
            "order_by": [],
            "limit": None,
            "ranking": {},
            "operations": ["projection", "aggregation", "grouping"],
            "ambiguities": [],
        }
        mock_extract.return_value = extracted
        mock_validate.side_effect = lambda intent, schema: intent

        result = run_intent_extraction_stage(
            query="Show the percentage share of revenue by month as a pie chart",
            schema=TEST_SCHEMA,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["extracted_intent"].get("metric_type"), "percentage")
        self.assertEqual(result["extracted_intent"].get("selected_chart_type"), "pie")
        self.assertEqual(result["extracted_intent"].get("chart_type"), "pie")
        self.assertEqual((result["extracted_intent"].get("chart") or {}).get("type"), "pie")
        self.assertTrue(result.get("debug_metadata", {}).get("chart_intent_fallback_applied"))
        self.assertIn(
            "Detected 'percentage share' -> pie chart",
            str(result.get("debug_metadata", {}).get("chart_intent_fallback_reason", "")),
        )

    @patch("intent_extraction.intent_extraction_task.route_intent")
    @patch("intent_extraction.intent_extraction_task.validate_structured_intent")
    @patch("intent_extraction.intent_extraction_task.extract_structured_intent")
    def test_analytical_route_success(
        self,
        mock_extract,
        mock_validate,
        mock_route,
    ):
        extracted = {
            "intent_type": "analytical",
            "metrics": ["revenue"],
            "dimensions": ["region"],
            "filters": [],
            "time_range": "last month",
            "aggregation": "SUM",
            "target_column": "revenue",
            "table": "sales_fact",
        }
        mock_extract.return_value = extracted
        mock_validate.return_value = extracted
        mock_route.return_value = {
            "sql_query": "SELECT region, SUM(revenue) AS sum_revenue FROM etl.sales_fact GROUP BY region;",
            "next_step": "metabase",
            "normalized_intent": {"table": "sales_fact"},
            "execution_result": {"rows": []},
            "downstream_result": {"status": "pending_integration"},
        }

        result = intent_extraction_task.fn(query="Show total revenue by region", schema=TEST_SCHEMA)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["intent_type"], "analytical")
        self.assertEqual(result["next_step"], "metabase")
        self.assertEqual(result["error_type"], "none")
        self.assertEqual(result["action_taken"], "proceed")

    @patch("intent_extraction.intent_extraction_task.route_intent")
    @patch("intent_extraction.intent_extraction_task.validate_structured_intent")
    @patch("intent_extraction.intent_extraction_task.extract_structured_intent")
    def test_predictive_route_success(
        self,
        mock_extract,
        mock_validate,
        mock_route,
    ):
        extracted = {
            "intent_type": "predictive",
            "metrics": ["revenue"],
            "dimensions": ["order_date"],
            "filters": [],
            "time_range": "next quarter",
            "aggregation": "SUM",
            "target_column": "revenue",
            "table": "sales_fact",
        }
        mock_extract.return_value = extracted
        mock_validate.return_value = extracted
        mock_route.return_value = {
            "sql_query": "SELECT order_date, SUM(revenue) AS sum_revenue FROM etl.sales_fact GROUP BY order_date;",
            "next_step": "forecasting",
            "normalized_intent": {"table": "sales_fact"},
            "execution_result": {"rows": []},
            "downstream_result": {"status": "pending_integration"},
        }

        result = intent_extraction_task.fn(query="Forecast revenue for next quarter", schema=TEST_SCHEMA)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["intent_type"], "predictive")
        self.assertEqual(result["next_step"], "forecasting")
        self.assertEqual(result["error_type"], "none")

    @patch("intent_extraction.intent_extraction_task.route_intent")
    @patch("intent_extraction.intent_extraction_task.validate_structured_intent")
    @patch("intent_extraction.intent_extraction_task.extract_structured_intent")
    def test_model_error_retries_once_then_succeeds(
        self,
        mock_extract,
        mock_validate,
        mock_route,
    ):
        extracted = {
            "intent_type": "analytical",
            "metrics": ["revenue"],
            "dimensions": ["region"],
            "filters": [],
            "time_range": "last month",
            "aggregation": "SUM",
            "target_column": "revenue",
            "table": "sales_fact",
        }
        mock_extract.side_effect = [
            IntentExtractionModelOutputError("Invalid JSON"),
            extracted,
        ]
        mock_validate.return_value = extracted
        mock_route.return_value = {
            "sql_query": "SELECT 1;",
            "next_step": "metabase",
            "normalized_intent": {"table": "sales_fact"},
            "execution_result": {"rows": []},
            "downstream_result": {"status": "pending_integration"},
        }

        result = intent_extraction_task.fn(query="Show revenue", schema=TEST_SCHEMA)

        self.assertEqual(result["status"], "success")
        self.assertEqual(mock_extract.call_count, 2)

    @patch("intent_extraction.intent_extraction_task.validate_structured_intent")
    @patch("intent_extraction.intent_extraction_task.extract_structured_intent")
    def test_schema_mismatch_stops_without_retry(
        self,
        mock_extract,
        mock_validate,
    ):
        mock_extract.return_value = {
            "intent_type": "analytical",
            "metrics": ["invalid_metric"],
            "dimensions": [],
            "filters": [],
            "time_range": "all time",
            "aggregation": "SUM",
            "target_column": "invalid_metric",
            "table": "sales_fact",
        }
        mock_validate.side_effect = IntentExtractionSchemaMismatchError("Column does not exist")

        result = intent_extraction_task.fn(query="show invalid metric", schema=TEST_SCHEMA)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_type"], "schema_mismatch")
        self.assertEqual(result["action_taken"], "stop")


class SemanticExtractionCompletenessTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("CLICKHOUSE_DATABASE", "etl")
        self._validate_patcher = patch("intent_extraction.routing.validate_sql", lambda _sql: None)
        self._validate_patcher.start()
        self.config = IntentExtractionConfig(
            llm_provider="openrouter",
            ollama_url="http://localhost:11434/api/generate",
            ollama_model="gemma3:1b",
            request_timeout_seconds=20.0,
            max_retries=0,
            clickhouse_executor_path="",
            metabase_handler_path="",
            forecasting_handler_path="",
        )
        self.logger = logging.getLogger(__name__)

    def tearDown(self) -> None:
        if hasattr(self, "_validate_patcher"):
            self._validate_patcher.stop()

    def _extract_with_mocked_llm(self, *, query: str, payload: dict) -> dict:
        with patch(
            "intent_extraction.llm_extractor._call_openrouter",
            return_value=json.dumps(payload),
        ):
            return extract_structured_intent(
                query=query,
                schema=TEST_SCHEMA,
                config=self.config,
                logger=self.logger,
                log_event=lambda *args, **kwargs: None,
            )

    def test_ranking_and_implicit_limit_are_extracted(self):
        intent = self._extract_with_mocked_llm(
            query="Which region has the highest revenue?",
            payload={
                "intent_type": "analytical",
                "table": "sales_fact",
                "metrics": ["revenue"],
                "metric_specs": [{"column": "revenue", "aggregation": "SUM"}],
                "dimensions": ["region"],
                "filters": [],
                "aggregation": "SUM",
                "target_column": "revenue",
            },
        )
        validated = validate_structured_intent(intent=intent, schema=TEST_SCHEMA)
        self.assertEqual(validated["order_by"][0]["direction"], "DESC")
        self.assertEqual(validated["limit"], 1)

    def test_limit_detection_top_n(self):
        intent = self._extract_with_mocked_llm(
            query="Top 3 regions by revenue",
            payload={
                "intent_type": "analytical",
                "table": "sales_fact",
                "metrics": ["revenue"],
                "metric_specs": [{"column": "revenue", "aggregation": "SUM"}],
                "dimensions": ["region"],
                "filters": [],
            },
        )
        validated = validate_structured_intent(intent=intent, schema=TEST_SCHEMA)
        self.assertEqual(validated["limit"], 3)
        self.assertEqual(validated["order_by"][0]["direction"], "DESC")

    def test_comparison_filters_are_extracted(self):
        intent = self._extract_with_mocked_llm(
            query="Show revenue by region where profit > 100 and orders <= 10",
            payload={
                "intent_type": "analytical",
                "table": "sales_fact",
                "metrics": ["revenue"],
                "metric_specs": [{"column": "revenue", "aggregation": "SUM"}],
                "dimensions": ["region"],
                "filters": [],
            },
        )
        validated = validate_structured_intent(intent=intent, schema=TEST_SCHEMA)
        operators = {(f["column"], f["operator"]) for f in validated["filters"]}
        self.assertIn(("profit", ">"), operators)
        self.assertIn(("orders", "<="), operators)

    def test_multi_metric_detection_keeps_all_requested_outputs(self):
        intent = self._extract_with_mocked_llm(
            query="Show revenue and profit by region",
            payload={
                "intent_type": "analytical",
                "table": "sales_fact",
                "metrics": ["revenue"],
                "metric_specs": [{"column": "revenue", "aggregation": "SUM"}],
                "dimensions": ["region"],
                "filters": [],
            },
        )
        validated = validate_structured_intent(intent=intent, schema=TEST_SCHEMA)
        self.assertIn("revenue", validated["metrics"])
        self.assertIn("profit", validated["metrics"])

    def test_noisy_combined_query_is_still_complete(self):
        intent = self._extract_with_mocked_llm(
            query="uhh pls show me the top 2 regions with the worst profit but revenue above 200, thx",
            payload={
                "intent_type": "analytical",
                "table": "sales_fact",
                "metrics": ["profit"],
                "metric_specs": [{"column": "profit", "aggregation": "SUM"}],
                "dimensions": ["region"],
                "filters": [],
            },
        )
        validated = validate_structured_intent(intent=intent, schema=TEST_SCHEMA)
        self.assertEqual(validated["limit"], 2)
        self.assertEqual(validated["order_by"][0]["direction"], "ASC")
        self.assertTrue(any(f["column"] == "revenue" and f["operator"] == ">" for f in validated["filters"]))
        self.assertTrue(validated["operations"])
        self.assertTrue(validated["intent"])

    def test_relationship_query_uses_non_aggregated_metric_pairs(self):
        intent = self._extract_with_mocked_llm(
            query="What is the relationship between revenue and profit?",
            payload={
                "intent_type": "analytical",
                "table": "sales_fact",
                "metrics": ["revenue", "profit"],
                "metric_specs": [
                    {"column": "revenue", "aggregation": "SUM"},
                    {"column": "profit", "aggregation": "SUM"},
                ],
                "dimensions": [],
                "filters": [],
                "aggregation": "SUM",
                "target_column": "revenue",
            },
        )
        validated = validate_structured_intent(intent=intent, schema=TEST_SCHEMA)
        self.assertEqual(validated["intent"], "comparison")
        self.assertEqual(validated["aggregation"], "")
        self.assertIn("comparison", validated["operations"])
        self.assertNotIn("aggregation", validated["operations"])
        self.assertEqual(validated["metrics"], ["revenue", "profit"])
        for spec in validated["metric_specs"]:
            self.assertIsNone(spec["aggregation"])

    def test_relationship_query_sql_does_not_force_sum(self):
        intent = self._extract_with_mocked_llm(
            query="What is the relationship between revenue and profit?",
            payload={
                "intent_type": "analytical",
                "table": "sales_fact",
                "metrics": ["revenue", "profit"],
                "metric_specs": [
                    {"column": "revenue", "aggregation": "SUM"},
                    {"column": "profit", "aggregation": "SUM"},
                ],
                "dimensions": [],
                "filters": [],
                "aggregation": "SUM",
                "target_column": "revenue",
            },
        )
        validated = validate_structured_intent(intent=intent, schema=TEST_SCHEMA)
        _, sql = build_sql_from_intent(
            query="What is the relationship between revenue and profit?",
            intent=validated,
            schema=TEST_SCHEMA,
            workspace_clickhouse_db="etl",
        )
        self.assertNotIn("SUM(", sql.upper())

    def test_relationship_wording_with_over_time_keeps_time_series_shape(self):
        intent = self._extract_with_mocked_llm(
            query="Show relationship between revenue and order_date over time",
            payload={
                "intent_type": "analytical",
                "table": "sales_fact",
                "metrics": ["revenue", "profit"],
                "metric_specs": [
                    {"column": "revenue", "aggregation": "SUM"},
                    {"column": "profit", "aggregation": "SUM"},
                ],
                "dimensions": [],
                "filters": [],
                "aggregation": "SUM",
                "target_column": "revenue",
            },
        )
        validated = validate_structured_intent(intent=intent, schema=TEST_SCHEMA)
        _, sql = build_sql_from_intent(
            query="Show relationship between revenue and order_date over time",
            intent=validated,
            schema=TEST_SCHEMA,
            workspace_clickhouse_db="etl",
        )
        self.assertIn("AS date", sql)
        self.assertIn("ORDER BY date ASC", sql)
        self.assertIn("order_date", sql)

    def test_percentage_share_query_populates_chart_contract(self):
        intent = self._extract_with_mocked_llm(
            query="Show the percentage share of revenue by month",
            payload={
                "intent_type": "analytical",
                "table": "sales_fact",
                "metrics": ["revenue"],
                "metric_specs": [{"column": "revenue", "aggregation": "SUM"}],
                "dimensions": ["order_date"],
                "filters": [],
                "aggregation": "SUM",
                "target_column": "revenue",
                "operations": ["projection", "aggregation", "grouping"],
            },
        )
        validated = validate_structured_intent(intent=intent, schema=TEST_SCHEMA)
        self.assertEqual(validated.get("metric_type"), "percentage")
        self.assertEqual(validated.get("selected_chart_type"), "pie")
        self.assertEqual(validated.get("chart_type"), "pie")
        self.assertEqual((validated.get("chart") or {}).get("type"), "pie")
        self.assertEqual((validated.get("chart") or {}).get("metric_type"), "percentage")


class BulkQuestionCoverageTests(unittest.TestCase):
    def test_percentage_distribution_detection_on_50_questions(self):
        questions = [
            f"Show percentage share of revenue by region #{idx}" for idx in range(1, 21)
        ] + [
            f"Show sales distribution by product #{idx}" for idx in range(1, 21)
        ] + [
            f"What is the share of orders by city #{idx}" for idx in range(1, 11)
        ]
        self.assertEqual(len(questions), 50)

        for question in questions:
            intent, reason = _apply_chart_intent_fallback(
                query=question,
                intent={"intent_type": "analytical", "chart": {}},
            )
            self.assertEqual(intent.get("metric_type"), "percentage")
            expected_chart = "histogram" if "distribution" in question.lower() else "pie"
            self.assertEqual(intent.get("selected_chart_type"), expected_chart)
            self.assertEqual(intent.get("chart_type"), expected_chart)
            self.assertEqual((intent.get("chart") or {}).get("type"), expected_chart)
            self.assertTrue(reason)

if __name__ == "__main__":
    unittest.main()

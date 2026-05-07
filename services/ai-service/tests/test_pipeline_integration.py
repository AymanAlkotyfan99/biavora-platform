import os
import sys
import types
import importlib.util
import unittest
from unittest.mock import patch


if "dagster" not in sys.modules:
    dagster_stub = types.ModuleType("dagster")

    class _RetryPolicy:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _AssetExecutionContext:
        def __init__(self):
            self.log = type(
                "L",
                (),
                {
                    "info": lambda *a, **k: None,
                    "warning": lambda *a, **k: None,
                    "error": lambda *a, **k: None,
                },
            )()

    def _asset(*args, **kwargs):
        def decorator(fn):
            return fn

        return decorator

    def _failure_hook(fn):
        return fn

    dagster_stub.RetryPolicy = _RetryPolicy
    dagster_stub.AssetExecutionContext = _AssetExecutionContext
    dagster_stub.HookContext = object
    dagster_stub.Config = object
    dagster_stub.asset = _asset
    dagster_stub.failure_hook = _failure_hook
    sys.modules["dagster"] = dagster_stub

if "clickhouse_connect" not in sys.modules:
    clickhouse_stub = types.ModuleType("clickhouse_connect")

    def _get_client(*args, **kwargs):
        raise RuntimeError("clickhouse client is not available in unit tests")

    clickhouse_stub.get_client = _get_client
    sys.modules["clickhouse_connect"] = clickhouse_stub

sys.path.insert(0, os.path.abspath("services/ai-service"))

_EXECUTION_PATH = os.path.abspath("services/ai-service/dagster_pipeline/assets/execution.py")
_execution_spec = importlib.util.spec_from_file_location("dagster_pipeline_assets_execution_test", _EXECUTION_PATH)
assert _execution_spec and _execution_spec.loader
_execution_module = importlib.util.module_from_spec(_execution_spec)
_execution_spec.loader.exec_module(_execution_module)

query_execution_asset = _execution_module.query_execution_asset
visualization_asset = _execution_module.visualization_asset
forecasting_asset = _execution_module.forecasting_asset


class _FakeLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class _FakeContext:
    def __init__(self):
        self.log = _FakeLogger()


class PipelineIntegrationTests(unittest.TestCase):
    @patch.object(_execution_module, "review_and_correct_sql")
    @patch.object(_execution_module, "build_sql_from_intent")
    def test_query_execution_asset_returns_sql_ready_without_clickhouse_execution(
        self,
        mock_build_sql,
        mock_review,
    ):
        normalized_intent = {
            "intent": "time_series",
            "operations": ["projection", "aggregation", "grouping", "time_grouping"],
            "intent_type": "analytical",
            "table": "etl.sales",
            "metrics": [{"column": "total_sales", "aggregation": "SUM", "alias": "total_sales"}],
            "dimensions": ["ds"],
            "filters": [],
            "aggregation": "SUM",
            "ranking": {"direction": None, "requested": False, "source": "validation"},
            "order_by": [{"column": "ds", "direction": "ASC"}],
            "limit": 30,
            "ambiguities": [],
        }
        sql = (
            "SELECT toDate(ds) AS ds, SUM(total_sales) AS total_sales "
            "FROM etl.sales GROUP BY ds ORDER BY ds ASC LIMIT 30"
        )
        mock_build_sql.return_value = (normalized_intent, sql)
        mock_review.return_value = {
            "status": "approved",
            "reviewed_sql": sql,
            "notes": ["approved"],
            "reason_category": "alignment",
        }

        with patch("shared.query_service_auth.require_query_service_bearer_token", return_value="Bearer " + ("x" * 40)):
            result = query_execution_asset(
                context=_FakeContext(),
                routing_asset={
                    "status": "success",
                    "next_step": "metabase",
                    "intent_type": "analytical",
                    "query": "show total sales by day",
                    "schema": {
                        "etl.sales": [
                            {"name": "ds", "type": "Date"},
                            {"name": "total_sales", "type": "Float64"},
                        ]
                    },
                    "validated_intent": normalized_intent,
                    "extracted_intent": {},
                    "debug_metadata": {
                        "bound_table": "sales",
                        "dataset_scope": {"table_name": "sales"},
                    },
                },
            )

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("asset_role"), "sql_ready_asset")
        self.assertEqual(result.get("next_step"), "metabase")
        self.assertIsNone(result.get("execution_result"))
        self.assertEqual((result.get("sql_lifecycle") or {}).get("executed"), "skipped")

    def test_query_execution_asset_rejects_when_upstream_rejected(self):
        result = query_execution_asset(
            context=_FakeContext(),
            routing_asset={"status": "rejected", "message": "Non-data question"},
        )
        self.assertEqual(result.get("status"), "skipped")
        self.assertEqual(result.get("next_step"), "stop")
        self.assertEqual(result.get("sql_query"), "")
        self.assertEqual(result.get("execution_result"), None)

    def test_visualization_asset_finalizes_chart_contract(self):
        result = visualization_asset(
            context=_FakeContext(),
            query_execution_asset={
                "status": "success",
                "next_step": "metabase",
                "query": "show sales over time",
                "normalized_intent": {
                    "intent_type": "analytical",
                    "metrics": [{"column": "total_sales", "aggregation": "SUM", "alias": "total_sales"}],
                    "dimensions": ["ds"],
                },
                "chart_contract": {
                    "chart_type": "line",
                    "selected_chart_type": "line",
                    "explicit_chart_lock": True,
                    "chart_reason": "time_series_single_metric",
                    "chart_confidence": 0.88,
                },
            },
        )
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("next_step"), "metabase")
        self.assertEqual(result.get("visualization_status"), "finalized")
        self.assertEqual(result.get("reason_chart_not_generated"), "")
        self.assertEqual(result.get("selected_chart_type"), "line")
        self.assertTrue(isinstance(result.get("chart_contract"), dict))
        self.assertTrue(bool((result.get("chart_contract") or {}).get("visualization_settings")))

    @patch.object(_execution_module, "review_and_correct_sql")
    @patch.object(_execution_module, "build_sql_from_intent")
    def test_distribution_query_generates_histogram_contract(
        self,
        mock_build_sql,
        mock_review,
    ):
        normalized_intent = {
            "intent": "distribution",
            "operations": ["projection", "distribution"],
            "intent_type": "analytical",
            "table": "etl.sales_3months_realistic_csv",
            "metrics": [{"column": "total_sales", "aggregation": None, "alias": "total_sales"}],
            "dimensions": [],
            "filters": [],
            "aggregation": None,
            "ranking": {"direction": None, "requested": False, "source": "validation"},
            "order_by": [],
            "limit": None,
            "ambiguities": [],
            "is_distribution": True,
            "is_time_series": False,
            "is_percentage": False,
            "selected_chart_type": "histogram",
            "chart_type": "histogram",
        }
        sql = (
            "WITH stats AS (SELECT min(total_sales) AS min_value, max(total_sales) AS max_value, count(*) AS row_count "
            "FROM etl.sales_3months_realistic_csv WHERE total_sales IS NOT NULL) "
            "SELECT floor(t.total_sales / p.bin_size) * p.bin_size AS bucket, count(*) AS frequency "
            "FROM etl.sales_3months_realistic_csv AS t CROSS JOIN stats AS p "
            "WHERE t.total_sales IS NOT NULL GROUP BY bucket ORDER BY bucket"
        )
        mock_build_sql.return_value = (normalized_intent, sql)
        mock_review.return_value = {
            "status": "approved",
            "reviewed_sql": sql,
            "notes": ["approved"],
            "reason_category": "alignment",
        }
        with patch("shared.query_service_auth.require_query_service_bearer_token", return_value="Bearer " + ("x" * 40)):
            result = query_execution_asset(
                context=_FakeContext(),
                routing_asset={
                    "status": "success",
                    "next_step": "metabase",
                    "intent_type": "analytical",
                    "query": "What is the distribution of total sales?",
                    "schema": {
                        "etl.sales_3months_realistic_csv": [
                            {"name": "ds", "type": "Date"},
                            {"name": "total_sales", "type": "Float64"},
                        ]
                    },
                    "validated_intent": normalized_intent,
                    "extracted_intent": {},
                    "debug_metadata": {
                        "bound_table": "sales_3months_realistic_csv",
                        "dataset_scope": {"table_name": "sales_3months_realistic_csv"},
                    },
                },
            )
        self.assertEqual(result.get("status"), "success")
        self.assertIn("GROUP BY bucket", str(result.get("sql_query", "")))
        chart_contract = result.get("chart_contract") or {}
        self.assertEqual(chart_contract.get("chart_type"), "histogram")

    def test_forecasting_asset_delegates_to_voice_service(self):
        result = forecasting_asset(
            context=_FakeContext(),
            query_execution_asset={
                "status": "success",
                "next_step": "forecasting",
            },
        )
        self.assertEqual(result.get("status"), "delegated")
        self.assertEqual(result.get("next_step"), "forecasting")
        self.assertEqual(result.get("error_type"), "forecasting_delegated_to_voice_service")
        self.assertEqual(result.get("downstream_result"), None)


if __name__ == "__main__":
    unittest.main()

import unittest

from shared.chart_recommender import recommend_chart
from shared.input_classifier import classify_input
from shared.query_planner import normalize_analytical_intent
from shared.sql_compiler import compile_sql


TEST_SCHEMA = {
    "sales_fact": [
        {"name": "order_date", "type": "Date"},
        {"name": "customers", "type": "UInt32"},
        {"name": "orders", "type": "UInt32"},
        {"name": "total_sales", "type": "Float64"},
        {"name": "revenue", "type": "Float64"},
    ]
}


class BIHardeningTests(unittest.TestCase):
    def test_correlation_impact_intent_sql_chart(self):
        question = "How do customers impact total sales?"
        intent = normalize_analytical_intent(question=question, raw_intent={"table": "sales_fact"}, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        chart = recommend_chart(intent)

        self.assertEqual(intent["intent"], "correlation")
        self.assertIn("customers", sql)
        self.assertIn("total_sales", sql)
        self.assertNotIn("SUM(", sql.upper())
        self.assertEqual(chart["type"], "line_multi")

    def test_distribution_intent_sql_chart(self):
        question = "How are orders distributed?"
        intent = normalize_analytical_intent(question=question, raw_intent={"table": "sales_fact"}, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        chart = recommend_chart(intent)

        self.assertEqual(intent["intent"], "distribution")
        self.assertIn("SELECT orders", sql)
        self.assertNotIn("SUM(", sql.upper())
        self.assertEqual(chart["type"], "bar_grouped")

    def test_time_series_intent_sql_chart(self):
        question = "Show total sales by month"
        intent = normalize_analytical_intent(question=question, raw_intent={"table": "sales_fact"}, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        chart = recommend_chart(intent)

        self.assertEqual(intent["intent"], "time_series")
        self.assertIn("GROUP BY period", sql)
        self.assertEqual(chart["type"], "line")

    def test_daily_trend_preserves_daily_grain_metric_without_sum(self):
        question = "What is the trend of total sales over time?"
        intent = normalize_analytical_intent(question=question, raw_intent={"table": "sales_fact"}, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        chart = recommend_chart(intent)

        self.assertEqual(intent["intent"], "time_series")
        self.assertTrue(intent["source_grain_matches_requested"])
        self.assertFalse(intent["time_rollup_required"])
        self.assertIn("toDate(order_date) AS period", sql)
        self.assertIn("total_sales", sql)
        self.assertNotIn("SUM(", sql.upper())
        self.assertNotIn("GROUP BY", sql.upper())
        self.assertEqual(chart["type"], "line")

    def test_weekly_total_rollup_still_aggregates(self):
        question = "What are the total sales per week?"
        intent = normalize_analytical_intent(question=question, raw_intent={"table": "sales_fact"}, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        chart = recommend_chart(intent)

        self.assertEqual(intent["time_granularity"], "week")
        self.assertFalse(intent["source_grain_matches_requested"])
        self.assertTrue(intent["time_rollup_required"])
        self.assertIn("SUM(total_sales) AS sum_total_sales", sql)
        self.assertIn("GROUP BY period", sql)
        self.assertEqual(chart["type"], "line")

    def test_compare_two_metrics_per_week_remains_time_series(self):
        question = "Compare total sales and orders per week"
        intent = normalize_analytical_intent(
            question=question,
            raw_intent={"table": "sales_fact"},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        chart = recommend_chart(intent)

        self.assertTrue(intent.get("time_grouping_detected"))
        self.assertIn("time_grouping", intent.get("operations", []))
        self.assertIn("GROUP BY period", sql)
        self.assertIn("SUM(total_sales)", sql)
        self.assertIn("SUM(orders)", sql)
        self.assertEqual(chart["type"], "line_multi")

    def test_distribution_across_weeks_keeps_time_grouping(self):
        question = "How are orders distributed across weeks?"
        intent = normalize_analytical_intent(
            question=question,
            raw_intent={"table": "sales_fact"},
            schema=TEST_SCHEMA,
        )
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        chart = recommend_chart(intent)

        self.assertTrue(intent.get("time_grouping_detected"))
        self.assertEqual(intent.get("time_granularity"), "week")
        self.assertIn("time_grouping", intent.get("operations", []))
        self.assertIn("toStartOfWeek(order_date) AS period", sql)
        self.assertIn("orders", sql)
        self.assertEqual(chart["type"], "line")

    def test_average_per_day_on_daily_grain_uses_line_without_sum(self):
        question = "What is the average number of orders per day?"
        intent = normalize_analytical_intent(question=question, raw_intent={"table": "sales_fact"}, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        chart = recommend_chart(intent)

        self.assertTrue(intent["source_grain_matches_requested"])
        self.assertIn("orders", sql)
        self.assertNotIn("SUM(", sql.upper())
        self.assertEqual(chart["type"], "line")

    def test_kpi_derived_metric_intent_sql_chart(self):
        question = "What is average order value?"
        intent = normalize_analytical_intent(question=question, raw_intent={"table": "sales_fact"}, schema=TEST_SCHEMA)
        sql = compile_sql(intent, schema=TEST_SCHEMA)
        chart = recommend_chart(intent)

        self.assertIn("formula", intent["metrics"][0])
        self.assertIn("NULLIF", sql.upper())
        self.assertEqual(chart["type"], "card")

    def test_invalid_input_safety_intent_sql_chart(self):
        classification = classify_input(raw_text="...", cleaned_text="...")
        intent = {}
        sql = ""
        chart_type = "none"

        self.assertEqual(classification["classification"], "invalid_input")
        self.assertEqual(classification["route"], "stop")
        self.assertEqual(intent, {})
        self.assertEqual(sql, "")
        self.assertEqual(chart_type, "none")


if __name__ == "__main__":
    unittest.main()

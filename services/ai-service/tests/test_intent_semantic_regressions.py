import os
import sys
from unittest.mock import patch

import pytest

os.environ.setdefault("CLICKHOUSE_DATABASE", "etl")


@pytest.fixture(autouse=True)
def _skip_remote_sql_validate() -> None:
    with patch("intent_extraction.routing.validate_sql", lambda _sql: None):
        yield

SERVICE_ROOT = os.path.abspath("services/ai-service")
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from intent_extraction.routing import build_sql_from_intent  # noqa: E402
from intent_extraction.validation import validate_structured_intent  # noqa: E402
from shared.chart_contract import build_chart_contract_from_intent  # noqa: E402
from shared.semantic_contract_validator import recover_intent_from_question, validate_semantic_contract  # noqa: E402


SCHEMA = {
    "etl.sales_3months_realistic_csv": [
        {"name": "ds", "type": "String"},
        {"name": "total_sales", "type": "Float64"},
        {"name": "customers", "type": "Int64"},
        {"name": "orders", "type": "Int64"},
        {"name": "category", "type": "String"},
    ]
}


def _metric_columns(intent: dict) -> list[str]:
    metrics = intent.get("metrics", []) if isinstance(intent.get("metrics"), list) else []
    output: list[str] = []
    for metric in metrics:
        if isinstance(metric, dict):
            col = str(metric.get("column") or "").strip()
        else:
            col = str(metric or "").strip()
        if col and col != "*" and col not in output:
            output.append(col)
    return output


def _run_pipeline(
    question: str,
    *,
    selected_columns: list[str],
    original_user_question: str | None = None,
) -> tuple[dict, str, dict]:
    oq = (original_user_question or question).strip()
    recovered = recover_intent_from_question(
        question=question,
        schema=SCHEMA,
        raw_intent={"table": "etl.sales_3months_realistic_csv"},
    )
    validated = validate_structured_intent(intent=recovered, schema=SCHEMA)
    repaired = validate_semantic_contract(
        question=question,
        intent=validated,
        schema=SCHEMA,
        preprocess_hints={
            "selected_columns": selected_columns,
            "selected_table": "etl.sales_3months_realistic_csv",
            "original_user_question": oq,
            "original_query_for_intent": oq,
        },
    )
    validated_repaired = validate_structured_intent(intent=repaired, schema=SCHEMA)
    oq_merge = (original_user_question or question).strip()
    normalized_intent, sql = build_sql_from_intent(
        query=question,
        intent=validated_repaired,
        schema=SCHEMA,
        workspace_clickhouse_db=os.environ.get("CLICKHOUSE_DATABASE") or "etl",
        preprocess_hints={
            "original_user_question": oq_merge,
            "original_query_for_intent": oq_merge,
        },
    )
    chart_contract = build_chart_contract_from_intent(normalized_intent, user_text=question)
    return normalized_intent, sql, chart_contract


def test_compare_sales_and_customers_over_time_generates_line_multi_grouped_sql():
    q = "Compare total sales and customers over time"
    intent, sql, chart = _run_pipeline(
        q,
        selected_columns=["total_sales", "customers", "ds"],
    )
    metrics = _metric_columns(intent)

    assert intent.get("intent_type") == "analytical"
    assert "total_sales" in metrics
    assert "customers" in metrics
    assert intent.get("group_by_time") is True
    assert str(intent.get("time_column") or "") == "ds"
    assert str(intent.get("time_granularity") or "")
    assert "GROUP BY date" in sql or "GROUP BY `date`" in sql
    assert "ORDER BY date" in sql or "ORDER BY `date`" in sql
    assert "toDate(" in sql and "ds" in sql
    assert "SUM(total_sales)" in sql
    assert "SUM(customers)" in sql
    assert chart["chart_type"] == "line_multi"
    assert chart["x_axis"] == "date"
    yset = set(chart["y_axis"])
    assert yset >= {"sum_total_sales", "sum_customers"}
    assert chart.get("type") == "line_multi"
    assert chart.get("chart_lock") is True
    assert chart.get("explicit_chart_lock") is True
    assert chart["chart_type"] != "card"


def test_compare_sales_stripped_query_uses_original_question_for_time():
    """Simulates preprocessing that drops 'over time' from the working query."""
    stripped = "Compare total sales and customers"
    original = "Compare total sales and customers over time"
    intent, sql, chart = _run_pipeline(
        stripped,
        selected_columns=["total_sales", "customers", "ds"],
        original_user_question=original,
    )
    assert intent.get("group_by_time") is True
    assert "toDate(" in sql and "ds" in sql
    assert "SUM(total_sales)" in sql
    assert chart["chart_type"] == "line_multi"


def test_percentage_share_by_month_as_pie_stays_grouped_not_scalar():
    intent, sql, chart = _run_pipeline(
        "Show the percentage share of total_sales by month as a pie chart",
        selected_columns=["total_sales", "ds"],
    )

    assert "total_sales" in _metric_columns(intent)
    assert intent.get("time_granularity") == "month"
    assert "GROUP BY" in sql
    assert "OVER ()" in sql
    assert "/ NULLIF(SUM(" in sql
    assert chart["chart_type"] in {"pie", "line_multi"}
    if chart["chart_type"] == "pie":
        assert str(chart.get("label_column") or "").strip()
        assert str(chart.get("value_column") or "").strip()
    assert chart["chart_type"] != "card"


def test_relationship_between_sales_and_orders_keeps_scatter_axes():
    intent, sql, chart = _run_pipeline(
        "What is the relationship between total sales and number of orders?",
        selected_columns=["total_sales", "orders"],
    )

    metrics = _metric_columns(intent)
    assert "total_sales" in metrics
    assert "orders" in metrics
    assert "relationship" in {str(op).lower() for op in intent.get("operations", [])} or "comparison" in {
        str(op).lower() for op in intent.get("operations", [])
    }
    assert "SELECT total_sales" in sql
    assert "orders" in sql
    assert "SUM(" not in sql.upper()
    assert chart["chart_type"] == "scatter"
    assert chart["x_axis"] == "total_sales"
    assert chart["y_axis"] == ["orders"]
    assert intent.get("chart_lock") is True
    assert intent.get("explicit_chart_lock") is True
    assert intent.get("final_chart_type") == "scatter"
    assert chart.get("type") == "scatter"
    assert chart.get("chart_lock") is True


def test_show_total_sales_over_time_is_line_with_sum():
    intent, sql, chart = _run_pipeline(
        "Show total sales over time",
        selected_columns=["total_sales", "ds"],
    )
    assert "total_sales" in _metric_columns(intent)
    assert intent.get("group_by_time") is True
    assert "SUM(total_sales)" in sql
    assert "GROUP BY date" in sql or "GROUP BY `date`" in sql
    assert chart["chart_type"] == "line"
    assert chart["x_axis"] == "date"


def test_compare_total_sales_and_customers_weekly_uses_week_bucket():
    intent, sql, chart = _run_pipeline(
        "Compare total sales and customers weekly",
        selected_columns=["total_sales", "customers", "ds"],
    )
    assert "toStartOfWeek(" in sql
    assert chart["chart_type"] == "line_multi"
    assert chart["x_axis"] == "date"


def test_show_total_sales_and_customers_without_time_is_not_line_multi():
    intent, sql, chart = _run_pipeline(
        "Show total sales and customers",
        selected_columns=["total_sales", "customers", "ds"],
    )
    assert intent.get("group_by_time") not in {True, 1}
    assert chart["chart_type"] != "line_multi"


def test_compare_total_sales_across_weeks_generates_line_week_grouping():
    intent, sql, chart = _run_pipeline(
        "Compare total sales across weeks",
        selected_columns=["total_sales", "ds"],
    )

    assert "total_sales" in _metric_columns(intent)
    assert intent.get("time_granularity") == "week"
    assert "toStartOfWeek(" in sql
    assert chart["chart_type"] == "line"
    assert chart["x_axis"] == "date"
    assert chart["y_axis"] == ["sum_total_sales"] or chart["y_axis"] == ["total_sales"]


def test_compare_total_sales_across_months_generates_line_month_grouping():
    intent, sql, chart = _run_pipeline(
        "Compare total sales across months",
        selected_columns=["total_sales", "ds"],
    )

    assert "total_sales" in _metric_columns(intent)
    assert intent.get("time_granularity") == "month"
    assert "toStartOfMonth(" in sql
    assert chart["chart_type"] == "line"
    assert chart["x_axis"] == "date"
    assert chart["y_axis"] == ["sum_total_sales"] or chart["y_axis"] == ["total_sales"]


def test_show_orders_by_month_is_grouped_and_not_card():
    intent, sql, chart = _run_pipeline(
        "Show orders by month",
        selected_columns=["orders", "ds"],
    )

    assert "orders" in _metric_columns(intent)
    assert intent.get("time_granularity") == "month"
    assert "GROUP BY" in sql
    assert chart["chart_type"] in {"line", "bar"}
    assert chart["chart_type"] != "card"


def test_distribution_of_customers_by_month_is_grouped_and_not_card():
    intent, sql, chart = _run_pipeline(
        "Show distribution of customers by month",
        selected_columns=["customers", "ds"],
    )

    assert "customers" in _metric_columns(intent)
    assert intent.get("time_granularity") == "month"
    assert "GROUP BY" in sql
    assert chart["chart_type"] != "card"


def test_total_sales_scalar_kpi_allows_card():
    intent, sql, chart = _run_pipeline(
        "Total sales",
        selected_columns=["total_sales"],
    )

    assert _metric_columns(intent) == ["total_sales"]
    assert "GROUP BY" not in sql
    assert chart["chart_type"] == "card"

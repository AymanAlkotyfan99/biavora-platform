import os
import sys


sys.path.insert(0, os.path.abspath("services/ai-service"))

from shared.chart_recommender import recommend_chart  # noqa: E402


def _result(columns, rows):
    return {"columns": columns, "rows": rows}


def test_recommender_time_single_metric_line():
    chart = recommend_chart(
        dataframe=_result(
            [{"name": "period", "type": "Date"}, {"name": "value", "type": "Float64"}],
            [{"period": "2026-01-01", "value": 10}],
        ),
        intent={"intent": "time_series", "metrics": [{"column": "value"}], "dimensions": ["period"]},
        metadata={},
    )
    assert chart["chart_type"] == "line"


def test_recommender_time_multi_metric_line_multi():
    chart = recommend_chart(
        dataframe=_result(
            [{"name": "period", "type": "Date"}, {"name": "sales", "type": "Float64"}, {"name": "orders", "type": "Float64"}],
            [{"period": "2026-01-01", "sales": 10, "orders": 2}],
        ),
        intent={"intent": "time_series", "metrics": [{"column": "sales"}, {"column": "orders"}], "dimensions": ["period"]},
        metadata={},
    )
    assert chart["chart_type"] == "line_multi"


def test_recommender_category_multi_metric_grouped_bar():
    chart = recommend_chart(
        dataframe=_result(
            [{"name": "region", "type": "String"}, {"name": "sales", "type": "Float64"}, {"name": "profit", "type": "Float64"}],
            [{"region": "north", "sales": 10, "profit": 4}],
        ),
        intent={"intent": "comparison", "metrics": [{"column": "sales"}, {"column": "profit"}], "dimensions": ["region"]},
        metadata={},
    )
    assert chart["chart_type"] == "bar_grouped"


def test_recommender_geo_map():
    chart = recommend_chart(
        dataframe=_result(
            [{"name": "country", "type": "String"}, {"name": "value", "type": "Float64"}],
            [{"country": "US", "value": 10}],
        ),
        intent={"intent": "comparison", "metrics": [{"column": "value"}], "dimensions": ["country"]},
        metadata={},
    )
    assert chart["chart_type"] == "map"


def test_recommender_empty_dataset_table():
    chart = recommend_chart(
        dataframe=_result([{"name": "x", "type": "String"}], []),
        intent={},
        metadata={},
    )
    assert chart["chart_type"] == "table"


def test_recommender_detects_line_and_bars_as_combo():
    chart = recommend_chart(
        dataframe=_result(
            [{"name": "period", "type": "Date"}, {"name": "total_sales", "type": "Float64"}, {"name": "orders", "type": "Float64"}],
            [{"period": "2026-01-01", "total_sales": 120, "orders": 8}],
        ),
        intent={"query": "Show total sales as a line and orders as bars over time"},
        metadata={},
    )
    assert chart["chart_type"] == "combo_line_bar"


def test_recommender_honors_explicit_stacked_intent():
    chart = recommend_chart(
        dataframe=_result(
            [{"name": "period", "type": "Date"}, {"name": "total_sales", "type": "Float64"}, {"name": "orders", "type": "Float64"}],
            [
                {"period": "2026-01-01", "total_sales": 100, "orders": 7},
                {"period": "2026-01-02", "total_sales": 120, "orders": 9},
            ],
        ),
        intent={"query": "Show total_sales and orders per day as a stacked chart"},
        metadata={},
    )
    assert chart["chart_type"] == "bar_stacked"

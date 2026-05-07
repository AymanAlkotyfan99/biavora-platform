import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

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
    service._request = MagicMock(return_value=_FakeResponse({"id": 123}))
    return service


def _payload(service):
    return service._request.call_args.kwargs["json"]


def test_valid_explicit_chart_is_preserved():
    service = _service()
    result = service.create_question(
        name="line",
        sql="SELECT day_key, value FROM t",
        visualization_settings={
            "chart_config": {
                "selected_chart_type": "line",
                "explicit_chart_lock": True,
                "x_axis": "day_key",
                "y_axis": ["value"],
            },
            "graph": {"type": "line", "dimensions": ["day_key"], "metrics": ["value"]},
            "result_rows": [{"day_key": "2026-01-01", "value": 10}],
            "dataset_columns": [{"name": "day_key"}, {"name": "value"}],
        },
    )
    assert result == 123
    payload = _payload(service)
    assert payload["display"] == "line"
    assert payload["visualization_settings"]["final_chart_type"] == "line"
    assert payload["visualization_settings"]["overwritten_by"] == ""


def test_percentage_pie_contract_is_preserved():
    service = _service()
    result = service.create_question(
        name="pie",
        sql="SELECT period, percentage_share FROM t",
        visualization_settings={
            "chart_config": {
                "selected_chart_type": "pie",
                "explicit_chart_lock": True,
                "chart_reason_code": "percentage_distribution",
                "x_axis": "period",
                "y_axis": ["percentage_share"],
            },
            "metric_type": "percentage",
            "result_rows": [{"period": "2026-01", "percentage_share": 0.4}],
            "dataset_columns": [{"name": "period"}, {"name": "percentage_share"}],
        },
    )
    assert result == 123
    payload = _payload(service)
    assert payload["display"] == "pie"
    assert payload["visualization_settings"]["final_chart_type"] == "pie"
    assert payload["visualization_settings"]["chart_decision_trace"]["overwritten"] is False


def test_time_series_line_contract_is_renderer_only():
    service = _service()
    result = service.create_question(
        name="line",
        sql="SELECT ds, metric FROM t",
        visualization_settings={
            "chart_config": {"selected_chart_type": "line", "explicit_chart_lock": True, "x_axis": "ds", "y_axis": ["metric"]},
            "graph": {"type": "line", "dimensions": ["ds"], "metrics": ["metric"]},
            "result_rows": [{"ds": "2026-01-01", "metric": 1}],
            "dataset_columns": [{"name": "ds"}, {"name": "metric"}],
        },
    )
    assert result == 123
    payload = _payload(service)
    assert payload["display"] == "line"
    assert payload["visualization_settings"]["final_chart_type"] == "line"


def test_multi_series_maps_to_metabase_line_and_preserves_metadata():
    service = _service()
    result = service.create_question(
        name="multi",
        sql="SELECT ds, m1, m2 FROM t",
        visualization_settings={
            "chart_config": {"selected_chart_type": "line_multi", "x_axis": "ds", "y_axis": ["m1", "m2"]},
            "graph": {"type": "line", "dimensions": ["ds"], "metrics": ["m1", "m2"]},
            "result_rows": [{"ds": "2026-01-01", "m1": 1, "m2": 2}],
            "dataset_columns": [{"name": "ds"}, {"name": "m1"}, {"name": "m2"}],
        },
    )
    assert result == 123
    payload = _payload(service)
    assert payload["display"] == "line"
    assert payload["visualization_settings"]["final_chart_type"] == "line_multi"


def test_multi_series_requires_explicit_metrics_and_dimensions():
    service = _service()
    result = service.create_question(
        name="multi-missing",
        sql="SELECT ds, m1, m2 FROM t",
        visualization_settings={
            "chart_config": {"selected_chart_type": "line_multi"},
            "graph": {"type": "line", "dimensions": ["ds"], "metrics": []},
            "result_rows": [{"ds": "2026-01-01", "m1": 1, "m2": 2}],
            "dataset_columns": [{"name": "ds"}, {"name": "m1"}, {"name": "m2"}],
        },
    )
    assert result is None
    assert "missing_required_axis_bindings:line_multi" in (service.last_error or "")


def test_invalid_explicit_pie_fails_without_axis_bindings():
    service = _service()
    result = service.create_question(
        name="invalid pie",
        sql="SELECT value FROM t",
        visualization_settings={
            "chart_config": {"selected_chart_type": "pie", "explicit_chart_lock": True},
            "result_rows": [{"value": 1}, {"value": 2}],
            "dataset_columns": [{"name": "value"}],
        },
    )
    assert result is None
    assert "missing_required_label_value_bindings:pie" in (service.last_error or "")


def test_missing_contract_errors_instead_of_inferring_table():
    service = _service()
    result = service.create_question(
        name="no contract",
        sql="SELECT a FROM t",
        visualization_settings={"result_rows": [{"a": "x"}], "dataset_columns": [{"name": "a"}]},
    )
    assert result is None
    assert "missing_upstream_chart_contract" in (service.last_error or "")


def test_scatter_chart_binds_graph_axes_explicitly():
    service = _service()
    result = service.create_question(
        name="scatter",
        sql="SELECT total_sales, orders FROM t",
        visualization_settings={
            "chart_config": {
                "selected_chart_type": "scatter",
                "x_axis": "total_sales",
                "y_axis": ["orders"],
                "explicit_chart_lock": True,
            },
            "result_rows": [{"total_sales": 100.0, "orders": 10}],
            "dataset_columns": [
                {"name": "total_sales", "type": "Float64", "is_numeric": True},
                {"name": "orders", "type": "Int64", "is_numeric": True},
            ],
        },
    )
    assert result == 123
    payload = _payload(service)
    assert payload["display"] == "scatter"
    assert payload["visualization_settings"]["final_chart_type"] == "scatter"
    assert payload["visualization_settings"]["graph.dimensions"] == ["total_sales"]
    assert payload["visualization_settings"]["graph.metrics"] == ["orders"]


def test_scatter_without_axes_returns_prepare_error():
    service = _service()
    result = service.create_question(
        name="scatter-missing-axes",
        sql="SELECT city, orders FROM t",
        visualization_settings={
            "chart_config": {"selected_chart_type": "scatter", "explicit_chart_lock": True},
            "result_rows": [{"city": "A", "orders": 10}],
            "dataset_columns": [{"name": "city"}, {"name": "orders", "type": "Int64", "is_numeric": True}],
        },
    )
    assert result is None
    assert service.last_error == "missing_required_axis_bindings:scatter"


def test_metabase_payload_sql_is_sanitized_for_trailing_semicolons():
    service = _service()
    result = service.create_question(
        name="semicolon",
        sql=" SELECT total_sales, orders FROM etl.sales_3months_realistic_csv;;  ",
        visualization_settings={
            "chart_config": {"selected_chart_type": "scatter", "x_axis": "total_sales", "y_axis": ["orders"]},
            "result_rows": [{"total_sales": 100.0, "orders": 10}],
            "dataset_columns": [
                {"name": "total_sales", "type": "Float64", "is_numeric": True},
                {"name": "orders", "type": "Int64", "is_numeric": True},
            ],
        },
    )
    assert result == 123
    payload = _payload(service)
    assert payload["dataset_query"]["native"]["query"] == "SELECT total_sales, orders FROM etl.sales_3months_realistic_csv"


def test_metabase_payload_sql_strips_ch_settings_comment_prefix():
    service = _service()
    result = service.create_question(
        name="comment-prefix",
        sql="/* ch_settings: max_execution_time=60, max_result_rows=100000, readonly=2 */\nSELECT total_sales, orders FROM etl.sales_3months_realistic_csv;",
        visualization_settings={
            "chart_config": {
                "selected_chart_type": "scatter",
                "x_axis": "total_sales",
                "y_axis": ["orders"],
                "explicit_chart_lock": True,
            },
            "result_rows": [{"total_sales": 100.0, "orders": 10}],
            "dataset_columns": [
                {"name": "total_sales", "type": "Float64", "is_numeric": True},
                {"name": "orders", "type": "Int64", "is_numeric": True},
            ],
        },
    )
    assert result == 123
    payload = _payload(service)
    assert payload["dataset_query"]["native"]["query"] == "SELECT total_sales, orders FROM etl.sales_3months_realistic_csv"

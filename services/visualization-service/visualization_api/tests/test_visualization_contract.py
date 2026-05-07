import sys
from pathlib import Path

SERVICE_ROOT = str(Path(__file__).resolve().parents[2])
REPO_ROOT = str(Path(__file__).resolve().parents[4])
for p in (SERVICE_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from visualization_api.application.chart_contract import validate_chart_contract  # noqa: E402


def test_pie_contract_is_preserved_when_shape_supports_it():
    result = validate_chart_contract(
        rows=[{"month": "2026-04", "orders": 42}],
        columns=["month", "orders"],
        chart_contract={"chart_type": "pie", "x_axis": "month", "y_axis": ["orders"], "locked": True},
        requested_chart_type="pie",
    )

    assert result["requested_chart_type"] == "pie"
    assert result["final_chart_type"] == "pie"
    assert result["fallback_used"] is False


def test_renderer_never_downgrades_scatter_to_table():
    result = validate_chart_contract(
        rows=[{"city": "A", "total_sales": 10}],
        columns=["city", "total_sales"],
        chart_contract={"chart_type": "scatter", "x_axis": "city", "y_axis": ["total_sales"], "locked": True},
        requested_chart_type="scatter",
    )

    assert result["requested_chart_type"] == "scatter"
    assert result["final_chart_type"] == "scatter"
    assert result["fallback_used"] is False


def test_histogram_contract_requires_bound_x_axis():
    result = validate_chart_contract(
        rows=[{"total_sales": 10.0}, {"total_sales": 11.2}],
        columns=["total_sales"],
        chart_contract={"chart_type": "histogram", "x_axis": "total_sales", "y_axis": ["frequency"], "locked": True},
        requested_chart_type="histogram",
    )
    assert result["requested_chart_type"] == "histogram"
    assert result["final_chart_type"] == "histogram"
    assert result["fallback_used"] is False

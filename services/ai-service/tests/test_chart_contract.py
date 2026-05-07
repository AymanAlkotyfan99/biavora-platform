import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

MODULE_PATH = Path(__file__).resolve().parents[1] / "shared" / "chart_contract.py"
spec = importlib.util.spec_from_file_location("ai_chart_contract_under_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
build_chart_contract_from_intent = module.build_chart_contract_from_intent


def test_explicit_pie_contract():
    contract = build_chart_contract_from_intent(
        {"selected_chart_type": "pie", "dimensions": ["region"], "metrics": ["orders"]},
        user_text="show orders by region as pie chart",
    )
    assert contract["selected_chart_type"] == "pie"
    assert contract["explicit_chart_lock"] is True
    assert contract["chart_reason_code"] == "explicit_chart"


def test_forecast_forces_line_contract():
    contract = build_chart_contract_from_intent(
        {"selected_chart_type": "bar", "requires_forecast": True, "dimensions": ["ds"], "metrics": ["sales"]},
        final_route="forecasting",
    )
    assert contract["selected_chart_type"] == "line"
    assert contract["chart_reason_code"] == "forecast_line"


def test_histogram_contract_autofills_x_axis():
    contract = build_chart_contract_from_intent(
        {"selected_chart_type": "histogram", "metrics": ["total_sales"]},
        user_text="distribution of total sales",
    )
    assert contract["selected_chart_type"] == "histogram"
    assert contract["x_axis"] == "total_sales"


def test_pie_contract_autofills_label_and_value():
    contract = build_chart_contract_from_intent(
        {"selected_chart_type": "pie", "dimensions": ["month"], "metrics": ["total_sales"]},
        user_text="percentage share of total sales by month",
    )
    assert contract["label_column"] == "month"
    assert contract["value_column"] == "total_sales"
    assert contract["x_axis"] == "month"
    assert contract["y_axis"] == ["total_sales"]

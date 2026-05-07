import importlib.util
from pathlib import Path
import sys
import types

MODULE_PATH = Path(__file__).resolve().parents[1] / "intent_extraction" / "predictive_parser.py"
SERVICE_ROOT = str(Path(__file__).resolve().parents[1])
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)
shared_pkg = sys.modules.get("shared")
if shared_pkg is None:
    shared_pkg = types.ModuleType("shared")
    shared_pkg.__path__ = [str(Path(SERVICE_ROOT) / "shared")]
    sys.modules["shared"] = shared_pkg
spec = importlib.util.spec_from_file_location("predictive_parser_under_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
parse_predictive_intent = module.parse_predictive_intent


def test_predict_orders_next_week_detects_ds_and_orders():
    schema = {
        "any_table": [
            {"name": "ds", "type": "String", "sample": "2023-01-01"},
            {"name": "orders", "type": "Int64", "sample": 44},
            {"name": "total_sales", "type": "Float64", "sample": 1546.0},
        ]
    }
    intent = parse_predictive_intent(query="Predict the number of orders for the next week based on past data", schema=schema)
    assert intent["table"] == "any_table"
    assert intent["time_column"] == "ds"
    assert intent["metric"] == "orders"
    assert intent["forecast_horizon"] == 1
    assert intent["granularity"] == "week"
    assert intent["time_grain"] == "week"


def test_predict_total_sales_next_7_days_uses_date_like_string_column():
    schema = {
        "t": [
            {"name": "event_time", "type": "String", "sample": "2024-04-15"},
            {"name": "total_sales", "type": "Float64", "sample": 1200.5},
            {"name": "customers", "type": "Int64", "sample": 20},
        ]
    }
    intent = parse_predictive_intent(query="What will be the total sales for the next 7 days?", schema=schema)
    assert intent["time_column"] == "event_time"
    assert intent["metric"] == "total_sales"
    assert intent["forecast_horizon"] == 7

import importlib.util
import sys
from pathlib import Path

SERVICE_ROOT = str(Path(__file__).resolve().parents[2])
REPO_ROOT = str(Path(__file__).resolve().parents[4])
for p in (SERVICE_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from visualization_api.application.chart_contract import coerce_upstream_chart_contract_dict  # noqa: E402

SERVICE_PATH = Path(__file__).resolve().parents[1] / "services" / "metabase_service.py"
spec = importlib.util.spec_from_file_location("metabase_service_under_test", SERVICE_PATH)
metabase_service = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(metabase_service)
MetabaseService = metabase_service.MetabaseService


def test_coerce_type_alias_line_multi():
    raw = {
        "type": "line_multi",
        "x_axis": "ds",
        "y_axis": ["sum_total_sales", "sum_customers"],
        "chart_lock": True,
    }
    out = coerce_upstream_chart_contract_dict(raw)
    assert out["chart_type"] == "line_multi"
    assert out["x_axis"] == "ds"
    assert out["y_axis"] == ["sum_total_sales", "sum_customers"]


def test_coerce_metrics_and_time_column_compare_sales_scenario():
    raw = {
        "final_chart_type": "line_multi",
        "time_column": "ds",
        "metrics": ["total_sales", "customers"],
        "explicit_chart_lock": True,
    }
    out = coerce_upstream_chart_contract_dict(raw)
    assert out["chart_type"] == "line_multi"
    assert out["x_axis"] == "ds"
    assert out["y_axis"] == ["total_sales", "customers"]


def test_metabase_prepare_preserves_line_multi_metrics_when_locked():
    svc = MetabaseService()
    display, settings, err = svc._prepare_visualization_settings(
        {
            "display": "line",
            "chart_type": "line_multi",
            "selected_chart_type": "line_multi",
            "explicit_chart_lock": True,
            "graph.dimensions": ["ds"],
            "graph.metrics": ["total_sales", "customers"],
            "x_axis": "ds",
            "y_axis": ["total_sales", "customers"],
        }
    )
    assert err is None
    assert display == "line"
    assert settings.get("final_chart_type") == "line_multi"
    assert settings.get("graph.metrics") == ["total_sales", "customers"]

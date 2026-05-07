import unittest
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "services" / "metabase_service.py"
spec = importlib.util.spec_from_file_location("metabase_service_under_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
MetabaseService = module.MetabaseService


class MetabaseSettingsLineTests(unittest.TestCase):
    def test_line_payload_keeps_line_display_and_axes(self):
        service = MetabaseService()
        display, settings = service._prepare_visualization_settings(
            {
                "final_chart_type": "line",
                "x_axis": "period",
                "y_axis": ["sum_total_sales"],
                "time_columns": ["period"],
                "numeric_columns": ["sum_total_sales"],
                "row_count": 3,
            }
        )
        self.assertEqual(display, "line")
        self.assertEqual(settings.get("chart_type"), "line")


if __name__ == "__main__":
    unittest.main()

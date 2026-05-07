import unittest
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "chart_recovery.py"
spec = importlib.util.spec_from_file_location("chart_recovery_under_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
infer_chart_type_from_shape = module.infer_chart_type_from_shape


class ChartRecoveryTests(unittest.TestCase):
    def test_period_metric_recovers_line(self):
        chart, reason = infer_chart_type_from_shape(
            columns=["period", "sum_total_sales"],
            rows=[
                {"period": "2026-01-01", "sum_total_sales": 10},
                {"period": "2026-02-01", "sum_total_sales": 20},
            ],
            intent={},
        )
        self.assertEqual(chart, "line")
        self.assertEqual(reason, "time_metric_shape")


if __name__ == "__main__":
    unittest.main()

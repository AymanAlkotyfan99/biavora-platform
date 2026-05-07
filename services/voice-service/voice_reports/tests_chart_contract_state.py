import unittest
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "chart_state.py"
spec = importlib.util.spec_from_file_location("chart_state_under_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
merge_chart_config_with_fresh = module.merge_chart_config_with_fresh


class ChartContractStateTests(unittest.TestCase):
    def test_stored_cache_cannot_override_fresh_chart(self):
        stored = {"selected_chart_type": "table", "final_chart_type": "table", "explicit_chart_lock": False}
        fresh = {"selected_chart_type": "line", "final_chart_type": "line", "explicit_chart_lock": True}
        effective = merge_chart_config_with_fresh(stored, fresh)
        self.assertEqual(effective.get("final_chart_type"), "line")
        self.assertEqual(effective.get("effective_chart_type"), "line")
        self.assertEqual(effective.get("chart_config_source"), "fresh_execution")
        self.assertFalse(effective.get("stored_overrode_fresh"))


if __name__ == "__main__":
    unittest.main()

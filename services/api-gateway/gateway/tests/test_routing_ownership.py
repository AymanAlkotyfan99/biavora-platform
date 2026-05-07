import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "routing.py"
spec = importlib.util.spec_from_file_location("gateway_routing_under_test", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)
resolve_target = mod.resolve_target


def test_voice_reports_lifecycle_routes_to_voice_service():
    paths = [
        "/voice-reports/upload/",
        "/voice-reports/text-query/",
        "/voice-reports/1/execute/",
        "/voice-reports/1/sql/",
        "/voice-reports/reports/",
        "/voice-reports/1/",
        "/voice-reports/1/ai-trace/",
        "/voice-reports/dashboard/",
        "/voice-reports/dashboard/stats/",
    ]
    for path in paths:
        target = resolve_target(path)
        assert target is not None
        assert target.service == "voice-service"

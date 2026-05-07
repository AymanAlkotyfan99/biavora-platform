import importlib.util
import logging
import sys
from types import SimpleNamespace
from pathlib import Path

if "clickhouse_connect" not in sys.modules:
    sys.modules["clickhouse_connect"] = SimpleNamespace(get_client=lambda **_: None)


MODULE_PATH = Path(__file__).resolve().parents[1] / "services" / "clickhouse_executor.py"
spec = importlib.util.spec_from_file_location("query_clickhouse_executor_under_test", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


class _FakeClient:
    def query(self, _sql):
        raise RuntimeError("syntax error near token")


def test_sql_failure_logging_does_not_include_raw_sql(caplog):
    executor = mod.ClickHouseExecutor.__new__(mod.ClickHouseExecutor)
    executor.database = "etl"
    executor.client = _FakeClient()

    sql = "SELECT secret_col FROM etl.sales WHERE api_key='super-secret'"
    with caplog.at_level(logging.ERROR):
        result = executor.execute_query(sql)

    assert result["success"] is False
    combined_logs = " ".join(record.getMessage() for record in caplog.records)
    assert "super-secret" not in combined_logs
    assert "query_hash=" in combined_logs


def test_hash_sql_is_stable():
    sql = "SELECT 1"
    h1 = mod.hash_sql(sql)
    h2 = mod.hash_sql(sql)
    assert h1 == h2

import os
import sys
import types

SERVICE_ROOT = os.path.abspath("services/query-service")
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

if "clickhouse_connect" not in sys.modules:
    clickhouse_stub = types.ModuleType("clickhouse_connect")
    clickhouse_stub.get_client = lambda *args, **kwargs: None
    sys.modules["clickhouse_connect"] = clickhouse_stub

from query_api.application import query_execution  # noqa: E402
from query_api.utils.sql_normalization import normalize_sql_table_references_detailed  # noqa: E402


class _Executor:
    def __init__(self, result):
        self.result = result
        self.called = False

    def execute_query(self, sql):
        self.called = True
        return self.result


def test_unsafe_sql_is_rejected_before_executor(monkeypatch):
    executor = _Executor({"success": True, "rows": [], "columns": []})
    monkeypatch.setattr(query_execution, "get_clickhouse_executor", lambda: executor)

    payload, status_code = query_execution.execute_sql_payload(
        {"sql": "DELETE FROM etl.sales WHERE 1=1", "workspace_database": "etl"}
    )

    assert status_code == 400
    assert payload["status"] == "failed"
    assert executor.called is False


def test_empty_result_is_reported_clearly(monkeypatch):
    executor = _Executor(
        {
            "success": True,
            "rows": [],
            "columns": ["city", "total_sales"],
            "row_count": 0,
            "execution_time_ms": 5,
        }
    )
    monkeypatch.setattr(query_execution, "get_clickhouse_executor", lambda: executor)

    payload, status_code = query_execution.execute_sql_payload(
        {"sql": "SELECT city, SUM(total_sales) AS total_sales FROM etl.sales GROUP BY city", "workspace_database": "etl"}
    )

    assert status_code == 200
    assert payload["status"] == "success"
    assert payload["empty_result"] is True
    assert payload["row_count"] == 0


def test_with_cte_normalization_keeps_cte_alias_unqualified():
    sql = "WITH cte AS (SELECT ds, total_sales FROM sales) SELECT ds FROM cte"
    out = normalize_sql_table_references_detailed(sql, "etl")

    assert "etl.sales" in out["normalized_sql"]
    assert "FROM cte" in out["normalized_sql"] or "FROM `cte`" in out["normalized_sql"]
    assert "etl.cte" not in out["normalized_sql"]

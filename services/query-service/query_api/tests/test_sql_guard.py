import pytest

import importlib.util
import os
import sys
from pathlib import Path

SERVICE_ROOT = os.path.abspath("services/query-service")
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)


SERVICE_PATH = Path(__file__).resolve().parents[1] / "services" / "sql_guard.py"
spec = importlib.util.spec_from_file_location("query_sql_guard_under_test", SERVICE_PATH)
sql_guard_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(sql_guard_module)
SQLGuard = sql_guard_module.SQLGuard


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT ds, SUM(total_sales) FROM etl.sales_3months_realistic_csv GROUP BY ds",
        "WITH x AS (SELECT ds, total_sales FROM etl.sales_3months_realistic_csv) SELECT * FROM x",
        "SELECT toStartOfWeek(toDate(ds)) AS week, SUM(orders) FROM etl.sales_3months_realistic_csv GROUP BY week",
    ],
)
def test_safe_sql_allowed(sql):
    guard = SQLGuard(workspace_database="etl")
    is_valid, _, clean_sql = guard.validate_and_sanitize(sql)
    assert is_valid is True
    assert "SELECT" in clean_sql.upper()


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE users",
        "SELECT * FROM sales; DROP TABLE sales",
        "INSERT INTO x SELECT * FROM y",
        "DELETE FROM sales WHERE 1=1",
        "ALTER TABLE sales DELETE WHERE 1=1",
        "SELECT * FROM file('/etc/passwd')",
        "SELECT * FROM url('http://evil.com')",
        "SELECT * INTO OUTFILE 'x.csv' FROM sales",
        "/* hidden */ DROP TABLE sales",
    ],
)
def test_unsafe_sql_blocked(sql):
    guard = SQLGuard(workspace_database="etl")
    is_valid, reason, _ = guard.validate_and_sanitize(sql)
    assert is_valid is False
    assert reason

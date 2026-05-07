import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "utils" / "sql_normalization.py"
spec = importlib.util.spec_from_file_location("query_sql_normalization_under_test", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def test_simple_select_is_normalized():
    out = mod.normalize_sql_table_references_detailed(
        "SELECT ds FROM sales_3months_realistic_csv",
        "etl",
    )
    if "sqlglot_unavailable" in out["warnings"]:
        assert out["normalization_applied"] is False
        assert out["normalized_sql"] == "SELECT ds FROM sales_3months_realistic_csv"
    else:
        assert out["normalization_applied"] is True
        assert "etl.sales_3months_realistic_csv" in out["normalized_sql"]


def test_subquery_is_preserved():
    sql = "SELECT * FROM (SELECT ds FROM sales_3months_realistic_csv) s"
    out = mod.normalize_sql_table_references_detailed(sql, "etl")
    assert "FROM (" in out["normalized_sql"]
    assert " AS s" in out["normalized_sql"] or " s" in out["normalized_sql"]


def test_join_alias_is_preserved():
    sql = "SELECT a.ds FROM sales_3months_realistic_csv a JOIN etl.other_table b ON a.ds = b.ds"
    out = mod.normalize_sql_table_references_detailed(sql, "etl")
    assert "sales_3months_realistic_csv AS a" in out["normalized_sql"] or "sales_3months_realistic_csv a" in out["normalized_sql"]
    assert "other_table AS b" in out["normalized_sql"] or "other_table b" in out["normalized_sql"]


def test_invalid_sql_falls_back_safely():
    sql = "SELECT FROM"
    out = mod.normalize_sql_table_references_detailed(sql, "etl")
    assert out["normalized_sql"] == sql
    assert out["normalization_applied"] is False

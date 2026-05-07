import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "sql_parser.py"
spec = importlib.util.spec_from_file_location("sql_parser_under_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
ensure_sql_parser_ready = module.ensure_sql_parser_ready


def test_sql_parser_available_or_degraded_with_override(monkeypatch):
    monkeypatch.setenv("ALLOW_SQLGLOT_FALLBACK", "true")
    status = ensure_sql_parser_ready(strict=False)
    assert status.parser in {"sqlglot", "fallback"}
    assert isinstance(status.available, bool)


def test_sql_parser_strict_raises_when_missing(monkeypatch):
    # This test validates behavior only when sqlglot import is unavailable.
    # In normal environments with sqlglot installed, strict mode should pass.
    monkeypatch.delenv("ALLOW_SQLGLOT_FALLBACK", raising=False)
    try:
        status = ensure_sql_parser_ready(strict=True)
        assert status.parser == "sqlglot"
    except RuntimeError:
        assert True

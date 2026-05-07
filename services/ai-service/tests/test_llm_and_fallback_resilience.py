from __future__ import annotations

import os
import sys
import types
from unittest.mock import patch

if "clickhouse_connect" not in sys.modules:
    clickhouse_stub = types.ModuleType("clickhouse_connect")
    clickhouse_stub.get_client = lambda *args, **kwargs: None
    sys.modules["clickhouse_connect"] = clickhouse_stub

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")

    class _DummyError(Exception):
        pass

    class _DummyCompletions:
        @staticmethod
        def create(**kwargs):
            raise _DummyError("stub")

    class _DummyChat:
        completions = _DummyCompletions()

    class _DummyClient:
        def __init__(self, *args, **kwargs):
            self.chat = _DummyChat()

    openai_stub.APIError = _DummyError
    openai_stub.APITimeoutError = _DummyError
    openai_stub.AuthenticationError = _DummyError
    openai_stub.RateLimitError = _DummyError
    openai_stub.OpenAI = _DummyClient
    sys.modules["openai"] = openai_stub

sys.path.insert(0, os.path.abspath("services/ai-service"))

from intent_extraction.intent_extraction_task import run_intent_extraction_stage
from llm_app.llm_client import get_openrouter_diagnostics
from preprocessing_high.preprocess_high_task import run_preprocess_high
from preprocessing_high.schema_loader import LoadedUserSchema


def _schema() -> LoadedUserSchema:
    return LoadedUserSchema(
        user_id="u1",
        database="etl",
        schema={
            "tables": ["sales_fact"],
            "columns": {"sales_fact": [{"name": "ds", "type": "Date"}, {"name": "total_sales", "type": "Float64"}]},
        },
        columns_by_name={"ds": [], "total_sales": []},
        date_columns_by_name={"ds": []},
    )


def test_openrouter_diagnostics_have_sanitized_key_fields():
    diag = get_openrouter_diagnostics()
    assert "openrouter_key_present" in diag
    assert "openrouter_key_prefix" in diag
    assert len(str(diag.get("openrouter_key_prefix", ""))) <= 6


@patch("preprocessing_high.preprocess_high_task.load_user_schema")
@patch("preprocessing_high.preprocess_high_task.correct_query_terms")
def test_preprocess_high_uses_deterministic_first_and_skips_ollama_for_exact_schema(
    mock_correct_query_terms,
    mock_load_user_schema,
):
    mock_load_user_schema.return_value = _schema()
    result = run_preprocess_high(
        cleaned_text="Compare total sales across months",
        user_id="u1",
        route="analytical",
        dataset_scope={"table_name": "sales_fact"},
    )
    assert result.get("status") in {"success", "degraded"}
    assert mock_correct_query_terms.call_count == 0


@patch("intent_extraction.intent_extraction_task._extract_and_validate")
def test_intent_extraction_openrouter_failure_uses_charted_deterministic_fallback(mock_extract_and_validate):
    mock_extract_and_validate.side_effect = RuntimeError("OpenRouter authentication failed: 401 User not found")
    schema = {"sales_fact": [{"name": "ds", "type": "Date"}, {"name": "total_sales", "type": "Float64"}]}
    result = run_intent_extraction_stage(query="Compare total sales across months", schema=schema, route="analytical")
    assert result.get("status") == "degraded"
    validated = result.get("validated_intent", {}) if isinstance(result.get("validated_intent"), dict) else {}
    assert validated.get("selected_chart_type") in {"line", "line_multi"}
    assert validated.get("chart_type") in {"line", "line_multi"}

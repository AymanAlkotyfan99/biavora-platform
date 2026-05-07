import os
import sys

sys.path.insert(0, os.path.abspath("services/ai-service"))

from reasoning_app.intent_classification_task import (  # noqa: E402
    route_intent_classification,
    run_intent_classification,
)
from shared.sql_review import _build_review_prompt  # noqa: E402


def test_non_data_classification_is_rejected_before_sql_generation():
    result = run_intent_classification("Hello, how are you?")
    route = route_intent_classification("Hello, how are you?", result)

    assert result["status"] == "rejected"
    assert result["classification"] in {"conversational", "invalid_input"}
    assert result["is_analytical"] is False
    assert route["status"] == "rejected"
    assert route["next_step"] == "stop"


def test_sql_review_prompt_receives_chart_contract():
    prompt = _build_review_prompt(
        question="What is the share of orders by month?",
        normalized_question="share of orders by month",
        schema={"etl.orders": [{"name": "month", "type": "String"}, {"name": "orders", "type": "UInt64"}]},
        selected_table="etl.orders",
        selected_columns=["month", "orders"],
        chart_contract={"chart_type": "pie", "x_axis": "month", "y_axis": ["orders"], "locked": True},
        generated_sql="SELECT month, count() AS orders FROM etl.orders GROUP BY month",
        validated_intent={"query_type": "analytical", "dimensions": ["month"], "metrics": [{"column": "orders"}]},
        extracted_intent={"query_type": "analytical"},
    )

    assert "Chart contract:" in prompt
    assert '"chart_type": "pie"' in prompt
    assert "Selected table:" in prompt
    assert "Selected columns:" in prompt

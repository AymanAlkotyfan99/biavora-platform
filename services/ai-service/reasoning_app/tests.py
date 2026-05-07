from __future__ import annotations

import unittest
from unittest.mock import patch

from preprocessing_high.diagnostics import build_schema_resolution_diagnostics
from preprocessing_low.preprocess_task import run_preprocess_text
from reasoning_app.intent_classification_task import run_intent_classification
from reasoning_app.llm_intent_client import is_force_analytical
from shared.input_classifier import classify_input
from shared.pipeline_trace import attach_stage, build_pipeline_trace_template, finalize_trace, make_attempt, stage_payload


class _FakeLoadedSchema:
    def __init__(self, columns_by_table: dict[str, list[dict[str, str]]]) -> None:
        self.user_id = "u1"
        self.database = "etl"
        self.schema = {"tables": list(columns_by_table.keys()), "columns": columns_by_table}
        self.columns_by_name = {}
        self.date_columns_by_name = {}


def _build_loaded_schema(columns_by_table: dict[str, list[dict[str, str]]]):
    columns_by_name = {}
    date_columns_by_name = {}
    for table_name, columns in columns_by_table.items():
        for column in columns:
            name = column["name"]
            ref = type("ColumnRef", (), {"table": table_name, "name": name, "type": column.get("type", "")})()
            columns_by_name.setdefault(name.lower(), []).append(ref)
            if "date" in column.get("type", "").lower() or "time" in column.get("type", "").lower():
                date_columns_by_name.setdefault(name.lower(), []).append(ref)
    loaded = _FakeLoadedSchema(columns_by_table)
    loaded.columns_by_name = columns_by_name
    loaded.date_columns_by_name = date_columns_by_name
    return loaded


class ReasoningRulesTests(unittest.TestCase):
    def test_analytical_keyword_guard(self):
        self.assertTrue(is_force_analytical("show top 5 regions by population"))
        self.assertFalse(is_force_analytical("hello how are you"))

    @patch("reasoning_app.intent_classification_task.classify_question")
    def test_rule_based_detection_short_circuits_llm(self, mock_classify_question):
        mock_classify_question.return_value = {
            "classification": "conversational",
            "question_type": "conversational",
            "needs_sql": False,
            "llm_explicit_decision": True,
            "decision_source": "llm_explicit",
        }
        question = "show total population by region"
        result = run_intent_classification(
            cleaned_text=question,
            raw_text=question,
            source="text",
            transcription_status="success",
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["classification"], "analytical")
        self.assertTrue(result["is_analytical"])
        self.assertEqual(result["classification_reason"], "rule_based_analytical_detection")
        mock_classify_question.assert_not_called()

    @patch("reasoning_app.intent_classification_task.classify_question")
    def test_rule_based_conversational_guard_short_circuits_llm_for_greeting(self, mock_classify_question):
        mock_classify_question.return_value = {
            "classification": "conversational",
            "question_type": "conversational",
            "needs_sql": False,
            "needs_chart": False,
            "llm_explicit_decision": True,
            "decision_source": "llm_explicit",
        }
        question = "hello how are you"
        result = run_intent_classification(
            cleaned_text=question,
            raw_text=question,
            source="text",
            transcription_status="success",
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["classification"], "conversational")
        self.assertFalse(result["is_analytical"])
        self.assertEqual(result["classification_reason"], "rule_based_conversational_detection")
        mock_classify_question.assert_not_called()

    @patch("reasoning_app.intent_classification_task.classify_question")
    def test_non_explicit_llm_conversational_defaults_to_analytical(self, mock_classify_question):
        mock_classify_question.return_value = {
            "classification": "conversational",
            "question_type": "conversational",
            "needs_sql": False,
            "llm_explicit_decision": False,
            "decision_source": "heuristic_conversational_pattern",
        }
        question = "show me what you can do"
        result = run_intent_classification(
            cleaned_text=question,
            raw_text=question,
            source="text",
            transcription_status="success",
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["classification"], "conversational")
        self.assertFalse(result["is_analytical"])
        self.assertEqual(result["classification_reason"], "heuristic_conversational_alignment")

    @patch("reasoning_app.intent_classification_task.classify_question")
    def test_llm_error_defaults_to_analytical(self, mock_classify_question):
        mock_classify_question.side_effect = RuntimeError("ollama unavailable")
        question = "what can you do"
        result = run_intent_classification(
            cleaned_text=question,
            raw_text=question,
            source="text",
            transcription_status="success",
        )
        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result.get("degraded"))
        self.assertEqual(result.get("degradation_reason"), "intent_classification_llm_error_fallback")
        self.assertEqual(result["classification"], "conversational")
        self.assertFalse(result["is_analytical"])
        self.assertEqual(result["classification_reason"], "safety_default_conversational_on_llm_error")

    def test_average_age_by_city_is_analytical(self):
        question = "Average age by city"
        result = run_intent_classification(
            cleaned_text=question,
            raw_text=question,
            source="text",
            transcription_status="success",
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["classification"], "analytical")
        self.assertTrue(result["is_analytical"])

    def test_cumulative_total_sales_with_underscore_is_analytical(self):
        question = "Show cumulative total_sales over time"
        result = run_intent_classification(
            cleaned_text=question,
            raw_text=question,
            source="text",
            transcription_status="success",
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["classification"], "analytical")
        self.assertTrue(result["is_analytical"])

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", side_effect=RuntimeError("ollama down"))
    def test_low_preprocess_uses_rule_based_fallback_when_llm_fails(self, _mock_llm):
        result = run_preprocess_text("show total population by region")
        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result.get("degraded"))
        self.assertEqual(result.get("degradation_reason"), "llm_preprocessing_fallback")
        self.assertEqual(result["cleaned_text"], "show total population by region")
        warning_types = {warning.get("type") for warning in result.get("warnings", [])}
        self.assertIn("llm_preprocessing_fallback", warning_types)
        self.assertTrue(result.get("debug_metadata", {}).get("llm_fallback_used"))


class PipelineCaseCoverageTests(unittest.TestCase):
    def _population_schema(self):
        return _build_loaded_schema(
            {
                "population_distribution_csv": [
                    {"name": "region", "type": "String"},
                    {"name": "city", "type": "String"},
                    {"name": "total_population", "type": "UInt64"},
                    {"name": "male_population", "type": "UInt64"},
                    {"name": "female_population", "type": "UInt64"},
                    {"name": "avg_age", "type": "Float64"},
                    {"name": "employment_rate", "type": "Float64"},
                ]
            }
        )

    def _assert_trace_shape(self, trace: dict) -> None:
        expected_sections = [
            "request_metadata",
            "input_validation",
            "transcription",
            "preprocessing_low",
            "preprocessing_high",
            "routing",
            "analytical_intent",
            "sql_generation",
            "sql_review",
            "sql_validation",
            "query_execution",
            "visualization",
            "final_response",
            "dagster_runtime",
            "overall_status",
            "root_cause",
        ]
        for section in expected_sections:
            self.assertIn(section, trace)

    def _trace_for_classification(self, classification_result: dict, request_id: str) -> dict:
        trace = build_pipeline_trace_template({"request_id": request_id})
        attempt = make_attempt(
            attempt_number=1,
            input_payload={"raw_text": "sample"},
            output_payload=classification_result,
            success=True,
            retry_triggered=False,
            model_or_method_used="rule_based_input_classifier",
            duration_ms=1,
            validation_result={"is_valid": True},
        )
        attach_stage(
            trace,
            "input_validation",
            stage_payload(
                status="success",
                final_output=classification_result,
                attempts=[attempt],
                errors=[],
                warnings=[],
                debug_metadata={},
            ),
        )
        finalize_trace(
            trace,
            overall_status="rejected",
            final_route=str(classification_result.get("classification", "stop")),
            final_user_message=str(classification_result.get("reason", "")),
            root_cause_category="input",
            root_cause_detail=str(classification_result.get("reason", "")),
            analyst_recommended_fix="Provide a valid analytical request.",
        )
        return trace

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", side_effect=lambda text, **_: text)
    def test_case_a_low_preprocessing_filler_cleanup(self, _mock_llm):
        result = run_preprocess_text("ummm show me like the total revenue uhh by region please")
        self.assertEqual(result["status"], "success")
        self.assertNotIn("umm", result["cleaned_text"].lower())
        self.assertNotIn("uhh", result["cleaned_text"].lower())
        self.assertNotIn(" like ", f" {result['cleaned_text'].lower()} ")
        self.assertNotIn("please", result["cleaned_text"].lower())
        self.assertGreaterEqual(result.get("attempts_count", 0), 1)
        self.assertTrue(any(change.get("type") for change in result.get("detected_changes", [])))

        trace = build_pipeline_trace_template({"request_id": "a"})
        attach_stage(
            trace,
            "preprocessing_low",
            stage_payload(
                status="success",
                final_output=result,
                attempts=result.get("attempts", []),
                errors=result.get("errors", []),
                warnings=result.get("warnings", []),
                debug_metadata=result.get("debug_metadata", {}),
            ),
        )
        finalize_trace(
            trace,
            overall_status="success",
            final_route="analytical",
            final_user_message="cleaned",
            root_cause_category="none",
            root_cause_detail="",
            analyst_recommended_fix="",
        )
        self._assert_trace_shape(trace)

    def test_case_b_typo_revenue_resolution(self):
        schema = _build_loaded_schema(
            {"sales": [{"name": "revenue", "type": "Float64"}, {"name": "region", "type": "String"}]}
        )
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show reveneu by region",
            corrected_query="show revenue by region",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [
                    {
                        "requested": "reveneu",
                        "matched_table": "sales",
                        "matched_column": "revenue",
                        "status": "mapped",
                        "reason": "Typo corrected",
                    }
                ],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        statuses = {item["resolution_status"] for item in diagnostics["term_resolutions"]}
        self.assertIn("corrected_typo", statuses)
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        trace = build_pipeline_trace_template({"request_id": "b"})
        attach_stage(
            trace,
            "preprocessing_high",
            stage_payload(
                status="success",
                final_output=diagnostics,
                attempts=[make_attempt(attempt_number=1, input_payload={}, output_payload=diagnostics, success=True, retry_triggered=False)],
            ),
        )
        finalize_trace(
            trace,
            overall_status="success",
            final_route="analytical",
            final_user_message="ok",
            root_cause_category="none",
            root_cause_detail="",
            analyst_recommended_fix="",
        )
        self._assert_trace_shape(trace)

    def test_case_c_avg_revenue_by_region(self):
        classification = classify_input(raw_text="show avg revenue by region", cleaned_text="show avg revenue by region")
        self.assertEqual(classification["classification"], "analytical")

        schema = _build_loaded_schema(
            {"sales": [{"name": "revenue", "type": "Float64"}, {"name": "region", "type": "String"}]}
        )
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show avg revenue by region",
            corrected_query="show avg revenue by region",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [
                    {
                        "requested": "revenue",
                        "matched_table": "sales",
                        "matched_column": "revenue",
                        "status": "exact",
                        "reason": "Exact match",
                    },
                    {
                        "requested": "region",
                        "matched_table": "sales",
                        "matched_column": "region",
                        "status": "exact",
                        "reason": "Exact match",
                    },
                ],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertEqual(diagnostics["unresolved_terms"], [])
        trace = build_pipeline_trace_template({"request_id": "c"})
        attach_stage(
            trace,
            "preprocessing_high",
            stage_payload(
                status="success",
                final_output=diagnostics,
                attempts=[make_attempt(attempt_number=1, input_payload={}, output_payload=diagnostics, success=True, retry_triggered=False)],
            ),
        )
        finalize_trace(
            trace,
            overall_status="success",
            final_route="analytical",
            final_user_message="ok",
            root_cause_category="none",
            root_cause_detail="",
            analyst_recommended_fix="",
        )
        self._assert_trace_shape(trace)

    def test_case_c2_average_age_by_city(self):
        classification = classify_input(raw_text="Average age by city", cleaned_text="Average age by city")
        self.assertEqual(classification["classification"], "analytical")

    def test_case_c3_semantic_mapping_is_not_marked_unresolved(self):
        schema = self._population_schema()
        diagnostics = build_schema_resolution_diagnostics(
            original_query="average age by city",
            corrected_query="average avg_age by city",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [
                    {
                        "requested": "age",
                        "matched_table": "population_distribution_csv",
                        "matched_column": "avg_age",
                        "status": "mapped",
                        "reason": "Mapped semantic metric.",
                    }
                ],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertNotIn("age", diagnostics["unresolved_terms"])
        self.assertIn("avg_age", diagnostics["selected_columns"])

    def test_case_d_revenue_by_year_unsupported(self):
        schema = _build_loaded_schema({"sales": [{"name": "region", "type": "String"}]})
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show revenue by year",
            corrected_query="show revenue by year",
            loaded_schema=schema,
            validation_result={
                "is_valid": False,
                "missing_column": "revenue",
                "mappings": [],
                "derivable_columns": [],
                "invalid_mappings": [
                    {
                        "requested": "revenue",
                        "matched_table": "",
                        "matched_column": "",
                        "status": "invalid",
                        "reason": "No metric match",
                    }
                ],
            },
        )
        self.assertIn("year", diagnostics["unsupported_terms"])
        self.assertIn("revenue", diagnostics["unresolved_terms"])
        self.assertNotEqual(diagnostics["schema_validation_status"], "valid")
        trace = build_pipeline_trace_template({"request_id": "d"})
        attach_stage(
            trace,
            "preprocessing_high",
            stage_payload(
                status="rejected",
                final_output=diagnostics,
                attempts=[make_attempt(attempt_number=1, input_payload={}, output_payload=diagnostics, success=False, retry_triggered=False)],
                errors=[{"type": "schema", "message": "Unsupported schema terms"}],
            ),
        )
        finalize_trace(
            trace,
            overall_status="rejected",
            final_route="stop",
            final_user_message="unsupported schema",
            root_cause_category="schema",
            root_cause_detail="unsupported term(s)",
            analyst_recommended_fix="add revenue/date fields",
        )
        self._assert_trace_shape(trace)

    def test_case_e_profit_margin_unresolved(self):
        schema = _build_loaded_schema(
            {"sales": [{"name": "revenue", "type": "Float64"}, {"name": "region", "type": "String"}]}
        )
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show profit_margin by region",
            corrected_query="show profit_margin by region",
            loaded_schema=schema,
            validation_result={
                "is_valid": False,
                "missing_column": "profit_margin",
                "mappings": [],
                "derivable_columns": [],
                "invalid_mappings": [
                    {
                        "requested": "profit_margin",
                        "matched_table": "",
                        "matched_column": "",
                        "status": "invalid",
                        "reason": "No metric match",
                    }
                ],
            },
        )
        self.assertIn("profit_margin", diagnostics["unresolved_terms"])
        self.assertIn("invalid", diagnostics["schema_validation_status"])
        trace = build_pipeline_trace_template({"request_id": "e"})
        attach_stage(
            trace,
            "preprocessing_high",
            stage_payload(
                status="rejected",
                final_output=diagnostics,
                attempts=[make_attempt(attempt_number=1, input_payload={}, output_payload=diagnostics, success=False, retry_triggered=False)],
                errors=[{"type": "schema", "message": "unresolved term profit_margin"}],
            ),
        )
        finalize_trace(
            trace,
            overall_status="rejected",
            final_route="stop",
            final_user_message="unresolved metric",
            root_cause_category="schema",
            root_cause_detail="profit_margin unresolved",
            analyst_recommended_fix="use supported metric or update schema",
        )
        self._assert_trace_shape(trace)

    def test_case_f_conversational_classification(self):
        result = classify_input(raw_text="how are you today?", cleaned_text="how are you today?")
        self.assertEqual(result["classification"], "conversational")
        self.assertEqual(result["route"], "stop")
        trace = self._trace_for_classification(result, "f")
        self.assertEqual(trace["root_cause"]["root_cause_category"], "input")
        self._assert_trace_shape(trace)

    def test_case_g_punctuation_invalid_input(self):
        result = classify_input(raw_text=".", cleaned_text=".")
        self.assertEqual(result["classification"], "invalid_input")
        self.assertEqual(result["reason"], "punctuation_only")
        trace = self._trace_for_classification(result, "g")
        self.assertEqual(trace["overall_status"]["status"], "rejected")
        self._assert_trace_shape(trace)

    def test_case_h_empty_input(self):
        result = classify_input(raw_text="", cleaned_text="")
        self.assertEqual(result["classification"], "empty_input")
        trace = self._trace_for_classification(result, "h")
        self.assertEqual(trace["input_validation"]["attempts_count"], 1)
        self._assert_trace_shape(trace)

    def test_case_i_no_speech_audio(self):
        result = classify_input(raw_text="", cleaned_text="", source="audio")
        self.assertEqual(result["classification"], "no_speech_detected")
        self.assertEqual(result["route"], "stop")
        trace = self._trace_for_classification(result, "i")
        self.assertEqual(trace["overall_status"]["final_route"], "no_speech_detected")
        self._assert_trace_shape(trace)

    def test_case_j_valid_total_population_by_region(self):
        schema = self._population_schema()
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show total population by region",
            corrected_query="show total population by region",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertEqual(diagnostics["selected_table"], "population_distribution_csv")
        self.assertIn("total_population", diagnostics["selected_columns"])
        self.assertIn("region", diagnostics["selected_columns"])
        self.assertEqual(diagnostics["unresolved_terms"], [])
        self.assertEqual(diagnostics["unsupported_terms"], [])

    def test_case_k_valid_top_cities_by_total_population(self):
        schema = self._population_schema()
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show top 5 cities by total population",
            corrected_query="show top 5 cities by total population",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        statuses = {item["resolution_status"] for item in diagnostics["term_resolutions"]}
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertIn("corrected_typo", statuses)
        self.assertEqual(diagnostics["selected_table"], "population_distribution_csv")
        self.assertIn("city", diagnostics["selected_columns"])
        self.assertIn("total_population", diagnostics["selected_columns"])

    def test_case_k2_ranking_language_is_not_marked_unresolved_schema(self):
        schema = self._population_schema()
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show the city with the highest population",
            corrected_query="show the city with the highest total_population",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [
                    {
                        "requested": "population",
                        "matched_table": "population_distribution_csv",
                        "matched_column": "total_population",
                        "status": "mapped",
                        "reason": "Semantic metric mapping.",
                    }
                ],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertNotIn("highest", diagnostics["unresolved_terms"])

    def test_case_k2b_relationship_language_is_not_marked_unresolved_schema(self):
        schema = _build_loaded_schema(
            {
                "sales_3months_realistic_csv": [
                    {"name": "ds", "type": "Date"},
                    {"name": "total_sales", "type": "Float64"},
                    {"name": "orders", "type": "UInt64"},
                    {"name": "customers", "type": "UInt64"},
                ]
            }
        )
        diagnostics = build_schema_resolution_diagnostics(
            original_query="what is the relationship between customers and total sales",
            corrected_query="what is the relationship between customers and total_sales",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [
                    {
                        "requested": "customers",
                        "matched_table": "sales_3months_realistic_csv",
                        "matched_column": "customers",
                        "status": "exact",
                        "reason": "Exact match.",
                    },
                    {
                        "requested": "sales",
                        "matched_table": "sales_3months_realistic_csv",
                        "matched_column": "total_sales",
                        "status": "mapped",
                        "reason": "Metric mapping.",
                    },
                ],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertNotIn("relationship", diagnostics["unresolved_terms"])

    def test_case_k2c_value_language_is_not_marked_unresolved_schema(self):
        schema = _build_loaded_schema(
            {
                "sales_3months_realistic_csv": [
                    {"name": "ds", "type": "Date"},
                    {"name": "total_sales", "type": "Float64"},
                    {"name": "orders", "type": "UInt64"},
                    {"name": "customers", "type": "UInt64"},
                ]
            }
        )
        diagnostics = build_schema_resolution_diagnostics(
            original_query="what is the average order value per day",
            corrected_query="what is the average orders value per ds",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [
                    {
                        "requested": "orders",
                        "matched_table": "sales_3months_realistic_csv",
                        "matched_column": "orders",
                        "status": "exact",
                        "reason": "Exact match.",
                    },
                    {
                        "requested": "day",
                        "matched_table": "sales_3months_realistic_csv",
                        "matched_column": "ds",
                        "status": "mapped",
                        "reason": "Mapped date axis.",
                    },
                ],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertNotIn("value", diagnostics["unresolved_terms"])

    def test_case_k3_literal_filter_value_is_not_schema_unresolved(self):
        schema = self._population_schema()
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show cities in the north region",
            corrected_query="show cities in the north region",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [
                    {
                        "requested": "region",
                        "matched_table": "population_distribution_csv",
                        "matched_column": "region",
                        "status": "exact",
                        "reason": "Exact match.",
                    },
                    {
                        "requested": "city",
                        "matched_table": "population_distribution_csv",
                        "matched_column": "city",
                        "status": "exact",
                        "reason": "Exact match.",
                    },
                ],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertNotIn("north", diagnostics["unresolved_terms"])

    def test_case_k4_comparison_language_is_not_schema_unresolved(self):
        schema = self._population_schema()
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show total population for cities where employment rate is above 55",
            corrected_query="show total population for cities where employment_rate is above 55",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [
                    {
                        "requested": "total population",
                        "matched_table": "population_distribution_csv",
                        "matched_column": "total_population",
                        "status": "mapped",
                        "reason": "Metric mapping.",
                    },
                    {
                        "requested": "employment rate",
                        "matched_table": "population_distribution_csv",
                        "matched_column": "employment_rate",
                        "status": "mapped",
                        "reason": "Metric mapping.",
                    },
                    {
                        "requested": "cities",
                        "matched_table": "population_distribution_csv",
                        "matched_column": "city",
                        "status": "mapped",
                        "reason": "Dimension mapping.",
                    },
                ],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertNotIn("where", diagnostics["unresolved_terms"])
        self.assertNotIn("above", diagnostics["unresolved_terms"])

    def test_case_k5_over_time_phrase_is_not_unsupported(self):
        schema = _build_loaded_schema(
            {
                "sales_3months_realistic_csv": [
                    {"name": "ds", "type": "String"},
                    {"name": "total_sales", "type": "Float64"},
                    {"name": "orders", "type": "UInt64"},
                    {"name": "customers", "type": "UInt64"},
                ]
            }
        )
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show total sales over time",
            corrected_query="show total_sales over time",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [
                    {
                        "requested": "sales",
                        "matched_table": "sales_3months_realistic_csv",
                        "matched_column": "total_sales",
                        "status": "mapped",
                        "reason": "Metric mapping.",
                    }
                ],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertNotIn("time", diagnostics["unsupported_terms"])
        self.assertNotIn("time", diagnostics["unresolved_terms"])
        self.assertIn("total_sales", diagnostics["selected_columns"])

    def test_case_k6_daily_per_month_is_not_unresolved_with_ds_time_key(self):
        schema = _build_loaded_schema(
            {
                "sales_3months_realistic_csv": [
                    {"name": "ds", "type": "String"},
                    {"name": "total_sales", "type": "Float64"},
                    {"name": "orders", "type": "UInt64"},
                    {"name": "customers", "type": "UInt64"},
                ]
            }
        )
        diagnostics = build_schema_resolution_diagnostics(
            original_query="what is the average daily sales per month",
            corrected_query="what is the average daily total_sales per month",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [
                    {
                        "requested": "sales",
                        "matched_table": "sales_3months_realistic_csv",
                        "matched_column": "total_sales",
                        "status": "mapped",
                        "reason": "Metric mapping.",
                    }
                ],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertNotIn("daily", diagnostics["unresolved_terms"])
        self.assertNotIn("daily", diagnostics["unsupported_terms"])
        self.assertNotIn("month", diagnostics["unresolved_terms"])
        self.assertNotIn("month", diagnostics["unsupported_terms"])
        self.assertIn("total_sales", diagnostics["selected_columns"])

    def test_case_k7_revenue_maps_to_total_sales_for_sales_schema(self):
        schema = _build_loaded_schema(
            {
                "sales_3months_realistic_csv": [
                    {"name": "ds", "type": "Date"},
                    {"name": "total_sales", "type": "Float64"},
                    {"name": "orders", "type": "UInt64"},
                    {"name": "customers", "type": "UInt64"},
                ]
            }
        )
        diagnostics = build_schema_resolution_diagnostics(
            original_query="what is the total revenue per week",
            corrected_query="what is the total revenue per week",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertNotIn("revenue", diagnostics["unresolved_terms"])
        self.assertIn("total_sales", diagnostics["selected_columns"])

    def test_case_l_invalid_revenue_by_region(self):
        schema = self._population_schema()
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show revenue by region",
            corrected_query="show revenue by region",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "invalid_unresolved_terms")
        self.assertIn("revenue", diagnostics["unresolved_terms"])

    def test_case_m_invalid_population_by_year(self):
        schema = self._population_schema()
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show population by year",
            corrected_query="show population by year",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertIn("year", diagnostics["unsupported_terms"])
        self.assertIn(diagnostics["schema_validation_status"], {"invalid_unresolved_terms", "invalid_unsupported_terms"})

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", side_effect=lambda text, **_: text)
    def test_case_n_noise_query_preprocessing(self, _mock_llm):
        result = run_preprocess_text("ummm show population please")
        self.assertEqual(result["status"], "success")
        self.assertNotIn("umm", result["cleaned_text"].lower())
        self.assertNotIn("please", result["cleaned_text"].lower())
        self.assertGreaterEqual(len(result["detected_changes"]), 1)

    def test_case_q_selected_table_is_not_hardcoded(self):
        schema = _build_loaded_schema(
            {
                "population_distribution_csv": [
                    {"name": "region", "type": "String"},
                    {"name": "total_population", "type": "UInt64"},
                ],
                "customer_stats": [
                    {"name": "region", "type": "String"},
                    {"name": "customer_count", "type": "UInt64"},
                ],
            }
        )
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show customer count by region",
            corrected_query="show customer_count by region",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [
                    {
                        "requested": "customer_count",
                        "matched_table": "customer_stats",
                        "matched_column": "customer_count",
                        "status": "mapped",
                        "reason": "Exact metric mapping.",
                    }
                ],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertEqual(diagnostics["schema_validation_status"], "valid")
        self.assertEqual(diagnostics["selected_table"], "customer_stats")
        self.assertIn("customer_count", diagnostics["selected_columns"])

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", side_effect=lambda text, **_: text)
    def test_case_r_normal_query_preserved(self, _mock_llm):
        result = run_preprocess_text("show total population by region")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cleaned_text"], "show total population by region")

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", side_effect=lambda text, **_: text)
    def test_case_s_missing_spaces_word_glue(self, _mock_llm):
        result = run_preprocess_text("showtotalpopulationbyregion")
        self.assertEqual(result["status"], "success")
        self.assertIn("show", result["cleaned_text"].lower())
        self.assertIn("total", result["cleaned_text"].lower())
        self.assertIn("population", result["cleaned_text"].lower())
        self.assertIn("region", result["cleaned_text"].lower())
        self.assertNotIn("showtotalpopulationbyregion", result["cleaned_text"].lower())

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", side_effect=lambda text, **_: text)
    def test_case_t_missing_spaces_numeric_word_glue(self, _mock_llm):
        result = run_preprocess_text("top10citiesbyregion")
        self.assertEqual(result["status"], "success")
        normalized = result["cleaned_text"].lower()
        self.assertIn("top 10", normalized)
        self.assertIn("by region", normalized)

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", side_effect=lambda text, **_: text)
    def test_case_u_combined_noise_glue_typo(self, _mock_llm):
        result = run_preprocess_text("ummm top10citiesbyreveneu please")
        self.assertEqual(result["status"], "success")
        normalized = result["cleaned_text"].lower()
        self.assertNotIn("umm", normalized)
        self.assertNotIn("please", normalized)
        self.assertIn("top 10", normalized)
        self.assertRegex(normalized, r"\b(revenue|reveneu)\b")

    def test_case_v_safe_plural_singular_handling_in_diagnostics(self):
        schema = _build_loaded_schema(
            {"orders": [{"name": "status", "type": "String"}, {"name": "region", "type": "String"}]}
        )
        diagnostics = build_schema_resolution_diagnostics(
            original_query="show status by region",
            corrected_query="show status by region",
            loaded_schema=schema,
            validation_result={
                "is_valid": True,
                "missing_column": "",
                "mappings": [
                    {
                        "requested": "status",
                        "matched_table": "orders",
                        "matched_column": "status",
                        "status": "mapped",
                        "reason": "Exact column mapping.",
                    }
                ],
                "derivable_columns": [],
                "invalid_mappings": [],
            },
        )
        self.assertNotIn("statu", diagnostics.get("unresolved_terms", []))
        self.assertEqual(diagnostics.get("schema_validation_status"), "valid")

    def test_case_o_numeric_only_classification(self):
        result = classify_input(raw_text="123123", cleaned_text="123123")
        self.assertEqual(result["classification"], "invalid_input")
        self.assertEqual(result["reason"], "numeric_only")

    def test_case_p_noise_classification(self):
        result = classify_input(raw_text="uhhh", cleaned_text="")
        self.assertEqual(result["classification"], "noise_input")
        self.assertEqual(result["route"], "stop")

    def test_case_w_distribution_classification(self):
        result = classify_input(
            raw_text="How are orders distributed?",
            cleaned_text="How are orders distributed?",
        )
        self.assertEqual(result["classification"], "analytical")
        self.assertEqual(result["route"], "proceed")

    def test_case_x_impact_classification(self):
        result = classify_input(
            raw_text="How do customers impact total sales?",
            cleaned_text="How do customers impact total sales?",
        )
        self.assertEqual(result["classification"], "analytical")
        self.assertEqual(result["route"], "proceed")

    def test_attempt_visibility_in_trace_payload(self):
        trace = build_pipeline_trace_template({"request_id": "attempt-case"})
        attempt = make_attempt(
            attempt_number=1,
            input_payload={"text": "show revenue by region"},
            output_payload={"classification": "analytical"},
            success=True,
            retry_triggered=False,
            model_or_method_used="unit-test",
            duration_ms=3,
            validation_result={"is_valid": True},
        )
        attach_stage(
            trace,
            "input_validation",
            stage_payload(
                status="success",
                final_output={"classification": "analytical"},
                attempts=[attempt],
                errors=[],
                warnings=[],
                debug_metadata={},
            ),
        )
        finalize_trace(
            trace,
            overall_status="success",
            final_route="analytical",
            final_user_message="ok",
            root_cause_category="none",
            root_cause_detail="",
            analyst_recommended_fix="",
        )
        self.assertEqual(trace["input_validation"]["attempts_count"], 1)
        self.assertEqual(trace["input_validation"]["attempts"][0]["attempt_number"], 1)
        self.assertEqual(trace["overall_status"]["status"], "success")
        self._assert_trace_shape(trace)

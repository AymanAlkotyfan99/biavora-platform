from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from preprocessing_low.preprocess_task import run_preprocess_text
from shared.input_classifier import classify_input


class PreprocessingLowSpellingTests(unittest.TestCase):
    def _assert_preclassified_analytical(self, raw_text: str, cleaned_text: str) -> None:
        classification = classify_input(raw_text=raw_text, cleaned_text=cleaned_text)
        self.assertNotIn(
            classification.get("classification"),
            {"conversational", "invalid_input", "noise_input", "empty_input", "numeric_only_input"},
        )

    @patch(
        "preprocessing_low.preprocess_task._call_ollama_preprocessor",
        return_value="Which days had the highest number of customers?",
    )
    def test_regression_highest_customers_typos_corrected_before_classification(self, _mock_clean_llm):
        source = "Which days had the heghest number of costomers?"
        result = run_preprocess_text(source)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["original_text"], source)
        self.assertEqual(result["cleaned_text"], "Which days had the highest number of customers?")
        self.assertEqual(result.get("correction_source"), "llm_based")
        self.assertTrue(result["has_spelling_correction"])
        self.assertIn({"original": "heghest", "corrected": "highest"}, result.get("spelling_changes", []))
        self.assertIn({"original": "costomers", "corrected": "customers"}, result.get("spelling_changes", []))
        self.assertEqual(
            result.get("changes", {}).get("spelling_corrections", []),
            result.get("spelling_changes", []),
        )
        self._assert_preclassified_analytical(source, result["cleaned_text"])

    @patch(
        "preprocessing_low.preprocess_task._call_ollama_preprocessor",
        return_value="How do customers impact total sales?",
    )
    def test_regression_filler_and_typos_corrected_before_classification(self, _mock_clean_llm):
        source = "umm how do costomers impact totol sales?"
        result = run_preprocess_text(source)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cleaned_text"], "How do customers impact total sales?")
        self.assertEqual(result.get("correction_source"), "llm_based")
        self.assertIn({"original": "costomers", "corrected": "customers"}, result.get("spelling_changes", []))
        self.assertIn({"original": "totol", "corrected": "total"}, result.get("spelling_changes", []))
        self.assertIn("umm", [word.lower() for word in result.get("removed_filler_words", [])])
        self._assert_preclassified_analytical(source, result["cleaned_text"])

    @patch(
        "preprocessing_low.preprocess_task._call_ollama_preprocessor",
        return_value="Show average orders per day",
    )
    def test_regression_average_orders_typo_corrected_before_classification(self, _mock_clean_llm):
        source = "hi show averge orders per day"
        result = run_preprocess_text(source)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cleaned_text"], "Show average orders per day")
        self.assertEqual(result.get("correction_source"), "llm_based")
        self.assertIn({"original": "averge", "corrected": "average"}, result.get("spelling_changes", []))
        self.assertIn("hi", [word.lower() for word in result.get("removed_filler_words", [])])
        self._assert_preclassified_analytical(source, result["cleaned_text"])

    @patch(
        "preprocessing_low.preprocess_task._call_ollama_preprocessor",
        return_value="Predict monthly sales",
    )
    def test_regression_predict_monthly_typo_corrected_before_classification(self, _mock_clean_llm):
        source = "predict montly sales"
        result = run_preprocess_text(source)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cleaned_text"], "Predict monthly sales")
        self.assertEqual(result.get("correction_source"), "llm_based")
        self.assertIn({"original": "montly", "corrected": "monthly"}, result.get("spelling_changes", []))
        self._assert_preclassified_analytical(source, result["cleaned_text"])

    @patch(
        "preprocessing_low.preprocess_task._call_ollama_prompt",
        return_value="Which days had the highest number of customers?",
    )
    @patch(
        "preprocessing_low.preprocess_task._call_ollama_preprocessor",
        return_value="Which days had the heghest number of customers?",
    )
    def test_spelling_pass_corrects_typos_when_cleaner_output_still_contains_mistakes(
        self,
        _mock_clean_llm,
        _mock_spelling_llm,
    ):
        source = "Which days had the heghest number of customers?"
        result = run_preprocess_text(source)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cleaned_text"], "Which days had the highest number of customers?")
        self.assertEqual(result.get("correction_source"), "llm_based")
        self.assertTrue(result["has_spelling_correction"])
        self.assertIn({"original": "heghest", "corrected": "highest"}, result.get("spelling_changes", []))
        self._assert_preclassified_analytical(source, result["cleaned_text"])

    @patch("preprocessing_low.preprocess_task._call_ollama_preprocessor", side_effect=RuntimeError("ollama down"))
    def test_fallback_uses_rule_based_cleaner_when_llm_fails(self, _mock_clean_llm):
        source = "umm how do costomers impact totol sales?"
        result = run_preprocess_text(source)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result.get("correction_source"), "rule_based_fallback")
        self.assertEqual(result["cleaned_text"], "how do customers impact total sales?")
        self.assertTrue(result["has_spelling_correction"])
        self.assertIn({"original": "costomers", "corrected": "customers"}, result.get("spelling_changes", []))
        self.assertIn({"original": "totol", "corrected": "total"}, result.get("spelling_changes", []))
        self.assertIn("umm", [word.lower() for word in result.get("removed_filler_words", [])])
        self.assertTrue(any(w.get("type") == "llm_preprocessing_fallback" for w in result.get("warnings", [])))


if __name__ == "__main__":
    unittest.main()

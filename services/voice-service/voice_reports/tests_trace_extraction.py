from __future__ import annotations

from voice_reports.utils.trace_extraction import extract_pipeline_trace, is_valid_trace


def _full_trace() -> dict:
    return {
        "preprocessing_low": {"status": "success"},
        "classification": {"status": "success"},
        "intent_extraction": {"status": "success"},
        "query_execution": {"status": "success"},
        "visualization": {"status": "success"},
    }


def test_is_valid_trace_true_for_full_trace():
    assert is_valid_trace(_full_trace()) is True


def test_is_valid_trace_false_for_partial_trace():
    assert is_valid_trace({"overall_status": {"status": "failed"}, "root_cause": {"code": "x"}}) is False


def test_extract_pipeline_trace_from_nested_result():
    payload = {"result": {"pipeline_trace": _full_trace()}, "overall_status": {"status": "success"}}
    extracted = extract_pipeline_trace(payload)
    assert is_valid_trace(extracted) is True
    assert "classification" in extracted


def test_extract_pipeline_trace_returns_partial_when_no_full_trace():
    partial = {"overall_status": {"status": "failed"}, "intent_extraction": {"status": "failed"}}
    payload = {"pipeline_trace": partial}
    extracted = extract_pipeline_trace(payload)
    assert extracted.get("overall_status", {}).get("status") == "failed"


def test_extract_pipeline_trace_accepts_flat_persisted_trace():
    flat = {
        "trace_version": "2.0",
        "classification": {"status": "success"},
        "overall_status": {"status": "success"},
    }
    out = extract_pipeline_trace(flat)
    assert out.get("trace_version") == "2.0"
    assert "classification" in out


def test_extract_pipeline_trace_prefers_valid_over_partial_top_level():
    payload = {
        "pipeline_trace": {"overall_status": {"status": "failed"}, "root_cause": {"code": "x"}},
        "result": {"pipeline_trace": _full_trace()},
    }
    extracted = extract_pipeline_trace(payload)
    assert is_valid_trace(extracted) is True
    assert "query_execution" in extracted


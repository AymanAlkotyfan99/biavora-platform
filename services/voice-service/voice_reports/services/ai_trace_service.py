from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

MAX_TRACE_SAMPLE_ROWS = 10
ANALYTICAL_TYPES = {"analytical", "predictive", "forecast", "forecasting"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _safe_list(payload: Any) -> list[Any]:
    return payload if isinstance(payload, list) else []


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        parsed_float = int(value)
        return parsed_float if parsed_float > 0 else None

    normalized = str(value or "").strip()
    if not normalized:
        return None

    if not re.fullmatch(r"-?\d+", normalized):
        match = re.search(r"-?\d+", normalized)
        if not match:
            return None
        normalized = match.group(0)

    try:
        parsed = int(normalized)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalize_trace_stage_aliases(trace: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(trace)
    alias_map = {
        "classification": ("classification_asset", "input_validation"),
        "intent_extraction": ("intent_extraction_asset", "analytical_intent"),
        "query_execution": ("query_execution_asset",),
        "visualization": ("visualization_asset",),
        "preprocessing_low": ("preprocessing_low_asset",),
        "preprocessing_high": ("preprocessing_high_asset",),
        "routing": ("routing_asset",),
        "forecasting": ("forecasting_asset",),
    }
    for canonical, aliases in alias_map.items():
        if canonical in normalized:
            continue
        for alias in aliases:
            if alias in normalized and isinstance(normalized.get(alias), dict):
                normalized[canonical] = _safe_dict(normalized.get(alias))
                break
    return normalized


def _normalize_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"success", "completed", "done", "approved", "passed", "routed"}:
        return "success"
    if normalized in {"degraded", "fallback", "partial"}:
        return "degraded"
    if normalized in {"failed", "error", "rejected"}:
        return "error"
    if normalized in {"skipped", "not_started", "pending", "unknown", ""}:
        return "skipped"
    return "warning"


def _sample_rows(rows: Any, limit: int = MAX_TRACE_SAMPLE_ROWS) -> list[dict[str, Any]]:
    sampled: list[dict[str, Any]] = []
    for row in _safe_list(rows)[: max(1, min(limit, MAX_TRACE_SAMPLE_ROWS))]:
        if isinstance(row, dict):
            sampled.append(row)
    return sampled


def _extract_stage(trace: dict[str, Any], stage_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    stage_payload = _safe_dict(trace.get(stage_name))
    final_output = _safe_dict(stage_payload.get("final_output"))
    return stage_payload, final_output


def _extract_stage_any(trace: dict[str, Any], stage_names: list[str]) -> tuple[dict[str, Any], dict[str, Any], bool]:
    for stage_name in stage_names:
        if stage_name not in trace:
            continue
        stage_payload = _safe_dict(trace.get(stage_name))
        final_output = _safe_dict(stage_payload.get("final_output"))
        return stage_payload, final_output, True
    return {}, {}, False


def _status_from_stage(*, stage_payload: dict[str, Any], stage_exists: bool) -> str:
    if not stage_exists:
        return "skipped"
    normalized = _normalize_status(stage_payload.get("status") or "success")
    if normalized == "degraded":
        return "degraded"
    # Dagster asset exists => never surface as skipped in AI trace.
    return "success"


def _normalize_question_type(
    intent_json: dict[str, Any],
    classification_final: dict[str, Any],
    routing_final: dict[str, Any],
    forecasting_payload: dict[str, Any],
) -> str:
    candidates = [
        intent_json.get("question_type"),
        classification_final.get("question_type"),
        classification_final.get("classification"),
        routing_final.get("intent_type"),
        routing_final.get("next_step"),
    ]
    normalized_candidates = [str(candidate or "").strip().lower() for candidate in candidates]
    if any(candidate in {"predictive", "forecast", "forecasting"} for candidate in normalized_candidates):
        return "predictive"
    if any(candidate == "analytical" for candidate in normalized_candidates):
        return "analytical"
    if any(candidate in {"conversational", "informational", "invalid_input", "noise_input", "empty_input"} for candidate in normalized_candidates):
        return "non_analytical"

    if forecasting_payload.get("enabled") and forecasting_payload.get("request", {}).get("requires_forecast"):
        return "predictive"

    return "analytical" if intent_json else "non_analytical"


def _extract_forecasting(
    *,
    chart_config: dict[str, Any],
    query_result: dict[str, Any],
    question_type: str,
) -> dict[str, Any] | None:
    forecasting_payload = _safe_dict(chart_config.get("forecasting"))
    request_payload = _safe_dict(forecasting_payload.get("request"))
    meta_payload = _safe_dict(forecasting_payload.get("meta"))
    error_payload = _safe_dict(forecasting_payload.get("error"))

    requires_forecast = bool(
        request_payload.get("requires_forecast")
        or question_type == "predictive"
    )

    if not requires_forecast:
        return None

    rows = _safe_list(query_result.get("rows"))
    actual_rows = [row for row in rows if isinstance(row, dict) and row.get("series_type") == "actual"]
    forecast_rows = [row for row in rows if isinstance(row, dict) and row.get("series_type") == "forecast"]

    frequency_seconds = _coerce_positive_int(meta_payload.get("frequency_seconds"))
    granularity = ""
    if frequency_seconds is not None:
        if frequency_seconds % 86400 == 0:
            days = frequency_seconds // 86400
            granularity = "daily" if days == 1 else f"{days}-day"
        elif frequency_seconds % 3600 == 0:
            hours = frequency_seconds // 3600
            granularity = "hourly" if hours == 1 else f"{hours}-hour"
        else:
            granularity = f"{frequency_seconds}-second"

    horizon = _coerce_positive_int(meta_payload.get("horizon"))
    if horizon is None:
        horizon = _coerce_positive_int(request_payload.get("horizon"))

    status = str(forecasting_payload.get("status") or "skipped").strip().lower()
    normalized_status = "success" if status == "success" else ("failed" if status == "failed" else "skipped")

    validation_notes: list[str] = []
    if normalized_status == "failed":
        message = str(error_payload.get("message") or "").strip()
        code = str(error_payload.get("code") or "").strip()
        if message:
            validation_notes.append(message)
        if code:
            validation_notes.append(f"code: {code}")
        details = _safe_dict(error_payload.get("details"))
        if details:
            validation_notes.append(f"details: {details}")

    return {
        "requires_forecast": True,
        "forecast_status": normalized_status,
        "fallback": str(forecasting_payload.get("fallback") or ""),
        "reason": str(forecasting_payload.get("reason") or ""),
        "detected_time_column": str(meta_payload.get("time_column") or ""),
        "detected_value_column": str(meta_payload.get("value_column") or ""),
        "horizon": horizon,
        "granularity": granularity,
        "validation_notes": validation_notes,
        "model_used": "TimesFM",
        "historical_series_sample": _sample_rows(actual_rows),
        "forecast_output_sample": _sample_rows(forecast_rows),
        "merged_dataset_sample": _sample_rows(rows),
    }


def _collect_errors(
    *,
    trace: dict[str, Any],
    report_error_message: str,
    forecasting_trace: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    stage_names = [
        "classification",
        "input_validation",
        "preprocessing_low",
        "routing",
        "preprocessing_high",
        "intent_extraction",
        "predictive_intent",
        "sql_generation",
        "sql_review",
        "query_execution",
        "forecasting",
        "visualization",
    ]
    for stage_name in stage_names:
        stage_payload = _safe_dict(trace.get(stage_name))
        for error in _safe_list(stage_payload.get("errors")):
            if not isinstance(error, dict):
                continue
            collected.append(
                {
                    "stage": stage_name,
                    "message": str(error.get("message") or "Unknown error").strip(),
                    "type": str(error.get("type") or "unknown").strip(),
                    "fallback_applied": False,
                }
            )

    if forecasting_trace and forecasting_trace.get("forecast_status") == "failed":
        notes = _safe_list(forecasting_trace.get("validation_notes"))
        collected.append(
            {
                "stage": "forecasting",
                "message": str(notes[0] if notes else "Forecasting failed").strip(),
                "type": "forecasting_error",
                "fallback_applied": True,
            }
        )

    normalized_error_message = str(report_error_message or "").strip()
    lowered_error_message = normalized_error_message.lower()
    looks_like_error = any(
        token in lowered_error_message
        for token in ("error", "failed", "failure", "exception", "timeout", "unavailable", "invalid")
    )
    if normalized_error_message and looks_like_error:
        collected.append(
            {
                "stage": "execution",
                "message": normalized_error_message,
                "type": "runtime_error",
                "fallback_applied": False,
            }
        )

    return collected


def _extract_preprocessing_corrections(preprocess_high: dict[str, Any]) -> list[dict[str, str]]:
    explicit = _safe_list(preprocess_high.get("term_corrections"))
    normalized: list[dict[str, str]] = []

    for item in explicit:
        if not isinstance(item, dict):
            continue
        source = str(item.get("from") or item.get("source") or "").strip()
        target = str(item.get("to") or item.get("target") or "").strip()
        if not source or not target or source == target:
            continue
        normalized.append({"from": source, "to": target, "type": str(item.get("type") or "").strip()})

    if normalized:
        return normalized

    for item in _safe_list(preprocess_high.get("term_resolutions")):
        if not isinstance(item, dict):
            continue
        status = str(item.get("resolution_status") or "").strip().lower()
        if status not in {"corrected_typo", "semantic_match"}:
            continue
        source = str(item.get("term") or "").strip()
        target = str(item.get("matched_column") or "").strip()
        if not source or not target or source == target:
            continue
        normalized.append({"from": source, "to": target, "type": status})

    return normalized


def _build_chart_decision_trace(
    *,
    chart_type: str,
    chart_config: dict[str, Any],
    visualization_stage: dict[str, Any],
) -> dict[str, Any]:
    canonical_contract = _safe_dict(chart_config.get("chart_contract"))
    upstream_chart = str(
        canonical_contract.get("type")
        or canonical_contract.get("final_chart_type")
        or canonical_contract.get("chart_type")
        or chart_config.get("upstream_chart_type")
        or chart_config.get("selected_chart_type")
        or chart_config.get("chart_type")
        or ""
    ).strip().lower()
    final_chart = str(
        canonical_contract.get("type")
        or canonical_contract.get("final_chart_type")
        or chart_type
        or chart_config.get("chart_type")
        or "table"
    ).strip().lower() or "table"
    chart_locked = bool(chart_config.get("chart_locked"))
    explicit_chart_lock = bool(chart_config.get("explicit_chart_lock") or chart_locked)
    overwritten_by = str(chart_config.get("overwritten_by") or "").strip()
    fallback_reason = str(chart_config.get("fallback_reason") or "").strip()
    reason = str(chart_config.get("reason_chart_selected") or "").strip() or "chart_selected"
    overwritten = bool(overwritten_by) or (bool(upstream_chart) and upstream_chart != final_chart)

    decision_chain = []
    decision_chain.append(
        {
            "stage": "ai-service",
            "chart": upstream_chart or final_chart,
            "action": "selected",
            "reason": "user_explicit_request" if explicit_chart_lock else "model_selection",
        }
    )
    if overwritten:
        decision_chain.append(
            {
                "stage": overwritten_by or "report-service",
                "chart": final_chart,
                "action": "overridden",
                "reason": fallback_reason or reason or "shape_fallback",
            }
        )
    else:
        decision_chain.append(
            {
                "stage": "report-service",
                "chart": final_chart,
                "action": "preserved",
                "reason": "explicit_chart_preserved" if explicit_chart_lock else reason,
            }
        )
    decision_chain.append(
        {
            "stage": "visualization-service",
            "chart": final_chart,
            "action": "sent_to_metabase",
            "reason": str(_safe_dict(visualization_stage.get("final_output")).get("reason_chart_selected") or "final_validated_chart"),
        }
    )
    return {
        "upstream_chart": upstream_chart or final_chart,
        "initial_selected_chart": upstream_chart or final_chart,
        "final_chart": final_chart,
        "chart_locked": chart_locked,
        "explicit_chart_lock": explicit_chart_lock,
        "overwritten": overwritten,
        "overwritten_by": overwritten_by if overwritten else "",
        "reason": reason if overwritten else "explicit_chart_preserved",
        "fallback_reason": fallback_reason,
        "downgrade_reason": str(chart_config.get("downgrade_reason") or "").strip(),
        "decision_chain": decision_chain,
    }


def build_ai_trace_payload(
    *,
    report_id: int | None,
    transcription: str,
    preprocessing_low: dict[str, Any] | None,
    preprocessing_high: dict[str, Any] | None,
    intent_json: dict[str, Any] | None,
    pipeline_trace: dict[str, Any] | None,
    generated_sql: str,
    reviewed_sql: str,
    query_result: dict[str, Any] | None,
    execution_time_ms: int | None,
    row_count: int | None,
    chart_type: str,
    metabase_question_id: int | None,
    metabase_dashboard_id: int | None,
    embed_url: str,
    chart_config: dict[str, Any] | None,
    error_message: str,
) -> dict[str, Any]:
    normalized_pre_low = _safe_dict(preprocessing_low)
    normalized_pre_high = _safe_dict(preprocessing_high)
    normalized_intent = _safe_dict(intent_json)
    normalized_trace = _normalize_trace_stage_aliases(_safe_dict(pipeline_trace))
    normalized_result = _safe_dict(query_result)
    normalized_chart_config = _safe_dict(chart_config)

    classification_stage, classification_final, classification_exists = _extract_stage_any(
        normalized_trace, ["classification_asset", "classification", "input_validation"]
    )
    intent_stage, intent_final, intent_exists = _extract_stage_any(
        normalized_trace, ["intent_extraction_asset", "intent_extraction", "analytical_intent"]
    )
    routing_stage, routing_final, _ = _extract_stage_any(normalized_trace, ["routing_asset", "routing"])
    pre_low_stage, _, pre_low_exists = _extract_stage_any(normalized_trace, ["preprocessing_low_asset", "preprocessing_low"])
    pre_high_stage, pre_high_final, pre_high_exists = _extract_stage_any(
        normalized_trace, ["preprocessing_high_asset", "preprocessing_high"]
    )
    predictive_stage, predictive_final = _extract_stage(normalized_trace, "predictive_intent")
    sql_generation_stage, sql_generation_final, _ = _extract_stage_any(
        normalized_trace, ["query_execution_asset", "sql_generation"]
    )
    sql_review_stage, sql_review_final = _extract_stage(normalized_trace, "sql_review")
    query_execution_stage, query_execution_final, query_execution_exists = _extract_stage_any(
        normalized_trace, ["query_execution_asset", "query_execution"]
    )
    visualization_stage, visualization_final, visualization_exists = _extract_stage_any(
        normalized_trace, ["visualization_asset", "visualization"]
    )
    forecasting_stage, _, forecasting_exists = _extract_stage_any(
        normalized_trace, ["forecasting_asset", "forecasting"]
    )

    question_type = _normalize_question_type(
        normalized_intent,
        classification_final,
        routing_final,
        _safe_dict(normalized_chart_config.get("forecasting")),
    )
    requires_forecast = bool(
        classification_final.get("requires_forecast")
        or normalized_intent.get("requires_forecast")
        or str(routing_final.get("next_step") or "").strip().lower() == "forecasting"
        or question_type == "predictive"
    )
    if requires_forecast:
        question_type = "predictive"
    is_analytical = question_type in {"analytical", "predictive"}
    preprocessing_high_status = _status_from_stage(stage_payload=pre_high_stage, stage_exists=pre_high_exists)
    preprocessing_high_failed = preprocessing_high_status == "error"

    extracted_intent = _safe_dict(intent_final.get("extracted_intent")) or normalized_intent
    validated_intent = _safe_dict(intent_final.get("validated_intent"))
    intent_type_for_trace = str(
        routing_final.get("intent_type")
        or intent_final.get("intent_type")
        or normalized_intent.get("intent_type")
        or normalized_intent.get("question_type")
        or ""
    ).strip().lower()
    if not intent_type_for_trace:
        intent_type_for_trace = "predictive" if requires_forecast else "analytical"
    elif requires_forecast and intent_type_for_trace not in {"predictive", "forecast", "forecasting"}:
        intent_type_for_trace = "predictive"

    columns = [str(column) for column in _safe_list(normalized_result.get("columns")) if str(column).strip()]
    rows = _safe_list(normalized_result.get("rows"))
    sampled_rows = _sample_rows(rows)
    normalized_row_count = int(row_count or len(rows))
    timeseries_diagnostics = _safe_dict(normalized_chart_config.get("timeseries_diagnostics"))

    forecasting_trace = _extract_forecasting(
        chart_config=normalized_chart_config,
        query_result=normalized_result,
        question_type=question_type,
    )

    sql_review_notes = sql_review_final.get("sql_review_notes")
    if not isinstance(sql_review_notes, list):
        sql_review_notes = _safe_list(_safe_dict(sql_review_final.get("sql_review")).get("notes"))
    sql_review_notes = [str(note) for note in sql_review_notes if str(note).strip()]
    preprocessing_corrections = _extract_preprocessing_corrections(normalized_pre_high)
    classification_status = _status_from_stage(stage_payload=classification_stage, stage_exists=classification_exists)
    classifier_called = classification_exists or bool(classification_stage) or bool(classification_final)
    classification_error = classification_status == "error"
    # If high preprocessing completed (including deferred/degraded recovery), avoid surfacing
    # stale classification errors as final failures.
    if preprocessing_high_status in {"success", "degraded"}:
        classification_error = False

    chart_decision_trace = _build_chart_decision_trace(
        chart_type=chart_type,
        chart_config=normalized_chart_config,
        visualization_stage=visualization_stage,
    )

    trace = {
        "report_id": report_id,
        "stage_order": [
            "original_question",
            "preprocessing_low",
            "classification",
            "preprocessing_high",
            "intent_extraction",
            "sql_generation",
            "execution",
            "visualization",
        ],
        "original_question": {
            "text": str(transcription or ""),
            "status": "success",
        },
        "preprocessing_low": {
            "status": _status_from_stage(stage_payload=pre_low_stage, stage_exists=pre_low_exists),
            "original_text": str(normalized_pre_low.get("original_text") or transcription or ""),
            "cleaned_text": str(normalized_pre_low.get("cleaned_text") or transcription or ""),
            "spelling_corrected_text": str(normalized_pre_low.get("spelling_corrected_text") or ""),
            "spelling_changes": _safe_list(normalized_pre_low.get("spelling_changes")),
            "has_spelling_correction": bool(normalized_pre_low.get("has_spelling_correction")),
            "removed_filler_words": _safe_list(normalized_pre_low.get("removed_filler_words")),
            "detected_changes": _safe_list(normalized_pre_low.get("changes") or normalized_pre_low.get("detected_changes")),
        },
        "classification": {
            "status": classification_status,
            "is_analytical": bool(is_analytical),
            "is_predictive": bool(question_type == "predictive"),
            "error": classification_error,
            "error_reason": str(
                classification_stage.get("message")
                or classification_final.get("message")
                or (pre_high_stage.get("message") if preprocessing_high_failed else "")
                or (pre_high_final.get("message") if preprocessing_high_failed else "")
                or ""
            ),
            "question_type": question_type,
            "requires_forecast": requires_forecast,
            "type": str(
                classification_final.get("type")
                or classification_final.get("classification_type")
                or ""
            ),
            "confidence": classification_final.get("confidence") or normalized_intent.get("confidence") or None,
            "reasoning": str(
                classification_final.get("reasoning")
                or classification_final.get("reason")
                or classification_final.get("message")
                or normalized_intent.get("classification_reason")
                or ""
            ),
            "raw_model_response": str(
                classification_final.get("raw_model_response")
                or _safe_dict(classification_stage.get("debug_metadata")).get("raw_model_response")
                or _safe_dict(classification_stage.get("debug_metadata")).get("raw_classifier_output")
                or ""
            ),
        },
        "routing": {
            "status": _normalize_status(routing_stage.get("status") or "unknown"),
            "route": str(
                routing_final.get("classification_route")
                or _safe_dict(normalized_pre_high.get("routing_decision")).get("route")
                or ("forecasting" if question_type == "predictive" else "analytical")
            ),
            "next_step": str(routing_final.get("next_step") or ""),
            "reason": str(routing_final.get("route_reason") or routing_final.get("reason") or ""),
            "fallback_route": str(routing_final.get("fallback_route") or ""),
            "message": str(_safe_dict(routing_stage).get("message") or ""),
        },
        "preprocessing_high": {
            "status": preprocessing_high_status,
            "corrected_query": str(normalized_pre_high.get("corrected_query") or normalized_pre_high.get("final_query") or ""),
            "corrections": preprocessing_corrections,
            "term_corrections": _safe_list(normalized_pre_high.get("term_corrections")),
            "skipped_schema_terms": _safe_list(normalized_pre_high.get("skipped_schema_terms")),
            "schema_used": _safe_dict(normalized_pre_high.get("schema_used")),
            "selected_table": str(normalized_pre_high.get("selected_table") or ""),
            "selected_columns": [
                str(column)
                for column in _safe_list(normalized_pre_high.get("selected_columns"))
                if str(column).strip()
            ],
            "routing_decision": _safe_dict(normalized_pre_high.get("routing_decision")),
            "skipped_reason": (
                "predictive_route_selected"
                if question_type == "predictive"
                else str(pre_high_stage.get("message") or "")
            ),
            "user_friendly_messages": _safe_list(normalized_pre_high.get("user_friendly_messages")),
        },
        "predictive_intent": {
            "status": (
                _normalize_status(predictive_stage.get("status") or intent_stage.get("status") or "unknown")
                if question_type == "predictive"
                else "skipped"
            ),
            "intent_type": str(
                predictive_final.get("intent_type")
                or intent_final.get("intent_type")
                or normalized_intent.get("intent_type")
                or ""
            ),
            "metric": str(
                predictive_final.get("metric")
                or extracted_intent.get("metric")
                or validated_intent.get("metric")
                or ""
            ),
            "time_column": str(
                predictive_final.get("time_column")
                or extracted_intent.get("time_column")
                or validated_intent.get("time_column")
                or ""
            ),
            "horizon": (
                predictive_final.get("horizon")
                or extracted_intent.get("horizon")
                or extracted_intent.get("forecast_horizon")
            ),
            "granularity": str(
                predictive_final.get("granularity")
                or extracted_intent.get("granularity")
                or ""
            ),
            "skipped_reason": "" if question_type == "predictive" else "analytical_route_selected",
        },
        "intent_extraction": {
            "status": _status_from_stage(stage_payload=intent_stage, stage_exists=intent_exists),
            "intent_type": intent_type_for_trace,
            "extracted_intent": extracted_intent,
            "validated_intent": validated_intent,
            "operations": _safe_list(extracted_intent.get("operations") or validated_intent.get("operations")),
            "columns": _safe_list(extracted_intent.get("columns") or validated_intent.get("columns")),
            "time_range": _safe_dict(extracted_intent.get("time_range") or validated_intent.get("time_range")),
            "routing_decision": {
                "next_step": str(routing_final.get("next_step") or ""),
                "reason": str(routing_final.get("route_reason") or routing_final.get("reason") or ""),
                "fallback_route": str(routing_final.get("fallback_route") or ""),
            },
            "ambiguities": _safe_list(validated_intent.get("ambiguities")),
        },
        "sql_generation": {
            "status": _status_from_stage(
                stage_payload=(sql_review_stage or sql_generation_stage),
                stage_exists=query_execution_exists,
            ),
            "generated_sql": str(generated_sql or sql_generation_final.get("generated_sql") or ""),
            "reviewed_sql": str(reviewed_sql or sql_review_final.get("reviewed_sql") or ""),
            "sql": str(
                reviewed_sql
                or generated_sql
                or query_execution_final.get("sql")
                or sql_generation_final.get("sql")
                or ""
            ),
            "row_count": normalized_row_count,
            "execution_time_ms": int(execution_time_ms or 0) if execution_time_ms is not None else None,
            "sql_review_notes": sql_review_notes,
            "historical_sql_only": bool(_safe_dict(sql_generation_final).get("historical_sql_only")),
        },
        "execution": {
            "status": _status_from_stage(stage_payload=query_execution_stage, stage_exists=query_execution_exists),
            "execution_time_ms": int(execution_time_ms or 0) if execution_time_ms is not None else None,
            "row_count": normalized_row_count,
            "columns": columns,
            "sample_rows": sampled_rows,
            "timeseries_profile": {
                "min_ds": str(timeseries_diagnostics.get("min_ds") or ""),
                "max_ds": str(timeseries_diagnostics.get("max_ds") or ""),
                "detected_granularity": str(timeseries_diagnostics.get("detected_granularity") or ""),
                "series_type_counts": _safe_dict(timeseries_diagnostics.get("series_type_counts")),
                "first_10_rows_sorted": _sample_rows(timeseries_diagnostics.get("first_10_rows_sorted"), limit=10),
                "last_10_rows_sorted": _sample_rows(timeseries_diagnostics.get("last_10_rows_sorted"), limit=10),
            },
        },
        "visualization": {
            "status": _status_from_stage(stage_payload=visualization_stage, stage_exists=visualization_exists),
            "chart_type": str(
                _safe_dict(normalized_chart_config.get("chart_contract")).get("type")
                or _safe_dict(normalized_chart_config.get("chart_contract")).get("chart_type")
                or chart_type
                or visualization_final.get("selected_chart_type")
                or ""
            ),
            "metabase_question_id": metabase_question_id,
            "render_status": str(normalized_chart_config.get("render_status") or ""),
            "contract_preserved": bool(normalized_chart_config.get("contract_preserved", False)),
            "metabase_dashboard_id": metabase_dashboard_id,
            "embed_url": str(embed_url or ""),
            "config": {
                "metabase_display": str(timeseries_diagnostics.get("metabase_display") or ""),
                "semantic_chart_type": str(normalized_chart_config.get("semantic_chart_type") or ""),
                "renderer_chart_type": str(normalized_chart_config.get("renderer_chart_type") or ""),
                "histogram_strategy": str(normalized_chart_config.get("histogram_strategy") or ""),
                "metric_column": str(normalized_chart_config.get("metric_column") or ""),
                "bucket_column": str(normalized_chart_config.get("bucket_column") or ""),
                "frequency_column": str(normalized_chart_config.get("frequency_column") or ""),
                "bin_size": normalized_chart_config.get("bin_size"),
                "bins_count": normalized_chart_config.get("bins_count"),
                "graph_dimensions": _safe_list(timeseries_diagnostics.get("graph_dimensions")),
                "graph_metrics": _safe_list(timeseries_diagnostics.get("graph_metrics")),
                "graph_breakout": _safe_list(timeseries_diagnostics.get("graph_breakout")),
            },
        },
        "chart_decision_trace": chart_decision_trace,
        "upstream_chart": chart_decision_trace.get("upstream_chart", ""),
        "final_chart": chart_decision_trace.get("final_chart", ""),
        "chart_locked": bool(chart_decision_trace.get("chart_locked", False)),
        "overwritten": bool(chart_decision_trace.get("overwritten", False)),
        "overwritten_by": chart_decision_trace.get("overwritten_by", ""),
        "fallback_reason": chart_decision_trace.get("fallback_reason", ""),
        "downgrade_reason": chart_decision_trace.get("downgrade_reason", ""),
        "errors": [],
        "meta": {
            "sample_limit": MAX_TRACE_SAMPLE_ROWS,
            "generated_at": _now_iso(),
        },
    }

    if forecasting_trace:
        forecasting_trace["forecast_status"] = _status_from_stage(
            stage_payload=forecasting_stage,
            stage_exists=forecasting_exists,
        )
        trace["forecasting"] = forecasting_trace

    trace["errors"] = _collect_errors(
        trace=normalized_trace,
        report_error_message=error_message,
        forecasting_trace=forecasting_trace,
    )

    return trace

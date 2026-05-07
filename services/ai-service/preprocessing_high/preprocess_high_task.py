from __future__ import annotations

import json
import logging
import re
import time
from difflib import get_close_matches
from datetime import datetime, timezone

try:
    from rapidfuzz import fuzz, process as rapidfuzz_process
except ImportError:  # pragma: no cover - optional dependency
    fuzz = None
    rapidfuzz_process = None

from preprocessing_high.diagnostics import build_schema_resolution_diagnostics
from preprocessing_high.error_handler import (
    PreprocessHighInputError,
    PreprocessHighMissingColumnError,
    classify_preprocess_high_error,
    decide_preprocess_high_action,
)
from preprocessing_high.llm_client import (
    FORECAST_RESERVED_TERMS,
    build_deterministic_schema_validation_result,
    correct_query_terms,
    validate_query_schema_usage,
)
from preprocessing_high.schema_loader import load_user_schema
from preprocessing_high.schemas import (
    HighPreprocessConfig,
    PreprocessHighResult,
    build_preprocess_high_failed_result,
    build_preprocess_high_rejected_result,
    build_preprocess_high_success_result,
)
from shared.analytical_time_semantics import question_requests_analytical_time
from shared.confidence import schema_confidence
from shared.pipeline_trace import make_attempt
from shared.schema_utils import is_date_type, is_numeric_type
from shared.time_semantics_detector import extract_longest_time_keyword


# Phase 5 / CRIT-14: forecasting must NEVER skip schema validation. The
# orchestrator surfaces ``forecast_missing_time_column`` /
# ``forecast_missing_target_column`` when a forecast question hits a dataset
# that lacks a Date/DateTime column or a numeric target column.
FORECAST_MISSING_TIME_COLUMN = "forecast_missing_time_column"
FORECAST_MISSING_TARGET_COLUMN = "forecast_missing_target_column"
FORECAST_TIME_COLUMN_CANDIDATES = (
    "ds",
    "date",
    "datetime",
    "timestamp",
    "time",
    "created_at",
    "updated_at",
    "order_date",
    "sales_date",
)


def _resolve_forecast_columns(
    *,
    loaded_schema,
    dataset_scope: dict[str, object] | None,
    query_text: str = "",
) -> tuple[str, str, str]:
    """Resolve the forecast date/target columns from the loaded schema.

    Returns ``(table, forecast_date_column, forecast_target_column)``. If a
    bound ``dataset_scope.table_name`` is provided we restrict the search to
    that table; otherwise we scan every table the schema exposes.
    """

    columns_obj = loaded_schema.schema.get("columns", {}) if loaded_schema is not None else {}
    if not isinstance(columns_obj, dict):
        return "", "", ""

    bound_table = ""
    if isinstance(dataset_scope, dict):
        bound_table = str(dataset_scope.get("table_name", "")).strip()

    candidates: list[tuple[str, list[dict[str, object]]]] = []
    if bound_table:
        bound_columns = columns_obj.get(bound_table)
        if not bound_columns:
            for table_name, table_columns in columns_obj.items():
                if str(table_name).split(".")[-1].lower() == bound_table.split(".")[-1].lower():
                    bound_columns = table_columns
                    bound_table = str(table_name)
                    break
        if isinstance(bound_columns, list):
            candidates.append((bound_table, bound_columns))
    else:
        for table_name, table_columns in columns_obj.items():
            if isinstance(table_columns, list):
                candidates.append((str(table_name), table_columns))

    query_tokens = set(re.findall(r"[a-z0-9_]+", str(query_text or "").lower()))

    for table_name, table_columns in candidates:
        date_column = ""
        target_column = ""
        scored_targets: list[tuple[int, str]] = []
        for col in table_columns:
            if not isinstance(col, dict):
                continue
            name = str(col.get("name", "")).strip()
            col_type = str(col.get("type", "")).strip()
            if not name:
                continue
            lowered_name = name.lower()
            if not date_column and (
                lowered_name in FORECAST_TIME_COLUMN_CANDIDATES
                or is_date_type(col_type)
            ):
                date_column = name
            if is_numeric_type(col_type) and not lowered_name.startswith("_"):
                score = 0
                if lowered_name in {"orders", "order_count", "total_sales", "sales", "revenue"}:
                    score += 4
                if lowered_name in query_tokens:
                    score += 3
                if any(token in lowered_name for token in query_tokens):
                    score += 1
                scored_targets.append((score, name))
        if scored_targets:
            scored_targets.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
            target_column = scored_targets[0][1]
        if date_column and target_column:
            return table_name, date_column, target_column
        if date_column and not target_column:
            # Date present but no numeric target is still a "missing target" failure.
            return table_name, date_column, ""

    if candidates:
        # Date column missing on the only/bound dataset: communicate this as
        # missing_time_column so the orchestrator can render a precise message.
        table_name = candidates[0][0]
        return table_name, "", ""
    return "", "", ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_logger() -> logging.Logger:
    return logging.getLogger(__name__)


def _log_event(logger: logging.Logger, level: int, message: str, **fields: object) -> None:
    payload = {"timestamp": _utc_now(), **fields}
    logger.log(level, "%s | %s", message, json.dumps(payload, sort_keys=True, default=str))


def _validate_inputs(cleaned_text: str, user_id: str) -> tuple[str, str]:
    normalized_text = str(cleaned_text or "").strip()
    if not normalized_text:
        raise PreprocessHighInputError("cleaned_text is empty.")

    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        raise PreprocessHighInputError("user_id is empty.")

    return normalized_text, normalized_user_id


def _extract_skipped_forecast_terms(query: str) -> list[str]:
    lowered = str(query or "").lower()
    found = []
    for term in sorted(FORECAST_RESERVED_TERMS):
        if not term:
            continue
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            found.append(term)
    return found


def _recommended_columns_text(schema: dict[str, object] | None) -> str:
    if not isinstance(schema, dict):
        return "Use existing table/column names from the current dataset schema."
    columns_obj = schema.get("columns", {})
    if not isinstance(columns_obj, dict):
        return "Use existing table/column names from the current dataset schema."
    all_columns: list[str] = []
    for table_columns in columns_obj.values():
        if not isinstance(table_columns, list):
            continue
        for column in table_columns:
            if not isinstance(column, dict):
                continue
            name = str(column.get("name", "")).strip()
            if name:
                all_columns.append(name)
    unique_columns = sorted(set(all_columns))
    if not unique_columns:
        return "Use existing table/column names from the current dataset schema."
    preview = ", ".join(unique_columns[:12])
    suffix = "..." if len(unique_columns) > 12 else ""
    return f"Use only existing schema columns ({preview}{suffix})."


_SCHEMA_CORRECTION_STOP_WORDS = {
    "how",
    "what",
    "where",
    "when",
    "why",
    "who",
    "do",
    "is",
    "are",
    "the",
    "a",
    "an",
    "of",
    "by",
    "for",
    "to",
    "in",
    "on",
    "with",
    "and",
    "or",
    "show",
    "give",
    "list",
    "many",
    "much",
    "per",
    "over",
    "under",
    "between",
    "from",
}

_BUSINESS_TERM_NORMALIZATION = {
    "impact": "relationship",
    "effect": "relationship",
    "influence": "relationship",
    "relation": "relationship",
}

_TIME_SEMANTICS_IN_PHRASE = re.compile(
    r"\bover\s+time\b|\btrend(s)?\b|\bby\s+date\b|\bby\s+day\b|\bdaily\b|\bweekly\b|\bmonthly\b|\bquarterly\b"
    r"|\b(per|by)\s+(day|week|month|quarter|year)\b|\bper\s+day\b|\bper\s+week\b|\bper\s+month\b|\bper\s+quarter\b|\bper\s+year\b",
    re.I,
)

_PROTECTED_SCHEMA_FUZZY_TOKENS = frozenset(
    {"time", "daily", "weekly", "monthly", "quarterly", "yearly", "trend", "trends", "annual", "annually"}
)


def _attach_intent_query_metadata(payload: dict[str, object], *, original_text: str, final_text: str) -> None:
    orig = str(original_text or "").strip()
    fin = str(final_text or "").strip()
    payload["original_query_for_intent"] = orig
    if question_requests_analytical_time(orig) and not question_requests_analytical_time(fin):
        payload["time_semantics_detected"] = True
        payload["time_phrase"] = extract_longest_time_keyword(orig) or "time_series"
    else:
        payload.setdefault("time_semantics_detected", False)
        payload.setdefault("time_phrase", "")


def _schema_token_vocabulary(loaded_schema) -> set[str]:
    vocabulary: set[str] = set()
    columns_obj = loaded_schema.schema.get("columns", {})
    if not isinstance(columns_obj, dict):
        return vocabulary

    for table_columns in columns_obj.values():
        if not isinstance(table_columns, list):
            continue
        for column in table_columns:
            if not isinstance(column, dict):
                continue
            column_name = str(column.get("name", "")).strip().lower()
            if not column_name:
                continue
            vocabulary.add(column_name)
            for token in re.findall(r"[a-z0-9]+", column_name.replace("_", " ")):
                if len(token) > 1:
                    vocabulary.add(token)
    return vocabulary


def _schema_column_phrase_lookup(loaded_schema) -> dict[str, str]:
    phrase_lookup: dict[str, str] = {}
    columns_obj = loaded_schema.schema.get("columns", {})
    if not isinstance(columns_obj, dict):
        return phrase_lookup

    for table_columns in columns_obj.values():
        if not isinstance(table_columns, list):
            continue
        for column in table_columns:
            if not isinstance(column, dict):
                continue
            raw_column_name = str(column.get("name", "")).strip().lower()
            if not raw_column_name:
                continue
            canonical = raw_column_name
            aliases = {
                canonical,
                canonical.replace("_", " "),
                re.sub(r"[^a-z0-9]+", " ", canonical).strip(),
            }
            for alias in aliases:
                normalized = re.sub(r"\s+", " ", alias).strip()
                if not normalized:
                    continue
                phrase_lookup.setdefault(normalized, canonical)
    return phrase_lookup


def _best_fuzzy_candidate(term: str, candidates: list[str]) -> tuple[str, float]:
    normalized_term = str(term or "").strip().lower()
    if not normalized_term or not candidates:
        return "", 0.0

    if rapidfuzz_process is not None and fuzz is not None:
        scored = rapidfuzz_process.extract(
            normalized_term,
            candidates,
            scorer=fuzz.WRatio,
            limit=2,
        )
        if not scored:
            return "", 0.0
        best_term, best_score, _ = scored[0]
        second_score = scored[1][1] if len(scored) > 1 else 0.0
        if best_score < 88 or (best_score - second_score) < 5:
            return "", 0.0
        return str(best_term), float(best_score)

    matches = get_close_matches(normalized_term, candidates, n=1, cutoff=0.84)
    if not matches:
        return "", 0.0
    return matches[0], 84.0


def _apply_fuzzy_phrase_corrections(
    *,
    query: str,
    loaded_schema,
    ignored_terms: set[str] | None = None,
    target_terms: set[str] | None = None,
) -> tuple[str, list[dict[str, str]]]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return normalized_query, []

    ignored = {str(term).strip().lower() for term in (ignored_terms or set()) if str(term).strip()}
    targets = {str(term).strip().lower() for term in (target_terms or set()) if str(term).strip()}
    phrase_lookup = _schema_column_phrase_lookup(loaded_schema)
    phrase_candidates = sorted(
        phrase for phrase in phrase_lookup.keys() if phrase and phrase not in _SCHEMA_CORRECTION_STOP_WORDS
    )
    if not phrase_candidates:
        return normalized_query, []

    working_query = normalized_query
    corrections: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    query_tokens = re.findall(r"[A-Za-z0-9_]+", normalized_query)

    max_span = min(3, len(query_tokens))
    for span in range(max_span, 0, -1):
        for index in range(0, len(query_tokens) - span + 1):
            phrase_tokens = query_tokens[index : index + span]
            candidate_phrase = " ".join(token.lower() for token in phrase_tokens).strip()
            if (
                not candidate_phrase
                or len(candidate_phrase) <= 2
                or candidate_phrase in ignored
                or candidate_phrase in _SCHEMA_CORRECTION_STOP_WORDS
                or candidate_phrase in _BUSINESS_TERM_NORMALIZATION
            ):
                continue
            if phrase_tokens and (
                phrase_tokens[0].lower() in _SCHEMA_CORRECTION_STOP_WORDS
                or phrase_tokens[-1].lower() in _SCHEMA_CORRECTION_STOP_WORDS
            ):
                continue
            if targets and candidate_phrase not in targets:
                continue
            if all(token.lower() in _SCHEMA_CORRECTION_STOP_WORDS for token in phrase_tokens):
                continue
            if _TIME_SEMANTICS_IN_PHRASE.search(f" {candidate_phrase} "):
                continue

            best_phrase, _ = _best_fuzzy_candidate(candidate_phrase, phrase_candidates)
            if not best_phrase:
                continue
            canonical_column = phrase_lookup.get(best_phrase, "")
            if not canonical_column:
                continue
            if canonical_column == candidate_phrase:
                continue

            replacement_pattern = re.compile(rf"\b{re.escape(' '.join(phrase_tokens))}\b", flags=re.IGNORECASE)
            if not replacement_pattern.search(working_query):
                continue
            working_query = replacement_pattern.sub(canonical_column, working_query, count=1)
            correction_key = (candidate_phrase, canonical_column)
            if correction_key in seen_pairs:
                continue
            seen_pairs.add(correction_key)
            corrections.append(
                {
                    "type": "fuzzy_phrase",
                    "from": candidate_phrase,
                    "to": canonical_column,
                    "message": f"Corrected '{candidate_phrase}' to '{canonical_column}'.",
                }
            )

    return working_query, corrections


def _apply_fuzzy_token_corrections(
    *,
    query: str,
    loaded_schema,
    ignored_terms: set[str] | None = None,
    target_terms: set[str] | None = None,
) -> tuple[str, list[dict[str, str]]]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return normalized_query, []

    ignored = {str(term).strip().lower() for term in (ignored_terms or set()) if str(term).strip()}
    targets = {str(term).strip().lower() for term in (target_terms or set()) if str(term).strip()}
    vocabulary = _schema_token_vocabulary(loaded_schema)
    token_vocabulary = sorted(
        term for term in vocabulary if re.fullmatch(r"[a-z0-9]+", term or "") and len(term) > 2
    )
    if not token_vocabulary:
        return normalized_query, []

    replacements: dict[str, str] = {}
    corrections: list[dict[str, str]] = []

    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", normalized_query):
        lower = token.lower()
        if (
            len(lower) <= 2
            or lower in replacements
            or lower in ignored
            or lower in vocabulary
            or lower in _SCHEMA_CORRECTION_STOP_WORDS
            or lower in _BUSINESS_TERM_NORMALIZATION
            or lower in _PROTECTED_SCHEMA_FUZZY_TOKENS
        ):
            continue
        if targets and lower not in targets:
            continue

        best, _ = _best_fuzzy_candidate(lower, token_vocabulary)
        if not best:
            continue

        if best == lower or abs(len(best) - len(lower)) > 3:
            continue

        replacements[lower] = best
        corrections.append(
            {
                "type": "typo",
                "from": lower,
                "to": best,
                "message": f"Corrected '{lower}' to '{best}'.",
            }
        )

    if not replacements:
        return normalized_query, []

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        return replacements.get(token.lower(), token)

    corrected = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", _replace, normalized_query)
    return corrected, corrections


def _apply_business_term_normalization(query: str) -> tuple[str, list[dict[str, str]]]:
    corrected = str(query or "").strip()
    if not corrected:
        return corrected, []

    corrections: list[dict[str, str]] = []
    for source_term, target_term in _BUSINESS_TERM_NORMALIZATION.items():
        pattern = re.compile(rf"\b{re.escape(source_term)}\b", flags=re.IGNORECASE)
        if not pattern.search(corrected):
            continue
        corrected = pattern.sub(target_term, corrected)
        corrections.append(
            {
                "type": "semantic",
                "from": source_term,
                "to": target_term,
                "message": f"Interpreted '{source_term}' as '{target_term}'.",
            }
        )

    return corrected, corrections


def _resolved_term_aliases(corrections: list[dict[str, str]]) -> set[str]:
    resolved: set[str] = set()
    for correction in corrections:
        if not isinstance(correction, dict):
            continue
        source = str(correction.get("from", "")).strip().lower()
        if not source:
            continue
        resolved.add(source)
        resolved.update(
            token
            for token in re.findall(r"[a-z0-9]+", source.replace("_", " "))
            if token
        )
    return resolved


def _filter_resolved_diagnostics(
    diagnostics: dict[str, object],
    corrections: list[dict[str, str]],
    validation_result: dict[str, object] | None,
) -> dict[str, object]:
    if not isinstance(diagnostics, dict):
        return diagnostics
    resolved_aliases = _resolved_term_aliases(corrections)
    if not resolved_aliases:
        return diagnostics

    filtered = dict(diagnostics)
    unresolved_terms = [
        str(term).strip()
        for term in diagnostics.get("unresolved_terms", [])
        if str(term).strip()
    ]
    unresolved_lexical_terms = [
        str(term).strip()
        for term in diagnostics.get("unresolved_lexical_terms", [])
        if str(term).strip()
    ]
    filtered_unresolved = [
        term
        for term in unresolved_terms
        if str(term).strip().lower() not in resolved_aliases
    ]
    filtered_unresolved_lexical = [
        term
        for term in unresolved_lexical_terms
        if str(term).strip().lower() not in resolved_aliases
    ]
    filtered["unresolved_terms"] = filtered_unresolved
    filtered["unresolved_lexical_terms"] = filtered_unresolved_lexical

    unresolved_before = set(unresolved_terms)
    unresolved_after = set(filtered_unresolved)
    if isinstance(diagnostics.get("candidate_columns"), dict) and unresolved_before != unresolved_after:
        candidate_columns = dict(diagnostics.get("candidate_columns", {}))
        for resolved_term in unresolved_before - unresolved_after:
            candidate_columns.pop(resolved_term, None)
        filtered["candidate_columns"] = candidate_columns

    if (
        not filtered_unresolved
        and not [str(term).strip() for term in diagnostics.get("unsupported_terms", []) if str(term).strip()]
        and bool((validation_result or {}).get("is_valid", False))
    ):
        filtered["schema_validation_status"] = "valid"
    return filtered


def _should_skip_llm_schema_validation(
    *,
    deterministic_validation_result: dict[str, object],
    deterministic_diagnostics: dict[str, object],
    dataset_scope: dict[str, object] | None,
    config: HighPreprocessConfig,
) -> bool:
    if not config.enable_llm_schema_validation:
        return True
    if str((dataset_scope or {}).get("table_name", "")).strip():
        return True
    if not bool(deterministic_validation_result.get("is_valid", False)):
        return False
    unresolved = [str(term).strip() for term in deterministic_diagnostics.get("unresolved_terms", []) if str(term).strip()]
    unsupported = [str(term).strip() for term in deterministic_diagnostics.get("unsupported_terms", []) if str(term).strip()]
    return not unresolved and not unsupported


def run_preprocess_high(
    cleaned_text: str,
    user_id: str,
    route: str = "analytical",
    dataset_scope: dict[str, object] | None = None,
) -> PreprocessHighResult:
    """
    Shared runtime function so this module can be reused by Dagster assets and direct callers.
    """
    logger = _get_logger()
    config = HighPreprocessConfig.from_env()
    retry_count = 0
    final_query = ""
    loaded_schema = None
    validation_result = None
    diagnostics: dict[str, object] = {}
    attempts: list[dict[str, object]] = []
    stage_started_at = _utc_now()
    stage_started_perf = time.perf_counter()

    while True:
        try:
            attempt_started_perf = time.perf_counter()
            normalized_text, normalized_user_id = _validate_inputs(cleaned_text, user_id)
            normalized_route = str(route or "analytical").strip().lower() or "analytical"
            loaded_schema = load_user_schema(
                user_id=normalized_user_id,
                config=config,
                logger=logger,
                log_event=_log_event,
                dataset_scope=dataset_scope,
            )
            term_corrections: list[dict[str, str]] = []
            user_friendly_messages: list[str] = []

            skipped_schema_terms: list[str] = []
            forecast_resolution: dict[str, str] = {}
            if normalized_route == "forecasting":
                # Forecasting control words (e.g., "next 7 days") are not schema entities.
                # Preserve the cleaned query as-is to avoid accidental column rewrites.
                final_query = normalized_text
                skipped_schema_terms = _extract_skipped_forecast_terms(final_query)
                validation_result = build_deterministic_schema_validation_result(
                    corrected_query=final_query,
                    loaded_schema=loaded_schema,
                    ignored_terms=set(skipped_schema_terms),
                )
                validation_result["is_valid"] = True
                validation_result["missing_column"] = ""
                validation_result["invalid_mappings"] = []

                # Phase 5 / CRIT-14: forecasting MUST run schema validation.
                # We resolve forecast_date_column / forecast_target_column from
                # the loaded schema and reject the request with a stable error
                # code when the dataset is incompatible with forecasting.
                forecast_table, forecast_date_column, forecast_target_column = _resolve_forecast_columns(
                    loaded_schema=loaded_schema,
                    dataset_scope=dataset_scope,
                    query_text=normalized_text,
                )
                if not forecast_date_column:
                    raise PreprocessHighMissingColumnError(
                        missing_column=FORECAST_MISSING_TIME_COLUMN,
                        message=(
                            "Forecasting requires a Date/DateTime column, but the selected dataset "
                            f"'{forecast_table or 'workspace'}' does not expose one. "
                            "Add a time column to the dataset or change the question."
                        ),
                    )
                if not forecast_target_column:
                    raise PreprocessHighMissingColumnError(
                        missing_column=FORECAST_MISSING_TARGET_COLUMN,
                        message=(
                            "Forecasting requires a numeric target column (e.g. revenue, sales, count), "
                            f"but the selected dataset '{forecast_table}' does not expose one."
                        ),
                    )
                forecast_resolution = {
                    "forecast_table": forecast_table,
                    "forecast_date_column": forecast_date_column,
                    "forecast_target_column": forecast_target_column,
                }
            else:
                pre_corrected_query, phrase_corrections = _apply_fuzzy_phrase_corrections(
                    query=normalized_text,
                    loaded_schema=loaded_schema,
                )
                pre_corrected_query, fuzzy_corrections = _apply_fuzzy_token_corrections(
                    query=pre_corrected_query,
                    loaded_schema=loaded_schema,
                )
                term_corrections.extend(phrase_corrections)
                pre_corrected_query, semantic_corrections = _apply_business_term_normalization(pre_corrected_query)
                term_corrections.extend(fuzzy_corrections)
                term_corrections.extend(semantic_corrections)
                final_query = pre_corrected_query
                validation_result = build_deterministic_schema_validation_result(
                    corrected_query=final_query,
                    loaded_schema=loaded_schema,
                )
                deterministic_diagnostics = build_schema_resolution_diagnostics(
                    original_query=normalized_text,
                    corrected_query=final_query,
                    loaded_schema=loaded_schema,
                    validation_result=validation_result,
                    ignored_terms=set(skipped_schema_terms),
                )
                if not _should_skip_llm_schema_validation(
                    deterministic_validation_result=validation_result,
                    deterministic_diagnostics=deterministic_diagnostics,
                    dataset_scope=dataset_scope,
                    config=config,
                ):
                    llm_config = HighPreprocessConfig(
                        **{
                            **config.__dict__,
                            "request_timeout_seconds": config.llm_schema_validation_timeout_seconds,
                        }
                    )
                    final_query = correct_query_terms(
                        query=pre_corrected_query,
                        loaded_schema=loaded_schema,
                        config=llm_config,
                        logger=logger,
                        log_event=_log_event,
                    )
                    validation_result = validate_query_schema_usage(
                        corrected_query=final_query,
                        loaded_schema=loaded_schema,
                        config=llm_config,
                        logger=logger,
                        log_event=_log_event,
                    )

            diagnostics = build_schema_resolution_diagnostics(
                original_query=normalized_text,
                corrected_query=final_query,
                loaded_schema=loaded_schema,
                validation_result=validation_result,
                ignored_terms=set(skipped_schema_terms),
            )
            bound_table = str((dataset_scope or {}).get("table_name", "")).strip()
            if bound_table:
                diagnostics["selected_table"] = bound_table
                diagnostics["candidate_tables"] = [bound_table]
                diagnostics["table_match_scores"] = {bound_table: 1}
                diagnostics["selected_table_match_score"] = 1
                bound_columns = loaded_schema.schema.get("columns", {}).get(bound_table, [])
                if not bound_columns:
                    for table_name, table_columns in loaded_schema.schema.get("columns", {}).items():
                        if str(table_name).split(".")[-1].lower() == bound_table.split(".")[-1].lower():
                            bound_columns = table_columns
                            diagnostics["selected_table"] = table_name
                            break
                diagnostics["selected_columns"] = [
                    str(column.get("name", "")).strip()
                    for column in bound_columns
                    if isinstance(column, dict) and str(column.get("name", "")).strip()
                ]
            if normalized_route == "forecasting":
                diagnostics["schema_validation_status"] = "skipped_for_forecasting"
                diagnostics["unresolved_terms"] = []
                diagnostics["unsupported_terms"] = []
            else:
                recovery_passes = 0
                max_recovery_passes = 2
                unresolved_terms = [str(term) for term in diagnostics.get("unresolved_terms", []) if str(term)]
                while unresolved_terms and recovery_passes < max_recovery_passes:
                    recovery_passes += 1
                    recovery_query = final_query
                    recovery_corrections: list[dict[str, str]] = []

                    phrase_recovery_query, phrase_recovery = _apply_fuzzy_phrase_corrections(
                        query=recovery_query,
                        loaded_schema=loaded_schema,
                        ignored_terms=set(skipped_schema_terms),
                        target_terms=set(unresolved_terms),
                    )
                    if phrase_recovery and phrase_recovery_query != recovery_query:
                        recovery_query = phrase_recovery_query
                        recovery_corrections.extend(phrase_recovery)

                    fuzzy_recovery_query, fuzzy_recovery = _apply_fuzzy_token_corrections(
                        query=recovery_query,
                        loaded_schema=loaded_schema,
                        ignored_terms=set(skipped_schema_terms),
                        target_terms=set(unresolved_terms),
                    )
                    if fuzzy_recovery and fuzzy_recovery_query != recovery_query:
                        recovery_query = fuzzy_recovery_query
                        recovery_corrections.extend(fuzzy_recovery)

                    semantic_recovery_query, semantic_recovery = _apply_business_term_normalization(recovery_query)
                    if semantic_recovery and semantic_recovery_query != recovery_query:
                        recovery_query = semantic_recovery_query
                        recovery_corrections.extend(semantic_recovery)

                    if recovery_query == final_query:
                        break

                    final_query = recovery_query
                    # Recovery pass: rerun schema-aware validation on the corrected query.
                    if _should_skip_llm_schema_validation(
                        deterministic_validation_result=validation_result,
                        deterministic_diagnostics=diagnostics,
                        dataset_scope=dataset_scope,
                        config=config,
                    ):
                        validation_result = build_deterministic_schema_validation_result(
                            corrected_query=final_query,
                            loaded_schema=loaded_schema,
                            ignored_terms=set(skipped_schema_terms),
                        )
                    else:
                        llm_config = HighPreprocessConfig(
                            **{
                                **config.__dict__,
                                "request_timeout_seconds": config.llm_schema_validation_timeout_seconds,
                            }
                        )
                        validation_result = validate_query_schema_usage(
                            corrected_query=final_query,
                            loaded_schema=loaded_schema,
                            config=llm_config,
                            logger=logger,
                            log_event=_log_event,
                        )
                    diagnostics = build_schema_resolution_diagnostics(
                        original_query=normalized_text,
                        corrected_query=final_query,
                        loaded_schema=loaded_schema,
                        validation_result=validation_result,
                        ignored_terms=set(skipped_schema_terms),
                    )
                    term_corrections.extend(recovery_corrections)
                    unresolved_terms = [str(term) for term in diagnostics.get("unresolved_terms", []) if str(term)]

            diagnostics = _filter_resolved_diagnostics(
                diagnostics=diagnostics,
                corrections=term_corrections,
                validation_result=validation_result,
            )

            schema_validation_status = str(diagnostics.get("schema_validation_status", "unknown")).strip().lower()
            has_schema_validation_issue = schema_validation_status != "valid" or not bool(
                validation_result.get("is_valid", False)
            )
            if normalized_route == "forecasting":
                has_schema_validation_issue = False

            deferred_schema_warnings: list[dict[str, str]] = []
            if has_schema_validation_issue:
                unresolved_terms = [str(term) for term in diagnostics.get("unresolved_terms", []) if str(term)]
                unsupported_terms = [str(term) for term in diagnostics.get("unsupported_terms", []) if str(term)]
                missing_column = str(validation_result.get("missing_column") or "").strip() or "unknown"
                if missing_column == "unknown" and unresolved_terms:
                    missing_column = unresolved_terms[0]

                if unresolved_terms:
                    message = (
                        "Schema validation failed because the query contains unresolved terms: "
                        f"{', '.join(unresolved_terms)}."
                    )
                    recommended_fix = _recommended_columns_text(loaded_schema.schema)
                elif unsupported_terms:
                    message = (
                        "Schema validation failed because the query uses unsupported time concepts: "
                        f"{', '.join(unsupported_terms)}."
                    )
                    recommended_fix = (
                        "Remove time-based grouping/filtering or add a Date/DateTime column to the dataset."
                    )
                else:
                    message = "Schema validation failed due to invalid schema references."
                    recommended_fix = "Use existing table/column names from the current dataset schema."

                attempts.append(
                    make_attempt(
                        attempt_number=len(attempts) + 1,
                        input_payload={"query": normalized_text, "user_id": normalized_user_id},
                        output_payload={
                            "final_query": final_query,
                            "validation_result": validation_result,
                            "diagnostics": diagnostics,
                        },
                        success=True,
                        retry_triggered=False,
                        model_or_method_used=f"schema_loader+ollama:{config.ollama_model}",
                        duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                        validation_result={
                            "is_valid": True,
                            "deferred_schema_validation": True,
                            "missing_column": missing_column,
                        },
                    )
                )
                deferred_schema_warnings.append(
                    {
                        "type": "schema_validation_deferred",
                        "message": f"{message} Deferred to intent-aware validation. {recommended_fix}",
                    }
                )
            for correction in term_corrections:
                message = str(correction.get("message", "")).strip()
                if message and message not in user_friendly_messages:
                    user_friendly_messages.append(message)
            for warning in deferred_schema_warnings:
                warning_message = str(warning.get("message", "")).strip()
                if warning_message and warning_message not in user_friendly_messages:
                    user_friendly_messages.append(warning_message)

            _log_event(
                logger,
                logging.INFO,
                "High preprocessing completed successfully",
                user_id=normalized_user_id,
                schema_valid=not bool(deferred_schema_warnings),
                final_query_preview=final_query[:200],
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"query": normalized_text, "user_id": normalized_user_id},
                    output_payload={
                        "final_query": final_query,
                        "validation_result": validation_result,
                        "diagnostics": diagnostics,
                    },
                    success=True,
                    retry_triggered=False,
                    model_or_method_used=f"schema_loader+ollama:{config.ollama_model}",
                    duration_ms=int((time.perf_counter() - attempt_started_perf) * 1000),
                    validation_result={"is_valid": True},
                )
            )
            success_payload = build_preprocess_high_success_result(
                final_query=final_query,
                schema_used=loaded_schema.schema,
                mappings=validation_result.get("mappings", []),
                derivable_columns=validation_result.get("derivable_columns", []),
                invalid_mappings=validation_result.get("invalid_mappings", []),
            )
            if deferred_schema_warnings:
                success_payload["status"] = "degraded"
                success_payload["schema_valid"] = False
                success_payload["degraded"] = True
                success_payload["deferred"] = True
                success_payload["degradation_reason"] = "schema_validation_deferred"
            else:
                success_payload["degraded"] = False
                success_payload["deferred"] = False
                success_payload["degradation_reason"] = ""
            success_payload.update(diagnostics)
            success_payload["attempts"] = attempts
            success_payload["attempts_count"] = len(attempts)
            success_payload["warnings"] = deferred_schema_warnings
            success_payload["errors"] = []
            success_payload["term_corrections"] = term_corrections
            success_payload["user_friendly_messages"] = user_friendly_messages
            success_payload["started_at"] = stage_started_at
            success_payload["finished_at"] = _utc_now()
            success_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            success_payload["debug_metadata"] = {
                "user_id": normalized_user_id,
                "schema_tables": len(loaded_schema.schema.get("tables", [])),
                "route": normalized_route,
                "dataset_scope": dataset_scope or {},
                "reason_for_selection": "schema_validation_deferred" if deferred_schema_warnings else "schema_validation_passed",
                "auto_recovery_applied": bool(term_corrections),
            }
            success_payload["route"] = normalized_route
            success_payload["skipped_schema_terms"] = skipped_schema_terms
            if forecast_resolution:
                success_payload["forecast_table"] = forecast_resolution.get("forecast_table", "")
                success_payload["forecast_date_column"] = forecast_resolution.get("forecast_date_column", "")
                success_payload["forecast_target_column"] = forecast_resolution.get(
                    "forecast_target_column", ""
                )
            _attach_intent_query_metadata(success_payload, original_text=normalized_text, final_text=final_query)
            success_payload["confidence"] = schema_confidence(success_payload)
            return success_payload
        except PreprocessHighMissingColumnError as exc:
            _log_event(
                logger,
                logging.WARNING,
                "High preprocessing rejected due to missing column",
                missing_column=exc.missing_column,
                final_query_preview=final_query[:200],
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"query": cleaned_text, "user_id": user_id},
                    output_payload={},
                    success=False,
                    retry_triggered=False,
                    model_or_method_used=f"schema_loader+ollama:{config.ollama_model}",
                    duration_ms=0,
                    validation_result={"is_valid": False, "missing_column": exc.missing_column},
                    error_type="business",
                    error_message=str(exc),
                )
            )
            rejected_payload = build_preprocess_high_rejected_result(
                final_query=final_query,
                missing_column=exc.missing_column,
                schema_used=(loaded_schema.schema if loaded_schema else None),
                mappings=(validation_result.get("mappings", []) if validation_result else None),
                derivable_columns=(
                    validation_result.get("derivable_columns", [])
                    if validation_result
                    else None
                ),
                invalid_mappings=(
                    validation_result.get("invalid_mappings", [])
                    if validation_result
                    else None
                ),
            )
            rejected_payload["attempts"] = attempts
            rejected_payload["attempts_count"] = len(attempts)
            rejected_payload["warnings"] = []
            rejected_payload["errors"] = [{"type": "business", "message": str(exc)}]
            rejected_payload["started_at"] = stage_started_at
            rejected_payload["finished_at"] = _utc_now()
            rejected_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            rejected_payload["debug_metadata"] = {}
            rejected_payload["confidence"] = schema_confidence(rejected_payload)
            return rejected_payload
        except Exception as exc:  # noqa: BLE001
            error_type = classify_preprocess_high_error(exc)
            action_taken = decide_preprocess_high_action(
                error_type=error_type,
                retry_count=retry_count,
                config=config,
            )
            attempts.append(
                make_attempt(
                    attempt_number=len(attempts) + 1,
                    input_payload={"query": cleaned_text, "user_id": user_id},
                    output_payload={},
                    success=False,
                    retry_triggered=action_taken == "retry",
                    retry_reason=str(exc) if action_taken == "retry" else "",
                    model_or_method_used=f"schema_loader+ollama:{config.ollama_model}",
                    duration_ms=0,
                    validation_result={"is_valid": False},
                    error_type=error_type,
                    error_message=str(exc),
                )
            )

            _log_event(
                logger,
                logging.ERROR,
                "High preprocessing failed",
                error_type=error_type,
                action_taken=action_taken,
                retry_count=retry_count,
                final_query_preview=final_query[:200],
                error=str(exc),
            )

            if action_taken == "retry":
                retry_count += 1
                continue

            if error_type in {"llm", "system", "unknown"} and loaded_schema is not None:
                fallback_query = final_query or str(cleaned_text or "").strip()
                fallback_validation_result = build_deterministic_schema_validation_result(
                    corrected_query=fallback_query,
                    loaded_schema=loaded_schema,
                    ignored_terms=(
                        set(_extract_skipped_forecast_terms(fallback_query))
                        if str(route or "analytical").strip().lower() == "forecasting"
                        else None
                    ),
                )
                fallback_diagnostics = build_schema_resolution_diagnostics(
                    original_query=str(cleaned_text or "").strip(),
                    corrected_query=fallback_query,
                    loaded_schema=loaded_schema,
                    validation_result=fallback_validation_result,
                )
                fallback_schema_status = str(
                    fallback_diagnostics.get("schema_validation_status", "unknown")
                ).strip().lower()
                fallback_is_valid = bool(fallback_validation_result.get("is_valid", False))
                fallback_success = fallback_is_valid and fallback_schema_status == "valid"
                attempts.append(
                    make_attempt(
                        attempt_number=len(attempts) + 1,
                        input_payload={"query": cleaned_text, "user_id": user_id},
                        output_payload={
                            "final_query": fallback_query,
                            "validation_result": fallback_validation_result,
                            "diagnostics": fallback_diagnostics,
                        },
                        success=fallback_success,
                        retry_triggered=False,
                        model_or_method_used="deterministic_schema_fallback",
                        duration_ms=0,
                        validation_result={
                            "is_valid": fallback_success,
                            "schema_validation_status": fallback_schema_status,
                        },
                        error_type="" if fallback_success else "business",
                        error_message="" if fallback_success else str(exc),
                    )
                )

                if fallback_success:
                    success_payload = build_preprocess_high_success_result(
                        final_query=fallback_query,
                        schema_used=loaded_schema.schema,
                        mappings=fallback_validation_result.get("mappings", []),
                        derivable_columns=fallback_validation_result.get("derivable_columns", []),
                        invalid_mappings=fallback_validation_result.get("invalid_mappings", []),
                    )
                    success_payload["degraded"] = False
                    success_payload["deferred"] = False
                    success_payload["degradation_reason"] = ""
                    success_payload.update(fallback_diagnostics)
                    success_payload["attempts"] = attempts
                    success_payload["attempts_count"] = len(attempts)
                    success_payload["warnings"] = [
                        {
                            "type": "schema_validation_llm_fallback",
                            "message": (
                                "LLM schema correction/validation failed; deterministic "
                                "schema fallback was used."
                            ),
                        }
                    ]
                    success_payload["errors"] = []
                    success_payload["started_at"] = stage_started_at
                    success_payload["finished_at"] = _utc_now()
                    success_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
                    success_payload["debug_metadata"] = {
                        "retry_count": retry_count,
                        "action_taken": action_taken,
                        "llm_fallback_used": True,
                        "llm_fallback_error_type": error_type,
                        "llm_fallback_error": str(exc),
                        "schema_tables": len(loaded_schema.schema.get("tables", [])),
                        "dataset_scope": dataset_scope or {},
                        "reason_for_selection": "deterministic_schema_fallback",
                    }
                    success_payload["status"] = "degraded"
                    success_payload["degraded"] = True
                    success_payload["degradation_reason"] = "schema_validation_llm_fallback"
                    _attach_intent_query_metadata(
                        success_payload,
                        original_text=str(cleaned_text or "").strip(),
                        final_text=fallback_query,
                    )
                    success_payload["confidence"] = schema_confidence(success_payload)
                    _log_event(
                        logger,
                        logging.WARNING,
                        "High preprocessing fallback activated",
                        fallback_mode="deterministic_schema_validation",
                        final_query_preview=fallback_query[:200],
                    )
                    return success_payload

                unresolved_terms = [
                    str(term) for term in fallback_diagnostics.get("unresolved_terms", []) if str(term)
                ]
                unsupported_terms = [
                    str(term) for term in fallback_diagnostics.get("unsupported_terms", []) if str(term)
                ]
                missing_column = str(fallback_validation_result.get("missing_column") or "").strip() or "unknown"
                if missing_column == "unknown" and unresolved_terms:
                    missing_column = unresolved_terms[0]
                if unresolved_terms:
                    fallback_message = (
                        "Schema validation failed because the query contains unresolved terms: "
                        f"{', '.join(unresolved_terms)}."
                    )
                elif unsupported_terms:
                    fallback_message = (
                        "Schema validation failed because the query uses unsupported time concepts: "
                        f"{', '.join(unsupported_terms)}."
                    )
                else:
                    fallback_message = "Schema validation failed due to invalid schema references."

                rejected_payload = build_preprocess_high_rejected_result(
                    final_query=fallback_query,
                    missing_column=missing_column,
                    message=fallback_message,
                    schema_used=loaded_schema.schema,
                    mappings=fallback_validation_result.get("mappings", []),
                    derivable_columns=fallback_validation_result.get("derivable_columns", []),
                    invalid_mappings=fallback_validation_result.get("invalid_mappings", []),
                )
                rejected_payload.update(fallback_diagnostics)
                rejected_payload["attempts"] = attempts
                rejected_payload["attempts_count"] = len(attempts)
                rejected_payload["warnings"] = [
                    {
                        "type": "schema_validation_llm_fallback_rejected",
                        "message": (
                            "LLM schema correction/validation failed and deterministic "
                            "fallback also found invalid schema references."
                        ),
                    }
                ]
                rejected_payload["errors"] = [{"type": "business", "message": fallback_message}]
                rejected_payload["started_at"] = stage_started_at
                rejected_payload["finished_at"] = _utc_now()
                rejected_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
                rejected_payload["debug_metadata"] = {
                    "retry_count": retry_count,
                    "action_taken": action_taken,
                    "llm_fallback_used": True,
                    "llm_fallback_error_type": error_type,
                    "llm_fallback_error": str(exc),
                    "dataset_scope": dataset_scope or {},
                    "reason_for_selection": "deterministic_fallback_rejected",
                }
                rejected_payload["confidence"] = schema_confidence(rejected_payload)
                return rejected_payload

            failed_payload = build_preprocess_high_failed_result(
                error_type=error_type,
                action_taken=action_taken,
                final_query=final_query,
                schema_used=(loaded_schema.schema if loaded_schema else None),
                mappings=(validation_result.get("mappings", []) if validation_result else None),
                derivable_columns=(
                    validation_result.get("derivable_columns", [])
                    if validation_result
                    else None
                ),
                invalid_mappings=(
                    validation_result.get("invalid_mappings", [])
                    if validation_result
                    else None
                ),
            )
            if diagnostics:
                failed_payload.update(diagnostics)
            failed_payload["attempts"] = attempts
            failed_payload["attempts_count"] = len(attempts)
            failed_payload["warnings"] = []
            failed_payload["errors"] = [{"type": error_type, "message": str(exc)}]
            failed_payload["started_at"] = stage_started_at
            failed_payload["finished_at"] = _utc_now()
            failed_payload["duration_ms"] = int((time.perf_counter() - stage_started_perf) * 1000)
            failed_payload["debug_metadata"] = {
                "retry_count": retry_count,
                "action_taken": action_taken,
            }
            failed_payload["confidence"] = schema_confidence(failed_payload)
            return failed_payload


def _attach_fn_compat(func):
    """
    Keep compatibility for existing call sites/tests that use Prefect's `.fn`.
    """
    setattr(func, "fn", func)
    return func


@_attach_fn_compat
def preprocess_high_task(
    cleaned_text: str,
    user_id: str,
    route: str = "analytical",
    dataset_scope: dict[str, object] | None = None,
) -> dict:
    return run_preprocess_high(
        cleaned_text=cleaned_text,
        user_id=user_id,
        route=route,
        dataset_scope=dataset_scope,
    )

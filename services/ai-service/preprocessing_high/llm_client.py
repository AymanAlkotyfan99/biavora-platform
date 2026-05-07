from __future__ import annotations

import json
import logging
import re
from typing import Callable

import requests

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
    _SHARED_CLIENT_AVAILABLE = True
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]
    _SHARED_CLIENT_AVAILABLE = False

from preprocessing_high.error_handler import (
    PreprocessHighLLMError,
    PreprocessHighSystemError,
)
from preprocessing_high.schema_loader import (
    LoadedUserSchema,
    find_column_matches,
    get_fallback_derivable_column,
)
from preprocessing_high.schemas import HighPreprocessConfig, SchemaValidationResult, ValidationMapping
from shared.schema_utils import is_date_type


_DERIVABLE_TIME_TERMS = {
    "year",
    "years",
    "month",
    "months",
    "day",
    "days",
    "date",
    "dates",
    "week",
    "weeks",
    "quarter",
    "quarters",
    "hour",
    "hours",
    "yearly",
    "monthly",
    "daily",
    "weekly",
    "quarterly",
    "hourly",
}

_VALID_REFERENCE_STATUSES = {"exact", "mapped", "derivable", "invalid"}
_DETERMINISTIC_FALLBACK_STOP_TOKENS = {
    "show",
    "me",
    "the",
    "a",
    "an",
    "of",
    "for",
    "to",
    "and",
    "by",
    "in",
    "on",
    "with",
    "please",
    "top",
    "list",
    "get",
    "give",
    "display",
    "what",
    "how",
    "many",
    "do",
    "we",
    "have",
    "had",
    "has",
    "which",
    "when",
    "where",
    "from",
    "between",
    "over",
    "under",
    "is",
    "are",
    "number",
    "numbers",
    "each",
    "per",
    "across",
    "group",
    "grouped",
    "grouping",
    "total",
    "avg",
    "average",
    "sum",
    "count",
    "min",
    "max",
    "impact",
    "effect",
    "influence",
    "relationship",
    "correlation",
    "distribution",
    "distributed",
    "spread",
    "histogram",
    "frequency",
    "trend",
    "trends",
    "values",
    "value",
    "together",
    "jointly",
    "alongside",
    "simultaneously",
    "concurrently",
    "share",
    "percentage",
    "percent",
    "ratio",
    "cumulative",
    "accumulated",
    "stack",
    "stacked",
    "chart",
    "charts",
    "line",
    "lines",
    "bar",
    "bars",
    "combo",
    "mixed",
}
_SEMANTIC_MAPPING_MIN_SCORE = 2.0
_SEMANTIC_MAPPING_MIN_MARGIN = 0.25
_RANKING_WORDS = ("highest", "lowest", "largest", "smallest", "top", "bottom", "best", "worst")
_COMPARISON_WORDS = ("above", "below", "over", "under", "greater than", "less than", "between")
_TOKEN_SYNONYMS = {
    "revenue": {"sales", "total_sales", "sale", "amount"},
    "sales": {"revenue", "sale", "total_sales"},
}

# Reserved predictive vocabulary that must never be interpreted as schema entities.
FORECAST_RESERVED_TERMS = {
    "forecast",
    "forecasting",
    "predict",
    "predictive",
    "prediction",
    "predictions",
    "future",
    "next",
    "expected",
    "trend",
    "trends",
    "upcoming",
    "day",
    "days",
    "week",
    "weeks",
    "month",
    "months",
    "year",
    "years",
}


def _schema_for_prompt(loaded_schema: LoadedUserSchema) -> str:
    prompt_schema = {
        "tables": loaded_schema.schema["tables"],
        "columns": loaded_schema.schema["columns"],
    }
    return json.dumps(prompt_schema, ensure_ascii=True, separators=(",", ":"))


def _extract_ollama_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error_value = payload.get("error")
            if isinstance(error_value, str) and error_value.strip():
                return error_value.strip()
    except ValueError:
        pass
    return response.text.strip()


def _call_ollama(
    *,
    prompt: str,
    config: HighPreprocessConfig,
    purpose: str,
    logger: logging.Logger,
    log_event: Callable[..., None],
) -> str:
    payload = {
        "model": config.ollama_model,
        "prompt": prompt,
        "stream": False,
    }

    log_event(
        logger,
        logging.INFO,
        "Calling Ollama for preprocessing_high",
        purpose=purpose,
        model=config.ollama_model,
        endpoint=config.ollama_url,
    )

    try:
        if _SHARED_CLIENT_AVAILABLE:
            response = get_default_client().post(
                config.ollama_url,
                json=payload,
                timeout=(min(5.0, float(config.request_timeout_seconds)), float(config.request_timeout_seconds)),
                attach_internal_api_key=False,
            )
        else:
            response = requests.post(
                config.ollama_url,
                json=payload,
                timeout=config.request_timeout_seconds,
            )
    except requests.Timeout as exc:
        raise PreprocessHighSystemError(
            f"Ollama timeout during {purpose} after {config.request_timeout_seconds}s."
        ) from exc
    except requests.ConnectionError as exc:
        raise PreprocessHighSystemError(f"Ollama connection error during {purpose}.") from exc
    except HttpClientError as exc:  # type: ignore[misc]
        raise PreprocessHighSystemError(f"Ollama HTTP failure during {purpose}: {exc}") from exc
    except requests.RequestException as exc:
        raise PreprocessHighSystemError(f"Ollama request failure during {purpose}.") from exc

    if response.status_code in {408, 429, 500, 502, 503, 504}:
        raise PreprocessHighSystemError(
            f"Ollama transient failure ({response.status_code}) during {purpose}: "
            f"{_extract_ollama_error_message(response)}"
        )

    if response.status_code >= 400:
        raise PreprocessHighLLMError(
            f"Ollama returned HTTP {response.status_code} during {purpose}: "
            f"{_extract_ollama_error_message(response)}"
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise PreprocessHighLLMError("Ollama returned a non-JSON response.") from exc

    model_output = str(body.get("response", "")).strip()
    if not model_output:
        raise PreprocessHighLLMError(f"Ollama returned empty output during {purpose}.")

    return model_output


def _build_correction_prompt(*, query: str, loaded_schema: LoadedUserSchema) -> str:
    return (
        "You are a schema-aware query term corrector for analytical questions.\n"
        "Correct user query terms so they match the provided ClickHouse schema exactly.\n\n"
        "Rules:\n"
        "1) Fix typos, spelling mistakes, partial words, and naming variations only when mapping to existing schema names.\n"
        "2) Never invent new tables or columns.\n"
        "3) Do not change the user intent or meaning.\n"
        "4) Keep the same language as the input whenever possible.\n"
        "5) If a term cannot be mapped confidently, keep it unchanged.\n\n"
        "Output constraints:\n"
        "- Output only the corrected query text.\n"
        "- No explanation.\n"
        "- No markdown.\n"
        "- No JSON unless the query itself is JSON.\n\n"
        f"Schema:\n{_schema_for_prompt(loaded_schema)}\n\n"
        f"User query:\n{query}\n\n"
        "Corrected query:"
    )


def _normalize_correction_output(raw_output: str) -> str:
    cleaned = raw_output.strip()
    cleaned = re.sub(r"^```(?:\w+)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            payload = json.loads(cleaned)
            if isinstance(payload, dict):
                for key in ("corrected_query", "final_query", "query"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        cleaned = value.strip()
                        break
        except ValueError:
            pass

    if "\n" in cleaned:
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        if lines:
            cleaned = lines[0]

    cleaned = re.sub(r"^[\"']|[\"']$", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        raise PreprocessHighLLMError("Corrected query output is empty.")
    return cleaned


def _extract_query_shape(query: str) -> dict[str, Any]:
    normalized = str(query or "").strip().lower()
    numeric_limits = [int(value) for value in re.findall(r"\b(?:top|bottom|first|last)\s+(\d+)\b", normalized)]
    explicit_numbers = [int(value) for value in re.findall(r"\b\d+\b", normalized)]
    has_where_like = bool(re.search(r"\b(where|having|with)\b", normalized))
    has_comparison = bool(
        re.search(r"(>=|<=|>|<|=)", normalized) or any(word in normalized for word in _COMPARISON_WORDS)
    )
    ranking_direction = ""
    if any(word in normalized for word in ("highest", "largest", "most", "top", "best")):
        ranking_direction = "DESC"
    elif any(word in normalized for word in ("lowest", "smallest", "least", "bottom", "worst")):
        ranking_direction = "ASC"
    has_time_series_language = bool(
        re.search(r"\bover\s+time\b", normalized)
        or re.search(r"\btrend(s)?\b", normalized)
        or re.search(r"\bby\s+date\b", normalized)
        or re.search(r"\bby\s+day\b", normalized)
        or re.search(r"\b(daily|weekly|monthly|quarterly|yearly|annually)\b", normalized)
        or re.search(r"\b(per|by)\s+(day|week|month|quarter|year)\b", normalized)
    )
    return {
        "numeric_limits": numeric_limits,
        "explicit_numbers": explicit_numbers,
        "has_where_like": has_where_like,
        "has_comparison": has_comparison,
        "ranking_direction": ranking_direction,
        "has_ranking_language": any(word in normalized for word in _RANKING_WORDS),
        "has_time_series_language": has_time_series_language,
    }


def _is_correction_structure_safe(original_query: str, corrected_query: str) -> bool:
    source = _extract_query_shape(original_query)
    corrected = _extract_query_shape(corrected_query)

    if source["has_ranking_language"] and not corrected["has_ranking_language"]:
        return False
    if source["ranking_direction"] and source["ranking_direction"] != corrected["ranking_direction"]:
        return False
    if source["numeric_limits"] and source["numeric_limits"] != corrected["numeric_limits"]:
        return False
    if source["has_where_like"] and not corrected["has_where_like"]:
        return False
    if source["has_comparison"] and not corrected["has_comparison"]:
        return False
    if source["explicit_numbers"] and corrected["explicit_numbers"] and source["explicit_numbers"] != corrected["explicit_numbers"]:
        return False
    if source.get("has_time_series_language") and not corrected.get("has_time_series_language"):
        return False
    return True


def correct_query_terms(
    *,
    query: str,
    loaded_schema: LoadedUserSchema,
    config: HighPreprocessConfig,
    logger: logging.Logger,
    log_event: Callable[..., None],
) -> str:
    prompt = _build_correction_prompt(query=query, loaded_schema=loaded_schema)
    raw_output = _call_ollama(
        prompt=prompt,
        config=config,
        purpose="term_correction",
        logger=logger,
        log_event=log_event,
    )
    corrected = _normalize_correction_output(raw_output)
    if not _is_correction_structure_safe(query, corrected):
        log_event(
            logger,
            logging.WARNING,
            "Schema-aware term correction failed structural guardrails; using original cleaned query",
            original_query=query,
            corrected_query=corrected,
        )
        corrected = str(query or "").strip()
    log_event(
        logger,
        logging.INFO,
        "Schema-aware term correction completed",
        input_chars=len(query),
        output_chars=len(corrected),
    )
    return corrected


def _extract_json_object(raw_output: str) -> dict:
    start = raw_output.find("{")
    end = raw_output.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise PreprocessHighLLMError("Validation output does not contain JSON.")

    json_blob = raw_output[start : end + 1]
    try:
        payload = json.loads(json_blob)
    except ValueError as exc:
        raise PreprocessHighLLMError("Validation JSON payload is malformed.") from exc

    if not isinstance(payload, dict):
        raise PreprocessHighLLMError("Validation payload must be a JSON object.")
    return payload


def _build_validation_prompt(*, corrected_query: str, loaded_schema: LoadedUserSchema) -> str:
    return (
        "You validate whether a corrected analytical query references valid schema fields.\n"
        "Return JSON only.\n\n"
        "Allowed statuses:\n"
        "- exact: requested term exactly exists in schema.\n"
        "- mapped: requested term can be mapped to an existing schema column with similar meaning.\n"
        "- derivable: requested term can be derived from a Date/DateTime/Timestamp column.\n"
        "- invalid: no valid mapping exists.\n\n"
        "Derivable examples:\n"
        "- year, month, day, week, quarter from datetime/date columns.\n\n"
        "Output JSON schema:\n"
        "{\n"
        '  "references": [\n'
        "    {\n"
        '      "requested": "string",\n'
        '      "matched_table": "string",\n'
        '      "matched_column": "string",\n'
        '      "status": "exact|mapped|derivable|invalid",\n'
        '      "reason": "short explanation"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Include every table/column-like reference in the query. "
        "If there is no reference, return references as an empty array.\n\n"
        f"Schema:\n{_schema_for_prompt(loaded_schema)}\n\n"
        f"Corrected query:\n{corrected_query}\n\n"
        "JSON response:"
    )


def _is_derivable_request(term: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(term or "").strip().lower())
    if not normalized:
        return False
    return normalized in _DERIVABLE_TIME_TERMS


def _build_mapping(
    *,
    requested: str,
    matched_table: str,
    matched_column: str,
    status: str,
    reason: str,
) -> ValidationMapping:
    return {
        "requested": requested,
        "matched_table": matched_table,
        "matched_column": matched_column,
        "status": status,  # type: ignore[typeddict-item]
        "reason": reason,
    }


def _resolve_reference(
    *,
    loaded_schema: LoadedUserSchema,
    requested: str,
    matched_table: str,
    matched_column: str,
    status: str,
    reason: str,
    preferred_table: str | None = None,
) -> tuple[bool, ValidationMapping, str]:
    normalized_status = status.lower().strip()
    if normalized_status not in _VALID_REFERENCE_STATUSES:
        return (
            False,
            _build_mapping(
                requested=requested,
                matched_table=matched_table,
                matched_column=matched_column,
                status="invalid",
                reason=f"Unsupported status '{status}'.",
            ),
            requested or matched_column or "unknown",
        )

    if normalized_status == "invalid":
        return (
            False,
            _build_mapping(
                requested=requested,
                matched_table=matched_table,
                matched_column=matched_column,
                status="invalid",
                reason=reason or "No matching schema element found.",
            ),
            requested or matched_column or "unknown",
        )

    target_column = matched_column or requested
    candidate_table = matched_table or preferred_table or None
    matches = find_column_matches(
        loaded_schema=loaded_schema,
        column_name=target_column,
        table_name=candidate_table,
    )

    if not matches and target_column != requested:
        matches = find_column_matches(
            loaded_schema=loaded_schema,
            column_name=requested,
            table_name=candidate_table,
        )

    if normalized_status in {"exact", "mapped"}:
        if not matches:
            return (
                False,
                _build_mapping(
                    requested=requested,
                    matched_table=matched_table,
                    matched_column=target_column,
                    status="invalid",
                    reason=reason or "Mapped column does not exist in schema.",
                ),
                requested or target_column or "unknown",
            )

        chosen = matches[0]
        return (
            True,
            _build_mapping(
                requested=requested,
                matched_table=chosen.table,
                matched_column=chosen.name,
                status=normalized_status,
                reason=reason or "Mapped to existing schema column.",
            ),
            "",
        )

    if not _is_derivable_request(requested):
        return (
            False,
            _build_mapping(
                requested=requested,
                matched_table=matched_table,
                matched_column=target_column,
                status="invalid",
                reason=reason or "Requested field is not a supported derivable datetime granularity.",
            ),
            requested or target_column or "unknown",
        )

    if not matches:
        fallback = get_fallback_derivable_column(loaded_schema)
        if fallback is not None and preferred_table and fallback.table.lower() != preferred_table.lower():
            fallback = None
        if fallback is not None:
            matches = [fallback]

    if not matches:
        return (
            False,
            _build_mapping(
                requested=requested,
                matched_table=matched_table,
                matched_column=target_column,
                status="invalid",
                reason=reason or "No datetime column available for derivation.",
            ),
            requested or target_column or "unknown",
        )

    date_match = next((match for match in matches if is_date_type(match.type)), None)
    if date_match is None:
        return (
            False,
            _build_mapping(
                requested=requested,
                matched_table=matches[0].table,
                matched_column=matches[0].name,
                status="invalid",
                reason=reason or "Derivable request requires a Date/DateTime column.",
            ),
            requested or matches[0].name or "unknown",
        )

    return (
        True,
        _build_mapping(
            requested=requested,
            matched_table=date_match.table,
            matched_column=date_match.name,
            status="derivable",
            reason=reason or "Derivable from datetime column.",
        ),
        "",
    )


def _find_direct_schema_mentions(
    *,
    query: str,
    loaded_schema: LoadedUserSchema,
) -> list[ValidationMapping]:
    query_lower = f" {query.lower()} "
    mappings: list[ValidationMapping] = []
    seen: set[str] = set()

    for table_name, columns in loaded_schema.schema["columns"].items():
        for column in columns:
            column_name = column["name"]
            variants = {column_name.lower(), column_name.lower().replace("_", " ")}
            if any(f" {variant} " in query_lower for variant in variants):
                key = f"{table_name}:{column_name.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                mappings.append(
                    _build_mapping(
                        requested=column_name,
                        matched_table=table_name,
                        matched_column=column_name,
                        status="exact",
                        reason="Direct schema match found in corrected query.",
                    )
                )

    return mappings


def _token_forms(token: str) -> set[str]:
    normalized = str(token or "").strip().lower()
    if not normalized:
        return set()
    forms = {normalized}
    if normalized.endswith("ies") and len(normalized) > 4:
        forms.add(normalized[:-3] + "y")
    if (
        normalized.endswith("s")
        and len(normalized) > 3
        and not normalized.endswith(("ss", "us", "is", "ous"))
    ):
        forms.add(normalized[:-1])
    return forms


def _expanded_token_forms(token: str) -> set[str]:
    forms = _token_forms(token)
    expanded = set(forms)
    for form in list(forms):
        expanded.update(_TOKEN_SYNONYMS.get(form, set()))
    return expanded


def _find_semantic_schema_mentions(
    *,
    query: str,
    loaded_schema: LoadedUserSchema,
    existing_requested: set[str],
    ignored_terms: set[str] | None = None,
) -> list[ValidationMapping]:
    mappings: list[ValidationMapping] = []
    raw_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(query or "").lower())
    seen_requested = set(existing_requested)
    ignored = {str(term).strip().lower() for term in (ignored_terms or set()) if str(term).strip()}

    column_catalog: list[tuple[str, str, set[str]]] = []
    for table_name, columns in loaded_schema.schema["columns"].items():
        for column in columns:
            column_name = str(column.get("name", "")).strip()
            if not column_name:
                continue
            column_tokens = set(re.findall(r"[A-Za-z0-9]+", column_name.lower().replace("_", " ")))
            if not column_tokens:
                continue
            column_catalog.append((table_name, column_name, column_tokens))

    for token in raw_tokens:
        token_forms = _expanded_token_forms(token)
        if not token_forms:
            continue
        if token_forms & _DETERMINISTIC_FALLBACK_STOP_TOKENS:
            continue
        canonical_requested = token.lower()
        if canonical_requested in ignored:
            continue
        if canonical_requested in seen_requested:
            continue

        candidates: list[tuple[float, str, str]] = []
        for table_name, column_name, column_tokens in column_catalog:
            if token_forms & column_tokens:
                overlap = len(token_forms & column_tokens)
                score = float(overlap * 3)
                candidates.append((score, table_name, column_name))
                continue

            best_similarity = max(
                (
                    len(form) / max(len(column_name), 1)
                    if form in column_name.lower()
                    else 0.0
                    for form in token_forms
                ),
                default=0.0,
            )
            if best_similarity >= 0.35:
                candidates.append((best_similarity, table_name, column_name))

        if not candidates:
            continue

        candidates.sort(reverse=True)
        best_score = candidates[0][0]
        best_candidates = [candidate for candidate in candidates if candidate[0] == best_score]
        if len(best_candidates) != 1:
            continue
        second_score = candidates[1][0] if len(candidates) > 1 else 0.0
        if best_score < _SEMANTIC_MAPPING_MIN_SCORE and (best_score - second_score) < _SEMANTIC_MAPPING_MIN_MARGIN:
            continue
        if best_score < _SEMANTIC_MAPPING_MIN_SCORE:
            continue

        _, table_name, column_name = best_candidates[0]
        mappings.append(
            _build_mapping(
                requested=canonical_requested,
                matched_table=table_name,
                matched_column=column_name,
                status="mapped",
                reason="Deterministic fallback semantic token match.",
            )
        )
        seen_requested.add(canonical_requested)

    return mappings


def _infer_preferred_table_from_query(
    *,
    corrected_query: str,
    loaded_schema: LoadedUserSchema,
    current_mappings: list[ValidationMapping],
) -> str | None:
    scores: dict[str, int] = {}

    for mapping in current_mappings:
        table_name = str(mapping.get("matched_table", "")).strip()
        status = str(mapping.get("status", "")).strip().lower()
        if table_name and status in {"exact", "mapped"}:
            scores[table_name] = scores.get(table_name, 0) + 2

    query_lower = f" {str(corrected_query or '').lower()} "
    for table_name, columns in loaded_schema.schema["columns"].items():
        table_score = scores.get(table_name, 0)
        for column in columns:
            col_name = str(column.get("name", "")).strip().lower()
            if not col_name:
                continue
            variants = {col_name, col_name.replace("_", " ")}
            if any(f" {variant} " in query_lower for variant in variants):
                table_score += 1
        scores[table_name] = table_score

    if not scores:
        return None
    best_score = max(scores.values())
    if best_score <= 0:
        return None
    best_tables = sorted(table for table, score in scores.items() if score == best_score)
    if len(best_tables) != 1:
        return None
    return best_tables[0]


def build_deterministic_schema_validation_result(
    *,
    corrected_query: str,
    loaded_schema: LoadedUserSchema,
    ignored_terms: set[str] | None = None,
) -> SchemaValidationResult:
    mappings = _find_direct_schema_mentions(query=corrected_query, loaded_schema=loaded_schema)
    ignored = {str(term).strip().lower() for term in (ignored_terms or set()) if str(term).strip()}
    mappings = [
        mapping
        for mapping in mappings
        if str(mapping.get("requested", "")).strip().lower() not in ignored
    ]
    existing_requested = {str(mapping.get("requested", "")).strip().lower() for mapping in mappings}
    mappings.extend(
        _find_semantic_schema_mentions(
            query=corrected_query,
            loaded_schema=loaded_schema,
            existing_requested=existing_requested,
            ignored_terms=ignored,
        )
    )
    derivable_mappings: list[ValidationMapping] = []
    invalid_mappings: list[ValidationMapping] = []
    missing_column = ""

    normalized_query_tokens = set(
        re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(corrected_query or "").lower())
    )
    fallback_datetime_column = get_fallback_derivable_column(loaded_schema)

    for token in sorted(normalized_query_tokens):
        if token in ignored:
            continue
        if token not in _DERIVABLE_TIME_TERMS:
            continue

        if fallback_datetime_column is None:
            invalid_mappings.append(
                _build_mapping(
                    requested=token,
                    matched_table="",
                    matched_column="",
                    status="invalid",
                    reason="No datetime column is available for derivation.",
                )
            )
            missing_column = missing_column or token
            continue

        derivable_mappings.append(
            _build_mapping(
                requested=token,
                matched_table=fallback_datetime_column.table,
                matched_column=fallback_datetime_column.name,
                status="derivable",
                reason="Derived from available datetime schema column.",
            )
        )

    all_mappings = mappings + derivable_mappings
    return {
        "is_valid": not bool(invalid_mappings),
        "missing_column": missing_column,
        "mappings": all_mappings,
        "derivable_columns": derivable_mappings,
        "invalid_mappings": invalid_mappings,
    }


def validate_query_schema_usage(
    *,
    corrected_query: str,
    loaded_schema: LoadedUserSchema,
    config: HighPreprocessConfig,
    logger: logging.Logger,
    log_event: Callable[..., None],
) -> SchemaValidationResult:
    prompt = _build_validation_prompt(corrected_query=corrected_query, loaded_schema=loaded_schema)
    raw_output = _call_ollama(
        prompt=prompt,
        config=config,
        purpose="schema_validation",
        logger=logger,
        log_event=log_event,
    )
    payload = _extract_json_object(raw_output)

    raw_references = payload.get("references", [])
    if raw_references is None:
        raw_references = []
    if not isinstance(raw_references, list):
        raise PreprocessHighLLMError("Validation payload field 'references' must be an array.")

    valid_mappings: list[ValidationMapping] = []
    derivable_mappings: list[ValidationMapping] = []
    invalid_mappings: list[ValidationMapping] = []
    missing_column = ""
    preferred_table = _infer_preferred_table_from_query(
        corrected_query=corrected_query,
        loaded_schema=loaded_schema,
        current_mappings=[],
    )

    for item in raw_references:
        if not isinstance(item, dict):
            raise PreprocessHighLLMError("Validation reference item must be an object.")

        requested = str(item.get("requested", "")).strip()
        matched_table = str(item.get("matched_table", "")).strip()
        matched_column = str(item.get("matched_column", "")).strip()
        status = str(item.get("status", "invalid")).strip().lower()
        reason = str(item.get("reason", "")).strip()

        is_valid, resolved, invalid_column = _resolve_reference(
            loaded_schema=loaded_schema,
            requested=requested,
            matched_table=matched_table,
            matched_column=matched_column,
            status=status,
            reason=reason,
            preferred_table=preferred_table,
        )
        if not is_valid:
            missing_column = missing_column or invalid_column or "unknown"
            invalid_mappings.append(resolved)
            continue

        valid_mappings.append(resolved)
        if resolved["status"] == "derivable":
            derivable_mappings.append(resolved)

    if not valid_mappings:
        valid_mappings = _find_direct_schema_mentions(query=corrected_query, loaded_schema=loaded_schema)

    deterministic_result = build_deterministic_schema_validation_result(
        corrected_query=corrected_query,
        loaded_schema=loaded_schema,
    )

    # Use deterministic validation as authority so LLM-only false invalid references
    # (e.g., ranking/comparison words) do not block valid analytical queries.
    deterministic_invalid = list(deterministic_result.get("invalid_mappings", []) or [])
    deterministic_missing = str(deterministic_result.get("missing_column", "") or "").strip()
    deterministic_mappings = list(deterministic_result.get("mappings", []) or [])
    deterministic_derivable = list(deterministic_result.get("derivable_columns", []) or [])

    merged_mappings: list[ValidationMapping] = []
    seen_mapping_keys: set[tuple[str, str, str, str]] = set()

    for mapping in valid_mappings + deterministic_mappings:
        requested = str(mapping.get("requested", "")).strip()
        matched_table = str(mapping.get("matched_table", "")).strip()
        matched_column = str(mapping.get("matched_column", "")).strip()
        status = str(mapping.get("status", "")).strip().lower()
        key = (requested.lower(), matched_table.lower(), matched_column.lower(), status)
        if key in seen_mapping_keys:
            continue
        seen_mapping_keys.add(key)
        merged_mappings.append(mapping)

    merged_derivable: list[ValidationMapping] = []
    seen_derivable_keys: set[tuple[str, str, str, str]] = set()
    for mapping in derivable_mappings + deterministic_derivable:
        requested = str(mapping.get("requested", "")).strip()
        matched_table = str(mapping.get("matched_table", "")).strip()
        matched_column = str(mapping.get("matched_column", "")).strip()
        status = str(mapping.get("status", "")).strip().lower()
        key = (requested.lower(), matched_table.lower(), matched_column.lower(), status)
        if key in seen_derivable_keys:
            continue
        seen_derivable_keys.add(key)
        merged_derivable.append(mapping)

    if deterministic_invalid:
        return {
            "is_valid": False,
            "missing_column": deterministic_missing or missing_column or "unknown",
            "mappings": merged_mappings,
            "derivable_columns": merged_derivable,
            "invalid_mappings": deterministic_invalid,
        }

    # If still no explicit references, this query can proceed and downstream intent extraction
    # will infer schema usage from available metadata.
    log_event(
        logger,
        logging.INFO,
        "Schema validation completed",
        reference_count=len(merged_mappings),
        derivable_count=len(merged_derivable),
        schema_valid=True,
    )
    return {
        "is_valid": True,
        "missing_column": "",
        "mappings": merged_mappings,
        "derivable_columns": merged_derivable,
        "invalid_mappings": [],
    }

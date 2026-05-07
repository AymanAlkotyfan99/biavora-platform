from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher, get_close_matches
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from preprocessing_high.schema_loader import LoadedUserSchema
else:
    LoadedUserSchema = Any  # type: ignore[assignment]


_TIME_TERMS = {
    "year",
    "years",
    "month",
    "months",
    "day",
    "days",
    "week",
    "weeks",
    "quarter",
    "quarters",
    "date",
    "time",
    "hour",
    "hours",
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "yearly",
    "hourly",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
    "q1",
    "q2",
    "q3",
    "q4",
}

_STOP_WORDS = {
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
    "how",
    "many",
    "do",
    "we",
    "have",
    "had",
    "has",
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
    "is",
    "are",
    "was",
    "were",
    "as",
    "at",
    "into",
    "than",
    "then",
    "that",
    "which",
    "what",
    "who",
    "when",
    "does",
    "did",
    "it",
    "its",
    "evolve",
    "evolves",
    "evolving",
    "change",
    "changes",
    "changed",
    "from",
    "between",
    "or",
    "all",
    "overall",
    "compare",
    "comparison",
    "vs",
    "versus",
    "highest",
    "lowest",
    "largest",
    "smallest",
    "best",
    "worst",
    "ascending",
    "descending",
    "asc",
    "desc",
    "above",
    "below",
    "under",
    "over",
    "greater",
    "less",
    "equal",
    "equals",
    "where",
    "having",
    "contains",
    "like",
    "filter",
    "filters",
    "rank",
    "ranking",
    "first",
    "last",
    "trend",
    "trends",
    "relationship",
    "relationships",
    "together",
    "jointly",
    "alongside",
    "simultaneously",
    "concurrently",
    "visualize",
    "plot",
    "identify",
    "calculate",
    "compute",
    "find",
    "pie",
    "donut",
    "doughnut",
}

_TYPO_SCORE_THRESHOLD = 0.82
_TYPO_AMBIGUITY_MARGIN = 0.03
_COMPARISON_CONNECTORS = {
    "above",
    "below",
    "over",
    "under",
    "greater",
    "less",
    "more",
    "fewer",
    "equal",
    "equals",
    "between",
    "and",
    "where",
    "having",
    "is",
    "are",
}
_TOKEN_SYNONYMS = {
    "revenue": {"sales", "sale", "total_sales", "amount"},
    "sales": {"revenue", "sale", "total_sales"},
}

_SUPPORTED_TEMPORAL_PHRASES = (
    "over time",
    "across time",
    "through time",
)

_ANALYTICAL_LANGUAGE_TERMS = {
    "analysis",
    "analytical",
    "distribution",
    "distributed",
    "spread",
    "histogram",
    "frequency",
    "impact",
    "effect",
    "influence",
    "correlation",
    "insight",
    "insights",
    "pattern",
    "patterns",
    "relationship",
    "relationships",
    "change",
    "changes",
    "changed",
    "evolve",
    "evolves",
    "evolving",
    "trend",
    "trends",
    "variance",
    "variation",
    "value",
    "values",
    "activity",
    "contribution",
    "contribute",
    "contributes",
    "contributing",
    "share",
    "shares",
    "percentage",
    "percent",
    "ratio",
    "cumulative",
    "accumulated",
    "running",
    "line",
    "lines",
    "bar",
    "bars",
    "chart",
    "charts",
    "plot",
    "plots",
    "stack",
    "stacked",
    "combo",
    "mixed",
    "visualize",
    "visualized",
    "visualization",
    "identify",
    "identified",
    "calculate",
    "calculated",
    "calculating",
    "compute",
    "computed",
    "computing",
    "pie",
    "donut",
    "doughnut",
}

_CONVERSATIONAL_TERMS = {
    "hi",
    "hello",
    "hey",
    "ok",
    "okay",
    "thanks",
    "thank",
    "please",
}

_NON_SCHEMA_LANGUAGE_TERMS = (
    _STOP_WORDS
    | _ANALYTICAL_LANGUAGE_TERMS
    | _TIME_TERMS
    | _CONVERSATIONAL_TERMS
)

_NON_SCHEMA_LANGUAGE_TYPO_THRESHOLD = 0.82


def _supported_temporal_phrase_terms(query_text: str) -> set[str]:
    normalized_query = _normalize_phrase(query_text)
    terms: set[str] = set()
    for phrase in _SUPPORTED_TEMPORAL_PHRASES:
        if phrase in normalized_query:
            terms.update(phrase.split())
    return terms


def _is_analytical_language_term(term: str) -> bool:
    normalized = _normalize_phrase(term)
    if not normalized:
        return False
    return normalized in _ANALYTICAL_LANGUAGE_TERMS


def _is_non_schema_language_term(term: str) -> bool:
    normalized = _normalize_phrase(term)
    if not normalized:
        return False
    if normalized in _NON_SCHEMA_LANGUAGE_TERMS:
        return True
    if len(normalized) <= 2:
        return False

    # Treat typo-like variants of control/analytical language as non-schema
    # so they do not become false unresolved schema terms.
    candidates = get_close_matches(
        normalized,
        list(_NON_SCHEMA_LANGUAGE_TERMS),
        n=1,
        cutoff=_NON_SCHEMA_LANGUAGE_TYPO_THRESHOLD,
    )
    return bool(candidates)


def _is_non_schema_noise_term(term: str) -> bool:
    normalized = _normalize_phrase(term)
    if not normalized:
        return False
    if len(normalized) <= 2 and normalized not in {"id", "ds"}:
        # Ignore short conversational/garbage tokens (e.g., "pp", "ok")
        # unless they are common schema identifiers.
        return True
    # Ignore tokens made of a single repeated character sequence.
    if len(normalized) >= 2 and len(set(normalized)) == 1:
        return True
    return False


def _safe_singular_forms(value: str) -> list[str]:
    normalized = _normalize_phrase(value)
    if not normalized:
        return []
    forms: list[str] = []
    if normalized.endswith("ies") and len(normalized) > 4:
        forms.append(normalized[:-3] + "y")
    if (
        normalized.endswith("s")
        and len(normalized) > 3
        and not normalized.endswith(("ss", "us", "is", "ous"))
    ):
        forms.append(normalized[:-1])
    return forms


def _safe_plural_forms(value: str) -> list[str]:
    normalized = _normalize_phrase(value)
    if not normalized:
        return []
    if normalized.endswith(("s", "x", "z", "sh", "ch")):
        return []
    if normalized.endswith("y") and len(normalized) > 2 and normalized[-2] not in "aeiou":
        return [normalized[:-1] + "ies"]
    if normalized.endswith(("us", "is", "ss", "ous")):
        return []
    return [normalized + "s"]


def _normalize_phrase(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _schema_tables(loaded_schema: LoadedUserSchema) -> list[str]:
    tables = [str(table).strip() for table in loaded_schema.schema.get("tables", []) if str(table).strip()]
    return sorted(set(tables))


def _schema_columns_by_table(loaded_schema: LoadedUserSchema) -> dict[str, list[str]]:
    columns_by_table: dict[str, list[str]] = {}
    for table_name, table_columns in loaded_schema.schema.get("columns", {}).items():
        normalized_table = str(table_name).strip()
        if not normalized_table:
            continue
        columns_by_table.setdefault(normalized_table, [])
        for column in table_columns:
            column_name = str(column.get("name", "")).strip()
            if column_name:
                columns_by_table[normalized_table].append(column_name)
    return columns_by_table


def _column_lookup(columns_by_table: dict[str, list[str]]) -> dict[str, list[str]]:
    lookup: dict[str, list[str]] = defaultdict(list)
    for table_name, columns in columns_by_table.items():
        for column_name in columns:
            lookup[column_name.lower()].append(table_name)
    return lookup


def _column_token_lookup(columns_by_table: dict[str, list[str]]) -> dict[str, list[str]]:
    lookup: dict[str, list[str]] = defaultdict(list)
    for table_name, columns in columns_by_table.items():
        for column_name in columns:
            tokens = re.findall(r"[a-z0-9]+", str(column_name).lower().replace("_", " "))
            for token in tokens:
                if len(token) <= 1:
                    continue
                lookup[token].append(f"{table_name}:{column_name}")
                for synonym in _TOKEN_SYNONYMS.get(token, set()):
                    if len(str(synonym)) <= 1:
                        continue
                    lookup[str(synonym)].append(f"{table_name}:{column_name}")
    return lookup


def _column_alias_lookup(columns_by_table: dict[str, list[str]]) -> dict[str, list[tuple[str, str]]]:
    alias_lookup: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for table_name, columns in columns_by_table.items():
        for column_name in columns:
            canonical = column_name.lower()
            aliases = {canonical, _normalize_phrase(column_name)}
            for alias in aliases:
                if alias:
                    alias_lookup[alias].append((table_name, column_name))
    return alias_lookup


def _extract_explicit_column_matches(
    *,
    query_text: str,
    alias_lookup: dict[str, list[tuple[str, str]]],
) -> list[dict[str, str]]:
    normalized_query = f" {_normalize_phrase(query_text)} "
    matches: list[dict[str, str]] = []
    seen_columns: set[str] = set()
    sorted_aliases = sorted(alias_lookup.keys(), key=lambda item: len(item.split()), reverse=True)

    for alias in sorted_aliases:
        if not alias:
            continue
        if f" {alias} " not in normalized_query:
            continue
        alias_candidates = alias_lookup.get(alias, [])
        if not alias_candidates:
            continue
        table_name, column_name = alias_candidates[0]
        dedupe_key = f"{table_name}:{column_name.lower()}"
        if dedupe_key in seen_columns:
            continue
        seen_columns.add(dedupe_key)
        matches.append(
            {
                "term": alias,
                "matched_table": table_name,
                "matched_column": column_name,
            }
        )
    return matches


def _extract_residual_terms(
    *,
    query_text: str,
    explicit_matches: list[dict[str, str]],
    ignored_terms: set[str] | None = None,
) -> list[str]:
    matched_tokens: set[str] = set()
    for item in explicit_matches:
        term = _normalize_phrase(item.get("term", ""))
        if not term:
            continue
        matched_tokens.update(term.split())

    raw_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(query_text or "").lower())
    residual: list[str] = []
    seen: set[str] = set()
    ignored = {str(term).strip().lower() for term in (ignored_terms or set()) if str(term).strip()}
    for token in raw_tokens:
        if token in _STOP_WORDS or token in ignored or len(token) <= 1:
            continue

        token_parts = _normalize_phrase(token).split()
        if token_parts and all(part in matched_tokens for part in token_parts):
            continue

        if token in seen:
            continue
        seen.add(token)
        residual.append(token)
    return residual


def _extract_literal_filter_terms(query_text: str) -> set[str]:
    query_lower = str(query_text or "").lower()
    literals: set[str] = set()

    patterns = [
        r"\bin\s+the\s+([a-z0-9_ -]+?)\s+[a-z_][a-z0-9_ ]+?(?:\b|$)",
        r"\b(?:where|with|having)\s+[a-z_][a-z0-9_ ]+?\s+(?:is|equals|equal to|=)\s+['\"]?([a-z0-9_ -]+?)['\"]?(?:\b|$)",
        r"\b[a-z_][a-z0-9_ ]+?\s+contains\s+['\"]?([a-z0-9_ -]+?)['\"]?(?:\b|$)",
        r"\b[a-z_][a-z0-9_ ]+?\s+like\s+['\"]?([a-z0-9_ -%]+?)['\"]?(?:\b|$)",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, query_lower):
            value = str(match.group(1) or "").strip().strip("'\"")
            for token in re.findall(r"[a-z_][a-z0-9_]*", value):
                if token:
                    literals.add(token)

    for token in re.findall(r"\b\d+(?:\.\d+)?\b", query_lower):
        literals.add(token)

    for token in _COMPARISON_CONNECTORS:
        literals.add(token)

    return literals


def _best_typo_candidate(
    *,
    term: str,
    column_lookup: dict[str, list[str]],
) -> tuple[str, float, bool]:
    normalized_term = _normalize_phrase(term)
    if not normalized_term:
        return "", 0.0, False

    singular_forms = _safe_singular_forms(normalized_term)
    for singular in singular_forms:
        if singular in column_lookup:
            return singular, 0.99, False

    scored: list[tuple[float, str]] = []
    for column_name in column_lookup.keys():
        candidate = _normalize_phrase(column_name)
        if not candidate:
            continue
        score = SequenceMatcher(None, normalized_term, candidate).ratio()
        scored.append((score, column_name))

    if not scored:
        return "", 0.0, False

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_column = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    ambiguous = (best_score - second_score) <= _TYPO_AMBIGUITY_MARGIN
    return best_column, best_score, ambiguous


def _has_any_datetime_columns(loaded_schema: LoadedUserSchema) -> bool:
    if loaded_schema.date_columns_by_name:
        return True

    # Heuristic fallback: some datasets store date keys (e.g., `ds`) as String.
    # Treat clearly date-like column names as temporal-capable for diagnostics.
    date_like_tokens = {"date", "day", "week", "month", "quarter", "year", "time", "timestamp"}
    for table_columns in loaded_schema.schema.get("columns", {}).values():
        for column in table_columns:
            column_name = str(column.get("name", "")).strip().lower()
            if not column_name:
                continue
            if column_name == "ds":
                return True
            tokens = set(re.findall(r"[a-z0-9]+", column_name.replace("_", " ")))
            if tokens & date_like_tokens:
                return True
    return False


def _mapping_resolution_map(mappings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for mapping in mappings:
        requested_raw = str(mapping.get("requested", "")).strip()
        requested = requested_raw.lower()
        normalized_requested = _normalize_phrase(requested_raw)
        if not requested and not normalized_requested:
            continue
        requested_aliases: set[str] = set()
        if requested:
            requested_aliases.add(requested)
        if normalized_requested:
            requested_aliases.add(normalized_requested)
        for alias in list(requested_aliases):
            requested_aliases.update(_safe_singular_forms(alias))
            requested_aliases.update(_safe_plural_forms(alias))
        for alias in requested_aliases:
            if alias:
                lookup[alias] = mapping
    return lookup


def _selected_table_for_matches(
    *,
    schema_tables: list[str],
    columns_by_table: dict[str, list[str]],
    matched_columns: list[str],
) -> tuple[str, list[str], list[str], dict[str, int]]:
    if not schema_tables:
        return "", [], [], {}

    table_scores: dict[str, int] = {table: 0 for table in schema_tables}
    for column_name in matched_columns:
        normalized_column = str(column_name or "").strip().lower()
        if not normalized_column:
            continue
        for table_name, columns in columns_by_table.items():
            if any(normalized_column == str(col).strip().lower() for col in columns):
                table_scores[table_name] = table_scores.get(table_name, 0) + 1

    best_score = max(table_scores.values(), default=0)
    if best_score <= 0:
        return "", [], [], table_scores

    candidate_tables = sorted(
        [table for table, score in table_scores.items() if score == best_score]
    )
    selected_table = candidate_tables[0] if len(candidate_tables) == 1 else ""

    selected_columns = [
        column_name
        for column_name in matched_columns
        if any(
            str(column_name).strip().lower() == str(col).strip().lower()
            for col in columns_by_table.get(selected_table, [])
        )
    ]
    deduped_selected_columns: list[str] = []
    seen: set[str] = set()
    for column_name in selected_columns:
        normalized = str(column_name).strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped_selected_columns.append(column_name)

    return selected_table, deduped_selected_columns, candidate_tables, table_scores


def build_schema_resolution_diagnostics(
    *,
    original_query: str,
    corrected_query: str,
    loaded_schema: LoadedUserSchema,
    validation_result: dict[str, Any] | None,
    ignored_terms: set[str] | None = None,
) -> dict[str, Any]:
    validation_payload = validation_result or {}
    mappings = validation_payload.get("mappings", []) if isinstance(validation_payload.get("mappings", []), list) else []
    invalid_mappings = (
        validation_payload.get("invalid_mappings", [])
        if isinstance(validation_payload.get("invalid_mappings", []), list)
        else []
    )
    mapping_lookup = _mapping_resolution_map(mappings + invalid_mappings)

    schema_tables = _schema_tables(loaded_schema)
    columns_by_table = _schema_columns_by_table(loaded_schema)
    column_lookup = _column_lookup(columns_by_table)
    column_token_lookup = _column_token_lookup(columns_by_table)
    alias_lookup = _column_alias_lookup(columns_by_table)

    explicit_matches = _extract_explicit_column_matches(query_text=original_query, alias_lookup=alias_lookup)
    supported_temporal_terms = _supported_temporal_phrase_terms(original_query)
    residual_terms = _extract_residual_terms(
        query_text=original_query,
        explicit_matches=explicit_matches,
        ignored_terms=(
            _extract_literal_filter_terms(original_query)
            | set(ignored_terms or set())
            | supported_temporal_terms
        ),
    )

    term_resolutions: list[dict[str, Any]] = []
    unresolved_schema_terms: list[str] = []
    unresolved_lexical_terms: list[str] = []
    unsupported_terms: list[str] = []
    candidate_columns: dict[str, list[str]] = {}
    matched_columns: list[str] = []

    for explicit in explicit_matches:
        term_resolutions.append(
            {
                "term": explicit["term"],
                "resolution_status": "exact_match",
                "matched_column": explicit["matched_column"],
                "reason": "Exact schema column mention found in query.",
            }
        )
        matched_columns.append(explicit["matched_column"])

    for term in residual_terms:
        normalized_term = _normalize_phrase(term)
        if not normalized_term:
            continue

        mapped = mapping_lookup.get(term) or mapping_lookup.get(normalized_term)
        if mapped:
            status = str(mapped.get("status", "")).strip().lower()
            matched_column = str(mapped.get("matched_column", "")).strip()
            requested = str(mapped.get("requested", "")).strip() or term
            if status == "exact" and matched_column:
                term_resolutions.append(
                    {
                        "term": requested,
                        "resolution_status": "exact_match",
                        "matched_column": matched_column,
                        "reason": mapped.get("reason") or "Exact schema match.",
                    }
                )
                matched_columns.append(matched_column)
                continue
            if status == "mapped" and matched_column:
                mapped_column_exists = bool(column_lookup.get(matched_column.lower(), []))
                if mapped_column_exists:
                    candidate_column, score, ambiguous = _best_typo_candidate(
                        term=requested,
                        column_lookup=column_lookup,
                    )
                    if (
                        candidate_column
                        and candidate_column.lower() == matched_column.lower()
                        and score >= _TYPO_SCORE_THRESHOLD
                        and not ambiguous
                    ):
                        resolution_status = "corrected_typo"
                        resolved_reason = mapped.get("reason") or f"Typo corrected (score={score:.2f})."
                    else:
                        resolution_status = "semantic_match"
                        resolved_reason = mapped.get("reason") or "Mapped to semantically equivalent schema column."

                    term_resolutions.append(
                        {
                            "term": requested,
                            "resolution_status": resolution_status,
                            "matched_column": matched_column,
                            "reason": resolved_reason,
                        }
                    )
                    matched_columns.append(matched_column)
                    continue

                candidate_column, score, ambiguous = _best_typo_candidate(
                    term=requested,
                    column_lookup=column_lookup,
                )
                if (
                    candidate_column
                    and candidate_column.lower() == matched_column.lower()
                    and score >= _TYPO_SCORE_THRESHOLD
                    and not ambiguous
                ):
                    term_resolutions.append(
                        {
                            "term": requested,
                            "resolution_status": "corrected_typo",
                            "matched_column": matched_column,
                            "reason": mapped.get("reason") or f"Typo corrected (score={score:.2f}).",
                        }
                    )
                    matched_columns.append(matched_column)
                    continue

            if status == "derivable" and matched_column:
                term_resolutions.append(
                    {
                        "term": requested,
                        "resolution_status": "derived_time_dimension",
                        "matched_column": matched_column,
                        "reason": mapped.get("reason") or "Derived from datetime schema column.",
                    }
                )
                matched_columns.append(matched_column)
                continue

        if normalized_term in _TIME_TERMS:
            if _has_any_datetime_columns(loaded_schema):
                term_resolutions.append(
                    {
                        "term": term,
                        "resolution_status": "analytical_language",
                        "matched_column": "",
                        "reason": "Supported temporal analytical language.",
                    }
                )
                continue
            unsupported_terms.append(term)
            term_resolutions.append(
                {
                    "term": term,
                    "resolution_status": "unsupported_for_current_schema",
                    "matched_column": "",
                    "reason": "No Date/DateTime column exists to support this time dimension.",
                }
            )
            continue

        if normalized_term in alias_lookup and alias_lookup[normalized_term]:
            _, matched_column = alias_lookup[normalized_term][0]
            term_resolutions.append(
                {
                    "term": term,
                    "resolution_status": "exact_match",
                    "matched_column": matched_column,
                    "reason": "Exact schema column match.",
                }
            )
            matched_columns.append(matched_column)
            continue

        semantic_candidates = column_token_lookup.get(normalized_term, [])
        if semantic_candidates:
            distinct_columns = sorted(
                {candidate.split(":", 1)[1] for candidate in semantic_candidates if ":" in candidate}
            )
            if len(distinct_columns) == 1:
                matched_column = distinct_columns[0]
                term_resolutions.append(
                    {
                        "term": term,
                        "resolution_status": "semantic_match",
                        "matched_column": matched_column,
                        "reason": "Matched schema column token semantically.",
                    }
                )
                matched_columns.append(matched_column)
                continue
            term_resolutions.append(
                {
                    "term": term,
                    "resolution_status": "analytical_language",
                    "matched_column": "",
                    "reason": "Token maps to multiple schema columns; treated as broad analytical language.",
                }
            )
            continue

        candidate_column, score, ambiguous = _best_typo_candidate(term=term, column_lookup=column_lookup)
        if candidate_column and score >= _TYPO_SCORE_THRESHOLD and not ambiguous:
            term_resolutions.append(
                {
                    "term": term,
                    "resolution_status": "corrected_typo",
                    "matched_column": candidate_column,
                    "reason": f"Typo corrected to '{candidate_column}' (score={score:.2f}).",
                }
            )
            matched_columns.append(candidate_column)
            continue

        if _is_non_schema_language_term(term) or _is_analytical_language_term(term):
            term_resolutions.append(
                {
                    "term": term,
                    "resolution_status": "analytical_language",
                    "matched_column": "",
                    "reason": "Generic analytical wording; not treated as a schema reference.",
                }
            )
            continue

        if _is_non_schema_noise_term(term):
            term_resolutions.append(
                {
                    "term": term,
                    "resolution_status": "analytical_language",
                    "matched_column": "",
                    "reason": "Non-schema conversational/noise token ignored.",
                }
            )
            continue

        unresolved_lexical_terms.append(term)
        candidate_columns[term] = [
            candidate
            for candidate in get_close_matches(normalized_term, list(column_lookup.keys()), n=3, cutoff=0.5)
        ]
        unresolved_schema_terms.append(term)
        term_resolutions.append(
            {
                "term": term,
                "resolution_status": "unresolved_schema_reference",
                "matched_column": "",
                "reason": "No valid schema column matches this term.",
            }
        )

    selected_table, selected_columns, candidate_tables, table_scores = _selected_table_for_matches(
        schema_tables=schema_tables,
        columns_by_table=columns_by_table,
        matched_columns=matched_columns,
    )

    schema_validation_status = "valid"
    if unresolved_schema_terms:
        schema_validation_status = "invalid_unresolved_terms"
    elif unsupported_terms:
        schema_validation_status = "invalid_unsupported_terms"
    elif not validation_payload.get("is_valid", True):
        schema_validation_status = "invalid_unresolved_terms"

    return {
        "original_terms": residual_terms,
        "corrected_terms": _extract_residual_terms(
            query_text=corrected_query,
            explicit_matches=_extract_explicit_column_matches(
                query_text=corrected_query,
                alias_lookup=alias_lookup,
            ),
            ignored_terms=(
                _extract_literal_filter_terms(corrected_query)
                | set(ignored_terms or set())
                | _supported_temporal_phrase_terms(corrected_query)
            ),
        ),
        "unresolved_terms": sorted(set(unresolved_schema_terms)),
        "unresolved_lexical_terms": sorted(set(unresolved_lexical_terms)),
        "unsupported_terms": sorted(set(unsupported_terms)),
        "term_resolutions": term_resolutions,
        "candidate_columns": candidate_columns,
        "candidate_tables": candidate_tables,
        "selected_table": selected_table,
        "selected_columns": selected_columns,
        "table_match_scores": table_scores,
        "selected_table_match_score": table_scores.get(selected_table, 0) if selected_table else 0,
        "schema_adjustments": mappings,
        "schema_validation_status": schema_validation_status,
    }

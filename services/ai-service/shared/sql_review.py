"""SQL review and correction stage (Phase 6 / CRIT-04 + CRIT-05).

Phase 6 of the audit hardens this module against three classes of bug:

1. **Predictive duplication** – the local ``_PREDICTIVE_PATTERNS`` tuple has
   been removed; the canonical detector at
   ``bi_platform_shared.predictive.detector.is_predictive`` is now the only
   place those patterns live.
2. **LLM SQL safety** – every variant of LLM-corrected SQL is validated via
   ``query-service /query/validate/`` (already centralised in CRIT-04). If
   that validation fails OR the SQL is misaligned with the validated IR,
   we fall back to the compiler SQL instead of raising an exception that
   would tear the pipeline down.
3. **Tenant qualification** – the LLM never sees a bare table name; the
   compiler now emits per-tenant qualified FROMs and the alignment check
   accepts both qualified and unqualified forms so a faithful LLM rewrite
   does not get rejected just for repeating the qualifier.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Tuple

import requests

from bi_platform_shared.http import HttpClientError, get_default_client
from bi_platform_shared.predictive.detector import is_predictive


logger = logging.getLogger(__name__)


_VALIDATION_CACHE: dict[str, tuple[bool, str]] = {}

_validation_workspace_id_var: ContextVar[str] = ContextVar("_validation_workspace_id", default="")
_validation_bearer_token_var: ContextVar[str] = ContextVar("_validation_bearer_token", default="")
_query_service_auth_status_var: ContextVar[str] = ContextVar("_query_service_auth_status", default="")


def get_last_query_service_auth_status() -> str:
    """Auth outcome of the most recent query-service validate call (for pipeline trace)."""

    return str(_query_service_auth_status_var.get() or "").strip()


def _set_query_service_auth_status(value: str) -> None:
    _query_service_auth_status_var.set(str(value or "").strip())


@contextmanager
def query_validate_request_context(*, workspace_id: str, bearer_token: str) -> Iterator[None]:
    """Bind workspace_id and Bearer token for nested :func:`validate_sql` / ``_query_service_validate`` calls."""

    token = str(bearer_token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    wid_reset = _validation_workspace_id_var.set(str(workspace_id or "").strip())
    tok_reset = _validation_bearer_token_var.set(token)
    try:
        yield
    finally:
        _validation_workspace_id_var.reset(wid_reset)
        _validation_bearer_token_var.reset(tok_reset)


def _validation_workspace_id() -> str:
    return str(_validation_workspace_id_var.get() or "").strip()


def _validation_bearer_token() -> str:
    return str(_validation_bearer_token_var.get() or "").strip()


def bind_query_service_validation_for_pipeline(*, workspace_id: str, bearer_token: str) -> Tuple[Any, Any]:
    """Set validation ContextVars; pair with :func:`reset_query_service_validation_for_pipeline`."""

    token = str(bearer_token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return (
        _validation_workspace_id_var.set(str(workspace_id or "").strip()),
        _validation_bearer_token_var.set(token),
    )


def reset_query_service_validation_for_pipeline(handles: Tuple[Any, Any]) -> None:
    _validation_workspace_id_var.reset(handles[0])
    _validation_bearer_token_var.reset(handles[1])


def _query_service_validate(sql: str) -> tuple[bool, str]:
    """Call query-service /query/validate/ and cache for the pipeline run.

    The cache is keyed on the SHA-256 of the SQL so the same compiler-emitted
    SQL is not re-validated multiple times within one pipeline run.
    """

    if not sql:
        return False, "sql is empty"
    sql_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    cached = _VALIDATION_CACHE.get(sql_hash)
    if cached is not None:
        return cached

    endpoint = f"{os.getenv('QUERY_SERVICE_URL', 'http://query-service:8006').rstrip('/')}/query/validate/"
    workspace_id = _validation_workspace_id() or str(os.getenv("QUERY_SERVICE_WORKSPACE_ID", "") or "").strip()
    ctx_bearer = _validation_bearer_token()
    from shared.query_service_auth import bearer_matches_configured_internal_secret, require_query_service_bearer_token

    bearer = str(ctx_bearer or "").strip()
    if not bearer:
        try:
            bearer = require_query_service_bearer_token()
        except RuntimeError as exc:
            _set_query_service_auth_status("auth_not_configured")
            logger.error(
                "query_service_validate_missing_auth",
                extra={"hint": str(exc)},
            )
            _VALIDATION_CACHE[sql_hash] = (False, "query_service_auth_not_configured")
            return False, "query_service_auth_not_configured"
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bearer}",
    }
    if bearer_matches_configured_internal_secret(bearer):
        headers["X-Internal-Service"] = "ai-service"
    payload: dict[str, Any] = {"sql": sql}
    if workspace_id:
        payload["workspace_id"] = workspace_id
    if not workspace_id:
        logger.warning(
            "query_service_validate_missing_workspace",
            extra={"hint": "Set QUERY_SERVICE_WORKSPACE_ID or query_validate_request_context(workspace_id=...)."},
        )
    try:
        response = get_default_client().post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=(5.0, float(os.getenv("AI_SERVICE_QUERY_VALIDATE_TIMEOUT", "15"))),
            attach_internal_api_key=False,
            request_id=str(uuid.uuid4()),
        )
    except HttpClientError as exc:
        logger.warning("query_service_validate_unreachable", extra={"error": str(exc)})
        return False, "query_service_unreachable"
    if response.status_code in (401, 403):
        err_txt = ""
        try:
            err_json = response.json()
            err_txt = str(err_json.get("error") or err_json.get("detail") or err_json or "")
        except ValueError:
            err_txt = (response.text or "")[:500]
        lowered = err_txt.lower()
        if response.status_code == 401 or (
            "database_mismatch" not in lowered
            and "cross_db" not in lowered
            and (
                "token" in lowered
                or "auth" in lowered
                or "not authenticated" in lowered
                or "credentials" in lowered
                or "permission denied" in lowered
            )
        ):
            _set_query_service_auth_status("auth_invalid")
            return False, "query_service_unauthorized"
    if response.status_code >= 500:
        _set_query_service_auth_status("auth_success")
        return False, f"query_service_error:{response.status_code}"
    try:
        body = response.json()
    except ValueError:
        _set_query_service_auth_status("auth_success")
        return False, "query_service_invalid_response"
    ok = bool(body.get("is_valid") or body.get("safe") or body.get("success"))
    msg = str(body.get("error") or body.get("message") or ("validation_passed" if ok else "sql_rejected"))
    _set_query_service_auth_status("auth_success")
    _VALIDATION_CACHE[sql_hash] = (ok, msg)
    return ok, msg


def validate_sql(sql: str) -> None:
    """Replacement for the deleted regex-based shared.sql_validator.validate_sql.

    The single source of SQL safety truth is now query-service. Callers that
    used to rely on the in-process regex check now ask query-service over
    HTTP. ``ValueError`` is preserved as the failure type so existing call
    sites do not need to change their except-clauses.
    """

    ok, msg = _query_service_validate(sql or "")
    if not ok:
        raise ValueError(msg)


_TOP_N_PATTERN = re.compile(r"\b(top|bottom)\s+(\d+)\b", flags=re.IGNORECASE)
_GROUPING_PATTERN = re.compile(r"\b(by|per|across|for each|in each)\b", flags=re.IGNORECASE)
_AGGREGATION_PATTERN = re.compile(r"\b(sum|avg|average|count|min|max|total)\b", flags=re.IGNORECASE)
_LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+)\b", flags=re.IGNORECASE)
_ORDER_PATTERN = re.compile(r"\bORDER\s+BY\b", flags=re.IGNORECASE)
_GROUP_BY_PATTERN = re.compile(r"\bGROUP\s+BY\b", flags=re.IGNORECASE)
_FROM_PATTERN = re.compile(r"\bFROM\s+([a-zA-Z0-9_.]+)\b", flags=re.IGNORECASE)
_BUSINESS_METRIC_COLUMNS = ("customers", "orders", "sales", "total_sales", "revenue", "quantity", "amount")
_ROW_COUNT_PATTERNS = (
    r"\bnumber of rows\b",
    r"\bnumber of records\b",
    r"\bcount of (?:rows|records|entries|transactions|days|weeks|items)\b",
    r"\bhow many (?:rows|records|entries|transactions|days|weeks|items)\b",
)
# Phase 6 / CRIT-06: predictive detection now flows through
# ``bi_platform_shared.predictive.detector.is_predictive`` so this module
# does not maintain its own local pattern list.


@dataclass(frozen=True)
class SqlReviewConfig:
    provider: str
    ollama_url: str
    ollama_model: str
    timeout_seconds: float
    enabled: bool

    @classmethod
    def from_env(cls) -> "SqlReviewConfig":
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
        default_ollama_url = f"{ollama_host.rstrip('/')}/api/generate"
        from shared.ollama_env import global_ollama_read_timeout_seconds

        default_timeout = global_ollama_read_timeout_seconds()
        raw_timeout = os.getenv("SQL_REVIEW_TIMEOUT_SECONDS")
        if raw_timeout is not None and str(raw_timeout).strip():
            try:
                timeout_seconds = float(raw_timeout)
            except ValueError:
                timeout_seconds = default_timeout
        else:
            timeout_seconds = default_timeout
        return cls(
            provider=os.getenv("SQL_REVIEW_PROVIDER", "openrouter").strip().lower(),
            ollama_url=os.getenv("SQL_REVIEW_OLLAMA_URL", default_ollama_url).strip(),
            ollama_model=os.getenv("SQL_REVIEW_OLLAMA_MODEL", "gemma3:1b").strip(),
            timeout_seconds=max(1.0, timeout_seconds),
            enabled=str(os.getenv("SQL_REVIEW_ENABLED", "true")).strip().lower() not in {"0", "false", "no"},
        )


def _schema_to_prompt(schema: dict[str, list[dict[str, Any]]]) -> str:
    rows: list[str] = []
    for table_name, columns in schema.items():
        rows.append(f"Table: {table_name}")
        for column in columns:
            rows.append(f"- {column.get('name', '')} ({column.get('type', '')})")
    return "\n".join(rows)


def _build_review_prompt(
    *,
    question: str,
    normalized_question: str,
    schema: dict[str, list[dict[str, Any]]],
    selected_table: str,
    selected_columns: list[str],
    chart_contract: dict[str, Any] | None,
    generated_sql: str,
    validated_intent: dict[str, Any] | None,
    extracted_intent: dict[str, Any] | None,
) -> str:
    return (
        "You are a SQL review and correction engine for BI analytics.\n"
        "Task: verify whether SQL answers the user question using the provided schema.\n"
        "You may correct SQL, but must keep semantics aligned with the question.\n\n"
        "STRICT SAFETY RULES (NON-NEGOTIABLE):\n"
        "- You must produce READ-ONLY SQL only.\n"
        "- Allowed query style: SELECT or WITH ... SELECT.\n"
        "- Forbidden: DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE, CREATE, REPLACE, MERGE, GRANT, REVOKE.\n"
        "- Never output multiple statements.\n\n"
        "Return JSON only with this exact shape:\n"
        "{\n"
        '  "status": "approved|corrected|rejected",\n'
        '  "sql": "single SQL statement",\n'
        '  "reason_category": "alignment|schema|safety|syntax|other",\n'
        '  "notes": ["short note 1", "short note 2"]\n'
        "}\n\n"
        f"Original question:\n{question}\n\n"
        f"Normalized question:\n{normalized_question}\n\n"
        f"Selected table:\n{selected_table}\n\n"
        f"Selected columns:\n{json.dumps(selected_columns, ensure_ascii=True)}\n\n"
        f"Schema:\n{_schema_to_prompt(schema)}\n\n"
        f"Extracted intent:\n{json.dumps(extracted_intent or {}, ensure_ascii=True)}\n\n"
        f"Validated intent:\n{json.dumps(validated_intent or {}, ensure_ascii=True)}\n\n"
        f"Chart contract:\n{json.dumps(chart_contract or {}, ensure_ascii=True)}\n\n"
        f"Generated SQL:\n{generated_sql}\n\n"
        "JSON response:"
    )


def _parse_json_payload(raw_output: str) -> dict[str, Any]:
    if not raw_output:
        raise ValueError("SQL review model returned empty output")
    start = raw_output.find("{")
    end = raw_output.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("SQL review model did not return JSON")
    parsed = json.loads(raw_output[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("SQL review model returned invalid JSON object")
    return parsed


def _call_openrouter(prompt: str) -> str:
    from llm_app.llm_client import call_llm

    return call_llm(prompt)


def _call_ollama(prompt: str, config: SqlReviewConfig) -> str:
    payload = {"model": config.ollama_model, "prompt": prompt, "stream": False}
    try:
        response = get_default_client().post(
            config.ollama_url,
            json=payload,
            timeout=(min(5.0, float(config.timeout_seconds)), float(config.timeout_seconds)),
            attach_internal_api_key=False,
        )
    except HttpClientError as exc:
        raise requests.RequestException(str(exc)) from exc
    response.raise_for_status()
    body = response.json()
    return str(body.get("response", "")).strip()


def _deterministic_review(question: str, generated_sql: str) -> dict[str, Any]:
    sql = str(generated_sql or "").strip()
    if not sql:
        return {
            "status": "rejected",
            "sql": "",
            "reason_category": "syntax",
            "notes": ["Generated SQL is empty."],
        }

    notes: list[str] = []
    question_lower = question.lower()
    sql_upper = sql.upper()
    match = _TOP_N_PATTERN.search(question_lower)
    if match:
        expected_limit = int(match.group(2))
        limit_match = _LIMIT_PATTERN.search(sql_upper)
        if not limit_match:
            notes.append(f"Expected LIMIT {expected_limit} for top/bottom request.")
        elif int(limit_match.group(1)) != expected_limit:
            notes.append(f"LIMIT mismatch: expected {expected_limit}.")
        if not _ORDER_PATTERN.search(sql_upper):
            notes.append("Top/bottom request should include ORDER BY.")

    if _AGGREGATION_PATTERN.search(question_lower) and _GROUPING_PATTERN.search(question_lower):
        if not _GROUP_BY_PATTERN.search(sql_upper):
            notes.append("Grouped analytical question should include GROUP BY.")

    if notes:
        return {
            "status": "rejected",
            "sql": sql,
            "reason_category": "alignment",
            "notes": notes,
        }
    return {
        "status": "approved",
        "sql": sql,
        "reason_category": "alignment",
        "notes": ["Deterministic SQL review passed."],
    }


def _sql_mentions_token(sql_upper: str, token: str) -> bool:
    token_upper = str(token or "").strip().upper()
    if not token_upper:
        return False
    return re.search(rf"\b{re.escape(token_upper)}\b", sql_upper) is not None


def _validate_sql_against_intent(sql: str, validated_intent: dict[str, Any] | None) -> list[str]:
    if not validated_intent or not isinstance(validated_intent, dict):
        return []

    notes: list[str] = []
    sql_upper = str(sql or "").upper()

    expected_table = str(validated_intent.get("table", "")).strip()
    from_match = _FROM_PATTERN.search(sql)
    if expected_table and from_match:
        actual_from = from_match.group(1).strip()
        expected_candidates = {expected_table.lower(), expected_table.split(".")[-1].lower()}
        actual_candidates = {actual_from.lower(), actual_from.split(".")[-1].lower()}
        if expected_candidates.isdisjoint(actual_candidates):
            notes.append(f"Reviewed SQL changed target table from '{expected_table}' to '{actual_from}'.")

    order_by = validated_intent.get("order_by") or []
    if order_by:
        if not _ORDER_PATTERN.search(sql_upper):
            notes.append("Reviewed SQL dropped ORDER BY required by intent.")
        for order_item in order_by:
            if not isinstance(order_item, dict):
                continue
            column = str(order_item.get("column", "")).strip()
            if column and not _sql_mentions_token(sql_upper, column):
                notes.append(f"Reviewed SQL is missing ORDER BY reference '{column}'.")

    limit = validated_intent.get("limit")
    if isinstance(limit, int) and limit > 0:
        limit_match = _LIMIT_PATTERN.search(sql_upper)
        if not limit_match:
            notes.append(f"Reviewed SQL dropped LIMIT {limit} required by intent.")
        elif int(limit_match.group(1)) != limit:
            notes.append(f"Reviewed SQL changed LIMIT from {limit} to {limit_match.group(1)}.")

    metrics = validated_intent.get("metrics") or []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        alias = str(metric.get("alias", "")).strip()
        column = str(metric.get("column", "")).strip()
        if alias and _sql_mentions_token(sql_upper, alias):
            continue
        if column and column != "*" and not _sql_mentions_token(sql_upper, column):
            notes.append(f"Reviewed SQL is missing metric reference '{column}'.")

    filters = validated_intent.get("filters") or []
    for filter_item in filters:
        if not isinstance(filter_item, dict):
            continue
        column = str(filter_item.get("column", "")).strip()
        if column and not _sql_mentions_token(sql_upper, column):
            notes.append(f"Reviewed SQL is missing filter reference '{column}'.")

    dimensions = [str(dim).strip() for dim in (validated_intent.get("dimensions") or []) if str(dim).strip()]
    has_aggregated_metric = any(
        isinstance(metric, dict) and str(metric.get("aggregation", "")).strip()
        for metric in metrics
    )
    if dimensions and has_aggregated_metric:
        if not _GROUP_BY_PATTERN.search(sql_upper):
            notes.append("Reviewed SQL dropped GROUP BY required by grouped intent.")
        for dimension in dimensions:
            if not _sql_mentions_token(sql_upper, dimension):
                notes.append(f"Reviewed SQL is missing grouped dimension '{dimension}'.")

    return notes


def _is_row_count_request(question: str) -> bool:
    normalized = str(question or "").strip().lower()
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in _ROW_COUNT_PATTERNS)


def _is_predictive_question(question: str) -> bool:
    """Phase 6 / CRIT-06: delegate to the canonical shared detector."""

    normalized = str(question or "").strip().lower()
    if not normalized:
        return False
    return bool(is_predictive(normalized))


def _normalize_clickhouse_date_casts(sql: str) -> str:
    normalized = str(sql or "").strip()
    if not normalized:
        return normalized
    previous = ""
    while normalized != previous:
        previous = normalized
        normalized = re.sub(
            r"toDate\(\s*toDate\(\s*([^)]+?)\s*\)\s*\)",
            r"toDate(\1)",
            normalized,
            flags=re.IGNORECASE,
        )
    def _rewrite_ambiguous_to_date(match: re.Match[str]) -> str:
        column_expr = str(match.group(1) or "").strip()
        lowered = column_expr.lower()
        if lowered in {"ds", "date", "period"} or lowered.endswith("_date"):
            return (
                "toDate("
                f"coalesce(parseDateTimeBestEffortUSOrNull({column_expr}), "
                f"parseDateTimeBestEffortOrNull({column_expr}))"
                ")"
            )
        return f"toDate({column_expr})"

    normalized = re.sub(
        r"toDate\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\)",
        _rewrite_ambiguous_to_date,
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"toStartOfWeek\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\)",
        r"toStartOfWeek(coalesce(parseDateTimeBestEffortUSOrNull(\1), parseDateTimeBestEffortOrNull(\1)))",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"toStartOfMonth\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\)",
        r"toStartOfMonth(coalesce(parseDateTimeBestEffortUSOrNull(\1), parseDateTimeBestEffortOrNull(\1)))",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"toYear\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\)",
        r"toYear(coalesce(parseDateTimeBestEffortUSOrNull(\1), parseDateTimeBestEffortOrNull(\1)))",
        normalized,
        flags=re.IGNORECASE,
    )
    return normalized


def _apply_output_sanity_checks(
    *,
    question: str,
    sql: str,
    validated_intent: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    corrected_sql = _normalize_clickhouse_date_casts(sql)
    notes: list[str] = []

    row_count_requested = _is_row_count_request(question) or bool(
        isinstance(validated_intent, dict) and validated_intent.get("row_count_requested")
    )
    if not row_count_requested:
        for metric_column in _BUSINESS_METRIC_COLUMNS:
            corrected_candidate = re.sub(
                rf"COUNT\(\s*{re.escape(metric_column)}\s*\)",
                f"SUM({metric_column})",
                corrected_sql,
                flags=re.IGNORECASE,
            )
            if corrected_candidate != corrected_sql:
                notes.append(f"Auto-corrected COUNT({metric_column}) to SUM({metric_column}).")
                corrected_sql = corrected_candidate

    if _is_predictive_question(question) and isinstance(validated_intent, dict):
        intent_type = str(validated_intent.get("intent_type", "")).strip().lower()
        requires_forecast = bool(validated_intent.get("requires_forecast"))
        if intent_type != "predictive" and not requires_forecast:
            notes.append("Predictive query detected; ensure forecasting route is used.")

    return corrected_sql, notes


def review_and_correct_sql(
    *,
    question: str,
    normalized_question: str | None = None,
    schema: dict[str, list[dict[str, Any]]],
    selected_table: str = "",
    selected_columns: list[str] | None = None,
    chart_contract: dict[str, Any] | None = None,
    generated_sql: str,
    validated_intent: dict[str, Any] | None = None,
    extracted_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = SqlReviewConfig.from_env()
    deterministic_result = _deterministic_review(question=question, generated_sql=generated_sql)

    if not config.enabled:
        final_sql = str(deterministic_result.get("sql", generated_sql)).strip()
        final_sql, sanity_notes = _apply_output_sanity_checks(
            question=question,
            sql=final_sql,
            validated_intent=validated_intent,
        )
        validate_sql(final_sql)
        alignment_notes = _validate_sql_against_intent(final_sql, validated_intent)
        status = deterministic_result.get("status", "approved")
        notes = list(deterministic_result.get("notes", [])) + sanity_notes
        if alignment_notes:
            final_sql = str(generated_sql or "").strip()
            validate_sql(final_sql)
            status = "approved"
            notes.extend(alignment_notes)
            notes.append("Review SQL reset to compiler output to preserve IR semantics.")
        return {
            "status": status,
            "generated_sql": generated_sql,
            "reviewed_sql": final_sql,
            "reason_category": deterministic_result.get("reason_category", "alignment"),
            "notes": notes,
            "model_provider": "disabled",
            "llm_used": False,
        }

    prompt = _build_review_prompt(
        question=question,
        normalized_question=normalized_question or question,
        schema=schema,
        selected_table=selected_table,
        selected_columns=selected_columns or [],
        chart_contract=chart_contract,
        generated_sql=generated_sql,
        validated_intent=validated_intent,
        extracted_intent=extracted_intent,
    )
    llm_error = ""
    llm_payload: dict[str, Any] | None = None

    try:
        if config.provider == "ollama":
            llm_raw = _call_ollama(prompt, config)
        else:
            llm_raw = _call_openrouter(prompt)
        llm_payload = _parse_json_payload(llm_raw)
    except Exception as exc:  # noqa: BLE001
        llm_error = str(exc)

    if llm_payload is None:
        final_sql = str(deterministic_result.get("sql", generated_sql)).strip()
        final_sql, sanity_notes = _apply_output_sanity_checks(
            question=question,
            sql=final_sql,
            validated_intent=validated_intent,
        )
        validate_sql(final_sql)
        alignment_notes = _validate_sql_against_intent(final_sql, validated_intent)
        if alignment_notes:
            final_sql = str(generated_sql or "").strip()
            final_sql, fallback_sanity_notes = _apply_output_sanity_checks(
                question=question,
                sql=final_sql,
                validated_intent=validated_intent,
            )
            validate_sql(final_sql)
            sanity_notes.extend(fallback_sanity_notes)
        return {
            "status": deterministic_result.get("status", "approved"),
            "generated_sql": generated_sql,
            "reviewed_sql": final_sql,
            "reason_category": deterministic_result.get("reason_category", "alignment"),
            "notes": (
                list(deterministic_result.get("notes", []))
                + sanity_notes
                + alignment_notes
                + (["Review SQL reset to compiler output to preserve IR semantics."] if alignment_notes else [])
                + [f"LLM review fallback: {llm_error}"]
            ),
            "model_provider": config.provider,
            "llm_used": False,
            "llm_error": llm_error,
        }

    llm_status = str(llm_payload.get("status", "rejected")).strip().lower()
    llm_sql = str(llm_payload.get("sql", "")).strip() or generated_sql
    llm_notes = llm_payload.get("notes", [])
    if not isinstance(llm_notes, list):
        llm_notes = [str(llm_notes)]
    llm_reason = str(llm_payload.get("reason_category", "other")).strip().lower()

    if llm_status == "rejected":
        fallback_sql, sanity_notes = _apply_output_sanity_checks(
            question=question,
            sql=str(generated_sql or "").strip(),
            validated_intent=validated_intent,
        )
        validate_sql(fallback_sql)
        fallback_notes = [str(note) for note in llm_notes if str(note).strip()]
        fallback_notes.extend(sanity_notes)
        fallback_notes.append("Review rejection fallback: preserved compiler SQL to keep validated IR semantics.")
        return {
            "status": "approved",
            "generated_sql": generated_sql,
            "reviewed_sql": fallback_sql,
            "reason_category": llm_reason or "alignment",
            "notes": fallback_notes,
            "model_provider": config.provider,
            "llm_used": True,
        }

    llm_sql, sanity_notes = _apply_output_sanity_checks(
        question=question,
        sql=llm_sql,
        validated_intent=validated_intent,
    )

    # Phase 6 / CRIT-04 + CRIT-05: validate the LLM SQL via query-service.
    # If validation fails OR the SQL drifts from the IR, fall back to the
    # compiler SQL instead of raising. The audit explicitly forbids letting
    # an invalid/misaligned LLM rewrite reach execution.
    llm_sql_invalid_reason = ""
    try:
        validate_sql(llm_sql)
    except ValueError as exc:
        llm_sql_invalid_reason = str(exc)

    alignment_notes = _validate_sql_against_intent(llm_sql, validated_intent)
    fallback_to_compiler = bool(llm_sql_invalid_reason) or bool(alignment_notes)
    if fallback_to_compiler:
        llm_sql = str(generated_sql or "").strip()
        llm_sql, fallback_sanity_notes = _apply_output_sanity_checks(
            question=question,
            sql=llm_sql,
            validated_intent=validated_intent,
        )
        validate_sql(llm_sql)
        fallback_messages: list[str] = []
        if llm_sql_invalid_reason:
            fallback_messages.append(
                f"LLM SQL rejected by query-service: {llm_sql_invalid_reason}; reverted to compiler SQL."
            )
        if alignment_notes:
            fallback_messages.extend(alignment_notes)
            fallback_messages.append(
                "LLM correction was overridden to preserve IR semantics."
            )
        llm_notes = (
            [str(note) for note in llm_notes if str(note).strip()]
            + sanity_notes
            + fallback_sanity_notes
            + fallback_messages
        )
        llm_status = "approved"
    else:
        llm_notes = [str(note) for note in llm_notes if str(note).strip()] + sanity_notes
    return {
        "status": llm_status if llm_status in {"approved", "corrected", "rejected"} else "rejected",
        "generated_sql": generated_sql,
        "reviewed_sql": llm_sql,
        "reason_category": llm_reason,
        "notes": [str(note) for note in llm_notes if str(note).strip()],
        "model_provider": config.provider,
        "llm_used": True,
    }

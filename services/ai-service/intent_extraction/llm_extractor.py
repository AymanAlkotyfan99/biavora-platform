"""LLM-driven structured intent extractor (Phase 5 / CRIT-14).

Phase 5 of the audit consolidates intent extraction around three principles:

1. **Single source of truth for predictive detection** – the local
   ``_PREDICTIVE_KEYWORDS`` and ``_FUTURE_TIME_PATTERNS`` tables that
   competed with the rest of the platform have been removed; predictive
   inference now flows through
   ``bi_platform_shared.predictive.detector.is_predictive``.

2. **Dynamic chart taxonomy** – the previously-hardcoded list of legal
   chart types is replaced by ``ChartTypeEnum``; that enum is the *only*
   taxonomy the platform recognises.

3. **JSON schema discipline** – the LLM prompt now enumerates the legal
   chart values directly from ``ChartTypeEnum.values()`` so the model can
   never invent a new chart token.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

import requests

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
    _SHARED_CLIENT_AVAILABLE = True
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]
    _SHARED_CLIENT_AVAILABLE = False

from bi_platform_shared.contracts.chart import ChartTypeEnum
from bi_platform_shared.predictive.detector import is_predictive

from intent_extraction.error_handler import (
    IntentExtractionModelOutputError,
    IntentExtractionSystemError,
)
from intent_extraction.schemas import IntentExtractionConfig, IntentType, StructuredIntent
from llm_app.response_parser import safe_json_parse
from shared.bi_llm_core_policy import STRICT_BI_LLM_CORE_POLICY
from shared.query_planner import normalize_analytical_intent
from shared.bi_llm_core_policy import STRICT_BI_LLM_CORE_POLICY


_VALID_INTENT_TYPES = {"analytical", "predictive"}
_RELATIONSHIP_KEYWORDS = (
    "relationship",
    "correlation",
    "associated",
    "association",
    "related",
    "relation",
    "vs",
    "versus",
)
_PERCENTAGE_SHARE_KEYWORDS = (
    "percentage",
    "percent",
    "share",
    "ratio",
    "proportion",
    "composition",
    "distribution",
    "%",
)
_PIE_KEYWORDS = ("pie", "donut", "doughnut")


def _allowed_chart_values() -> set[str]:
    """All canonical chart-type tokens the platform recognises.

    Driven by ``ChartTypeEnum`` so adding a new chart in the shared
    contract automatically widens the LLM and the validator without code
    duplication.
    """

    return {member.value for member in ChartTypeEnum}


def _allowed_chart_prompt_list() -> str:
    return "|".join(sorted(_allowed_chart_values())) + "|null"


def _schema_to_prompt(schema: dict[str, list[dict[str, Any]]]) -> str:
    lines: list[str] = []
    for table, columns in schema.items():
        lines.append(f"Table: {table}")
        for col in columns:
            col_name = str(col.get("name", "")).strip()
            col_type = str(col.get("type", "")).strip()
            lines.append(f"  - {col_name} ({col_type})")
    return "\n".join(lines)


def _build_extraction_prompt(*, query: str, schema: dict[str, list[dict[str, Any]]]) -> str:
    chart_options = _allowed_chart_prompt_list()
    return f"""
{STRICT_BI_LLM_CORE_POLICY}

You are a domain-agnostic semantic intent extraction engine for BI and analytics.

Your job:
1) Infer intent_type: "analytical" or "predictive".
2) Extract a COMPLETE IR payload for SQL planning.
3) Output STRICT JSON only (no markdown, no prose, no code fences).

Hard constraints:
- Use only columns/tables from the provided schema.
- Do not generate SQL.
- Do not drop requested metrics, dimensions, filters, ranking, or limits.
- If query implies ranking keywords (highest, lowest, top, bottom, best, worst), include order_by and ranking.direction.
- If query implies top/bottom/first/last N, include limit=N.
- If query implies comparisons (above, below, greater than, less than, more than, fewer than, >=, <=, =), map them into filters with explicit operators.
- If query asks multiple outputs ("A and B", "X with Y"), include all relevant metrics in both metrics and metric_specs.
- If aggregation intent appears (sum/total, avg/mean, count), set metric_specs.aggregation and aggregation accordingly.
- If query asks for pie/donut/share/percentage/composition/proportion, include chart.type="pie".
- If query asks for distribution/spread/frequency/histogram, include chart.type="histogram"; never map distribution to pie.
- If query asks for percentage/share, include chart.metric_type="percentage" and top-level metric_type="percentage".
- If the user mentions percentage, percent, or share -> set metric_type="percentage".
- If the user mentions distribution, preserve distribution semantics and set chart.type="histogram".
- If the user mentions pie or pie chart -> set chart.type="pie".
- Always include chart, metric_type, selected_chart_type, and chart_type in the output object.
- selected_chart_type and chart_type must mirror chart.type (or be null if chart.type is null).
- chart.type, selected_chart_type and chart_type MUST be one of: {chart_options}.
- If unsure, choose safest valid values but keep structure complete.

Schema:
{_schema_to_prompt(schema)}

Return exactly one JSON object with these keys:
{{
  "intent_type": "analytical|predictive",
  "table": "table_name",
  "intent": "projection|filtering|aggregation|ranking",
  "metrics": ["metric_column_name", "..."],
  "metric_specs": [
    {{"column": "metric_column_name", "aggregation": "SUM|AVG|COUNT|MIN|MAX|null", "alias": "optional_alias"}}
  ],
  "dimensions": ["dimension_column_name", "..."],
  "filters": [
    {{"column": "column_name", "operator": "=|!=|>|<|>=|<=|IN|LIKE|BETWEEN", "value": "scalar_or_array"}}
  ],
  "aggregation": "SUM|AVG|COUNT|MIN|MAX|MIXED|null",
  "target_column": "primary_metric_column_or_*",
  "time_range": "time window string or all_time",
  "order_by": [{{"column": "column_or_metric_alias", "direction": "ASC|DESC"}}],
  "limit": 1,
  "ranking": {{"direction": "ASC|DESC|null", "requested": true, "source": "query|model"}},
  "operations": ["projection", "aggregation", "grouping", "filtering", "ranking", "limiting", "comparison"],
  "ambiguities": [{{"type": "string", "message": "string"}}],
  "chart": {{
    "type": "{chart_options}",
    "metric_type": "percentage|absolute|ratio|null",
    "group_by": "dimension name or null"
  }},
  "metric_type": "percentage|absolute|ratio|null",
  "selected_chart_type": "{chart_options}",
  "chart_type": "{chart_options}"
}}

User query:
{query}
""".strip()


def _extract_json(raw_output: str) -> dict[str, Any]:
    try:
        parsed = safe_json_parse(raw_output)
    except Exception as exc:  # noqa: BLE001
        raise IntentExtractionModelOutputError(f"Invalid JSON returned by model: {exc}") from exc
    if not isinstance(parsed, dict):
        raise IntentExtractionModelOutputError("Model output must be a JSON object.")
    return parsed


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise IntentExtractionModelOutputError("Expected list for metrics/dimensions.")

    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
            continue
        if isinstance(item, dict):
            candidate = (
                item.get("column")
                or item.get("name")
                or item.get("field")
            )
            if isinstance(candidate, str) and candidate.strip():
                result.append(candidate.strip())
                continue
        raise IntentExtractionModelOutputError("Metrics/dimensions entries must be strings or objects with column.")
    return result


def _normalize_filters(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise IntentExtractionModelOutputError("Expected list for filters.")

    normalized: list[dict[str, Any]] = []
    operator_aliases = {
        "ABOVE": ">",
        "BELOW": "<",
        "GREATER THAN": ">",
        "LESS THAN": "<",
        "MORE THAN": ">",
        "FEWER THAN": "<",
        "=>": ">=",
        "=<": "<=",
        "==": "=",
    }
    for item in value:
        if not isinstance(item, dict):
            raise IntentExtractionModelOutputError("Each filter must be an object.")
        column = str(item.get("column", "")).strip()
        if not column:
            continue
        operator = str(item.get("operator", "=")).strip().upper() or "="
        operator = operator_aliases.get(operator, operator)
        normalized.append(
            {
                "column": column,
                "operator": operator,
                "value": item.get("value"),
            }
        )
    return normalized


def _normalize_metric_specs(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise IntentExtractionModelOutputError("Expected list for metric_specs.")

    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        column = str(item.get("column", "")).strip()
        if not column:
            continue
        aggregation = str(item.get("aggregation", "")).strip().upper() or None
        alias = str(item.get("alias", "")).strip() or None
        normalized.append(
            {
                "column": column,
                "aggregation": aggregation,
                "alias": alias,
            }
        )
    return normalized


def _normalize_order_by(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise IntentExtractionModelOutputError("Expected list for order_by.")

    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        column = str(item.get("column", "")).strip()
        if not column:
            continue
        direction = str(item.get("direction", "ASC")).strip().upper() or "ASC"
        if direction not in {"ASC", "DESC"}:
            direction = "ASC"
        normalized.append({"column": column, "direction": direction})
    return normalized


def _normalize_limit(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _as_metric_specs_from_columns(metrics: list[str], aggregation: str | None) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for metric in metrics:
        metric_clean = str(metric).strip()
        if not metric_clean:
            continue
        specs.append(
            {
                "column": metric_clean,
                "aggregation": aggregation if aggregation in {"SUM", "AVG", "COUNT", "MIN", "MAX"} else None,
                "alias": None,
            }
        )
    return specs


def _is_relationship_query(query: str) -> bool:
    lowered = str(query or "").strip().lower()
    if not lowered:
        return False
    if any(keyword in lowered for keyword in _RELATIONSHIP_KEYWORDS):
        return True
    return bool(re.search(r"\bbetween\b.+\band\b", lowered))


def _detect_chart_semantics(query: str, payload: dict[str, Any]) -> tuple[str, str]:
    """Detect chart semantics using the canonical ``ChartTypeEnum`` taxonomy.

    Phase 5 / CRIT-14: the prior hardcoded chart whitelist has been replaced
    by ``ChartTypeEnum.values()`` so the platform stays consistent if the
    enum grows.
    """

    lowered_query = str(query or "").strip().lower()
    payload_chart = payload.get("chart") if isinstance(payload.get("chart"), dict) else {}
    payload_chart_type = (
        str(payload.get("selected_chart_type", "")).strip().lower()
        or str(payload.get("chart_type", "")).strip().lower()
        or str(payload_chart.get("type", "")).strip().lower()
    )
    payload_metric_type = (
        str(payload_chart.get("metric_type", "")).strip().lower()
        or str(payload.get("metric_type", "")).strip().lower()
    )

    allowed_chart_types = _allowed_chart_values()
    chart_type = payload_chart_type if payload_chart_type in allowed_chart_types else ""
    metric_type = payload_metric_type if payload_metric_type in {"percentage", "absolute", "ratio"} else ""

    if any(keyword in lowered_query for keyword in ("distribution", "histogram", "spread", "frequency")):
        chart_type = ChartTypeEnum.HISTOGRAM.value
    if not metric_type and any(keyword in lowered_query for keyword in ("percentage", "percent", "share", "ratio", "proportion", "composition", "%")):
        metric_type = "percentage"
    if not chart_type and (
        any(keyword in lowered_query for keyword in _PIE_KEYWORDS)
        or (metric_type == "percentage" and any(keyword in lowered_query for keyword in _PERCENTAGE_SHARE_KEYWORDS))
    ):
        chart_type = ChartTypeEnum.PIE.value
    return chart_type, metric_type


def _relationship_ready_metrics(
    *,
    candidates: list[str],
    schema: dict[str, list[dict[str, Any]]],
) -> list[str]:
    numeric_columns: set[str] = set()
    for columns in schema.values():
        for col in columns:
            name = str(col.get("name", "")).strip()
            col_type = str(col.get("type", "")).strip().lower()
            if not name:
                continue
            if any(token in col_type for token in ("int", "float", "double", "decimal", "numeric", "real")):
                numeric_columns.add(name)

    resolved: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        metric = str(candidate or "").strip()
        if not metric:
            continue
        metric_lower = metric.lower()
        if metric_lower in seen:
            continue
        if metric in numeric_columns:
            resolved.append(metric)
            seen.add(metric_lower)
        if len(resolved) >= 2:
            break
    return resolved


def _enrich_with_semantic_ir(
    *,
    query: str,
    schema: dict[str, list[dict[str, Any]]],
    intent_payload: StructuredIntent,
) -> StructuredIntent:
    raw_intent_for_planner: dict[str, Any] = {
        "table": intent_payload.get("table", ""),
        "intent": intent_payload.get("intent", "projection"),
        "operations": intent_payload.get("operations", []),
        "metric_specs": intent_payload.get("metric_specs", []),
        "metrics": intent_payload.get("metrics", []),
        "dimensions": intent_payload.get("dimensions", []),
        "filters": intent_payload.get("filters", []),
        "order_by": intent_payload.get("order_by", []),
        "limit": intent_payload.get("limit"),
        "ranking": intent_payload.get("ranking", {}),
        "ambiguities": intent_payload.get("ambiguities", []),
        "chart": intent_payload.get("chart", {}),
        "metric_type": intent_payload.get("metric_type", ""),
        "selected_chart_type": intent_payload.get("selected_chart_type", ""),
        "chart_type": intent_payload.get("chart_type", ""),
    }

    try:
        normalized = normalize_analytical_intent(
            question=query,
            raw_intent=raw_intent_for_planner,
            schema=schema,
        )
    except Exception:
        return intent_payload

    normalized_metrics = normalized.get("metrics", []) or []
    enriched_metric_specs: list[dict[str, Any]] = []
    enriched_metrics: list[str] = []
    for metric in normalized_metrics:
        if not isinstance(metric, dict):
            continue
        column = str(metric.get("column", "")).strip()
        if not column:
            continue
        enriched_metrics.append(column)
        enriched_metric_specs.append(
            {
                "column": column,
                "aggregation": metric.get("aggregation"),
                "alias": metric.get("alias"),
            }
        )

    if not enriched_metrics:
        enriched_metrics = intent_payload.get("metrics", []) or []
    if not enriched_metric_specs and enriched_metrics:
        enriched_metric_specs = _as_metric_specs_from_columns(
            enriched_metrics,
            str(normalized.get("aggregation", "")).strip().upper() or None,
        )

    target_column = str(intent_payload.get("target_column", "")).strip()
    if not target_column:
        target_column = enriched_metrics[0] if enriched_metrics else "*"

    relationship_query = _is_relationship_query(query)
    normalized_operations = {
        str(op).strip().lower()
        for op in (normalized.get("operations", []) or [])
        if str(op).strip()
    }
    normalized_dimensions = [
        str(item).strip()
        for item in (normalized.get("dimensions", []) or [])
        if str(item).strip()
    ]
    has_time_like_dimension = any(
        (
            dim.lower() in {"ds", "date", "period", "timestamp", "datetime"}
            or any(token in dim.lower() for token in ("date", "time", "day", "week", "month", "quarter", "year"))
        )
        for dim in normalized_dimensions
    )
    time_grouping_detected = bool(
        normalized.get("time_grouping_detected")
        or "time_grouping" in normalized_operations
        or str(normalized.get("intent", "")).strip().lower() == "time_series"
        or has_time_like_dimension
    )
    if relationship_query and not time_grouping_detected:
        candidate_metrics: list[str] = []
        candidate_metrics.extend([str(item).strip() for item in enriched_metrics if str(item).strip()])
        candidate_metrics.extend([str(item).strip() for item in (intent_payload.get("metrics", []) or []) if str(item).strip()])
        relationship_metrics = _relationship_ready_metrics(candidates=candidate_metrics, schema=schema)
        if len(relationship_metrics) >= 2:
            return {
                "intent_type": intent_payload["intent_type"],
                "intent": "comparison",
                "metrics": relationship_metrics,
                "metric_specs": [
                    {"column": metric, "aggregation": None, "alias": None}
                    for metric in relationship_metrics
                ],
                "dimensions": [],
                "filters": normalized.get("filters", []) or [],
                "time_range": str(intent_payload.get("time_range", "all_time")).strip() or "all_time",
                "aggregation": "",
                "target_column": relationship_metrics[0],
                "table": str(normalized.get("table", intent_payload.get("table", ""))).strip(),
                "order_by": [],
                "limit": None,
                "ranking": {"direction": None, "requested": False, "source": "relationship_override"},
                "operations": ["projection", "comparison"],
                "ambiguities": normalized.get("ambiguities", []) if isinstance(normalized.get("ambiguities"), list) else [],
            }

    return {
        "intent_type": intent_payload["intent_type"],
        "intent": str(normalized.get("intent", intent_payload.get("intent", "projection"))),
        "metrics": enriched_metrics or ["*"],
        "metric_specs": enriched_metric_specs,
        "dimensions": [str(item).strip() for item in (normalized.get("dimensions", []) or []) if str(item).strip()],
        "filters": normalized.get("filters", []) or [],
        "time_range": str(intent_payload.get("time_range", "all_time")).strip() or "all_time",
        "aggregation": str(normalized.get("aggregation", intent_payload.get("aggregation", "")) or ""),
        "target_column": target_column,
        "table": str(normalized.get("table", intent_payload.get("table", ""))).strip(),
        "order_by": normalized.get("order_by", []) or [],
        "limit": normalized.get("limit"),
        "ranking": normalized.get("ranking", {}) if isinstance(normalized.get("ranking"), dict) else {},
        "operations": normalized.get("operations", []) if isinstance(normalized.get("operations"), list) else [],
        "ambiguities": normalized.get("ambiguities", []) if isinstance(normalized.get("ambiguities"), list) else [],
        "chart": intent_payload.get("chart", {}) if isinstance(intent_payload.get("chart"), dict) else {},
        "metric_type": str(intent_payload.get("metric_type", "")).strip().lower(),
        "selected_chart_type": str(intent_payload.get("selected_chart_type", "")).strip().lower(),
        "chart_type": str(intent_payload.get("chart_type", "")).strip().lower(),
    }


def infer_intent_type(*, query: str, hinted_intent_type: str | None = None) -> IntentType:
    """Decide whether a question is analytical or predictive.

    Phase 5 / CRIT-14: the local predictive keyword and pattern lists were
    deleted. Predictive detection now uses the canonical shared detector at
    ``bi_platform_shared.predictive.detector.is_predictive`` which carries
    the platform-wide multilingual keyword set.
    """

    hinted = (hinted_intent_type or "").strip().lower()
    if hinted in _VALID_INTENT_TYPES:
        return hinted  # type: ignore[return-value]

    if is_predictive(str(query or "")):
        return "predictive"

    lowered = (query or "").lower()
    current_year = datetime.now(timezone.utc).year
    for match in re.findall(r"\b(19\d{2}|20\d{2}|21\d{2})\b", lowered):
        if int(match) > current_year:
            return "predictive"

    return "analytical"


def _call_ollama(
    *,
    prompt: str,
    config: IntentExtractionConfig,
) -> str:
    payload = {
        "model": config.ollama_model,
        "prompt": prompt,
        "stream": False,
    }

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
        raise IntentExtractionSystemError(
            f"Ollama timeout after {config.request_timeout_seconds}s."
        ) from exc
    except HttpClientError as exc:  # type: ignore[misc]
        raise IntentExtractionSystemError(f"Ollama HTTP request failed: {exc}") from exc
    except requests.RequestException as exc:
        raise IntentExtractionSystemError(f"Ollama request failed: {exc}") from exc

    if response.status_code in {408, 429, 500, 502, 503, 504}:
        raise IntentExtractionSystemError(
            f"Ollama transient error ({response.status_code}): {response.text.strip()}"
        )
    if response.status_code >= 400:
        raise IntentExtractionModelOutputError(
            f"Ollama returned HTTP {response.status_code}: {response.text.strip()}"
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise IntentExtractionModelOutputError("Ollama returned non-JSON body.") from exc

    content = str(body.get("response", "")).strip()
    if not content:
        raise IntentExtractionModelOutputError("Ollama returned empty content.")
    return content


def _call_openrouter(*, prompt: str) -> str:
    try:
        from llm_app.llm_client import call_llm
    except Exception as exc:  # noqa: BLE001
        raise IntentExtractionSystemError(f"LLM client import failed: {exc}") from exc

    try:
        content = call_llm(prompt)
    except ValueError as exc:
        raise IntentExtractionSystemError(f"LLM configuration error: {exc}") from exc
    except RuntimeError as exc:
        lowered = str(exc).lower()
        if "timeout" in lowered or "timed out" in lowered:
            raise IntentExtractionSystemError(str(exc)) from exc
        raise IntentExtractionSystemError(f"LLM service error: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise IntentExtractionSystemError(f"Unexpected LLM error: {exc}") from exc

    if not content or not content.strip():
        raise IntentExtractionModelOutputError("LLM returned empty content.")
    return content


def extract_structured_intent(
    *,
    query: str,
    schema: dict[str, list[dict[str, Any]]],
    config: IntentExtractionConfig,
    logger: logging.Logger,
    log_event: Callable[..., None],
    include_debug: bool = False,
) -> StructuredIntent | tuple[StructuredIntent, dict[str, Any]]:
    prompt = _build_extraction_prompt(query=query, schema=schema)
    provider = config.llm_provider

    log_event(
        logger,
        logging.INFO,
        "Calling LLM for intent extraction",
        llm_provider=provider,
        input_query_preview=query[:200],
    )

    if provider == "ollama":
        raw_output = _call_ollama(prompt=prompt, config=config)
    else:
        raw_output = _call_openrouter(prompt=prompt)

    payload = _extract_json(raw_output)

    metrics = _normalize_string_list(payload.get("metrics"))
    dimensions = _normalize_string_list(payload.get("dimensions"))
    metric_specs = _normalize_metric_specs(payload.get("metric_specs"))
    filters = _normalize_filters(payload.get("filters"))
    order_by = _normalize_order_by(payload.get("order_by"))
    limit = _normalize_limit(payload.get("limit"))
    aggregation = str(payload.get("aggregation", "SUM")).strip().upper() or "SUM"
    table = str(payload.get("table", "")).strip()
    target_column = str(payload.get("target_column", "")).strip()
    time_range = str(payload.get("time_range", "")).strip() or "all_time"

    if not target_column and metrics:
        target_column = metrics[0]

    intent_type = infer_intent_type(
        query=query,
        hinted_intent_type=str(payload.get("intent_type", "")).strip(),
    )
    selected_chart_type, metric_type = _detect_chart_semantics(query, payload)
    chart_group_by = None
    if dimensions:
        chart_group_by = dimensions[0]
    payload_chart = payload.get("chart") if isinstance(payload.get("chart"), dict) else {}
    if payload_chart.get("group_by"):
        chart_group_by = str(payload_chart.get("group_by")).strip() or chart_group_by

    intent_payload: StructuredIntent = {
        "intent_type": intent_type,
        "intent": "projection",
        "metrics": metrics,
        "metric_specs": metric_specs,
        "dimensions": dimensions,
        "filters": filters,
        "time_range": time_range,
        "aggregation": aggregation,
        "target_column": target_column,
        "table": table,
        "order_by": order_by,
        "limit": limit,
        "ranking": payload.get("ranking") if isinstance(payload.get("ranking"), dict) else {},
        "operations": payload.get("operations") if isinstance(payload.get("operations"), list) else [],
        "ambiguities": payload.get("ambiguities") if isinstance(payload.get("ambiguities"), list) else [],
        "chart": {
            "type": selected_chart_type or None,
            "metric_type": metric_type or None,
            "group_by": chart_group_by or None,
        },
        "metric_type": metric_type,
        "selected_chart_type": selected_chart_type,
        "chart_type": selected_chart_type,
    }
    intent_payload = _enrich_with_semantic_ir(
        query=query,
        schema=schema,
        intent_payload=intent_payload,
    )
    debug_payload = {
        "provider": provider,
        "prompt": prompt,
        "raw_output": raw_output,
        "parsed_payload": payload,
    }
    if include_debug:
        return intent_payload, debug_payload
    return intent_payload

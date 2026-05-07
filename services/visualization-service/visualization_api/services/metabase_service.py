"""
Metabase Self-Hosted Integration Service

- Session auth via POST /api/session
- Health check with retries before login
- In-memory session caching with TTL
- Auto re-auth on 401
- Graceful fallback with structured last_error

Phase 13 / GAP-03 — Metabase fallback:

* When Metabase is unreachable (health check fails), ``create_question``
  now returns the structured value ``MetabaseFallbackResult`` (a dict with
  ``status="degraded"``, ``error_code="metabase_unavailable"``, and the
  raw SQL/columns/rows preserved) instead of returning ``None`` and losing
  the result. Voice-service can then render a typed "results-without-chart"
  response so users still see the data.
* All outbound HTTP calls go through the shared HTTP client (Phase 13 /
  GAP-05) which provides retries with exponential backoff, circuit
  breakers, and W3C Trace Context propagation.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple
from bi_platform_shared.sql import sanitize_sql_for_metabase

# Phase 13 / GAP-05: prefer the shared HTTP client which provides retries,
# circuit breakers and W3C Trace Context propagation. Fall back to the
# stdlib ``requests`` package when the shared package is not on PYTHONPATH
# (e.g. unit tests that import ``metabase_service`` in isolation).
try:
    from bi_platform_shared.http import get_default_client as _get_shared_http_client
    from bi_platform_shared.http.client import CircuitBreakerOpenError, HttpClientError
except Exception:  # pragma: no cover
    _get_shared_http_client = None  # type: ignore[assignment]

    class HttpClientError(Exception):
        """Fallback when bi_platform_shared is not installed."""

    class CircuitBreakerOpenError(HttpClientError):
        """Fallback when bi_platform_shared is not installed."""


import requests
logger = logging.getLogger(__name__)

_session_token: Optional[str] = None
_session_token_expires_at: float = 0.0

METABASE_TIMEOUT_SECONDS = int(os.getenv("METABASE_TIMEOUT_SECONDS", "30"))
METABASE_AUTH_RETRIES = int(os.getenv("METABASE_AUTH_RETRIES", "2"))
METABASE_HEALTH_RETRIES = int(os.getenv("METABASE_HEALTH_RETRIES", "2"))
METABASE_SESSION_TTL_SECONDS = int(os.getenv("METABASE_SESSION_TTL_SECONDS", "1800"))

CHART_TYPE_MAPPING: Dict[str, str] = {
    "line": "line",
    "line_multi": "line",
    "bar": "bar",
    "bar_grouped": "bar",
    "bar_stacked": "bar",
    "pie": "pie",
    "area": "area",
    "scatter": "scatter",
    "bubble": "scatter",
    "histogram": "histogram",
    "map": "map",
    "combo_line_bar": "combo",
    "combo": "combo",
    "kpi": "scalar",
    "card": "scalar",
    "scalar": "scalar",
    "number": "scalar",
    "grouped_bar": "bar",
    "stacked_bar": "bar",
    "table": "table",
}
SUPPORTED_DISPLAYS = {"line", "bar", "scatter", "scalar", "table", "histogram", "pie", "area", "map", "combo"}

def _metabase_base_url() -> str:
    return (os.getenv("METABASE_URL") or "http://localhost:3000").rstrip("/")


def _metabase_embed_base_url() -> str:
    return (
        os.getenv("METABASE_EMBED_URL")
        or os.getenv("METABASE_PUBLIC_URL")
        or os.getenv("METABASE_URL")
        or "http://localhost:3000"
    ).rstrip("/")


def _credentials() -> tuple[Optional[str], Optional[str]]:
    return os.getenv("METABASE_USERNAME"), os.getenv("METABASE_PASSWORD")


def _http_get(url: str, *, timeout: int) -> Optional[requests.Response]:
    """Phase 13 / GAP-05: route GETs through the shared HTTP client when
    available; fall back to the stdlib ``requests`` package otherwise.
    """

    if _get_shared_http_client is not None:
        try:
            client = _get_shared_http_client()
            return client.get(url, timeout=(min(5.0, timeout), float(timeout)), attach_internal_api_key=False)
        except CircuitBreakerOpenError as exc:
            logger.warning("metabase_http_breaker_open url=%s err=%s", url, exc)
            return None
        except HttpClientError as exc:
            logger.warning("metabase_http_client_error url=%s err=%s", url, exc)
            return None
    return requests.get(url, timeout=timeout)


def _http_request(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    json: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = METABASE_TIMEOUT_SECONDS,
) -> Optional[requests.Response]:
    """GAP-05: Metabase API calls (non-health) via shared client when installed."""

    timeout_pair = (min(5.0, float(timeout_seconds)), float(timeout_seconds))
    if _get_shared_http_client is not None:
        try:
            client = _get_shared_http_client()
            if json is not None and method.upper() != "GET":
                return client.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    timeout=timeout_pair,
                    attach_internal_api_key=False,
                )
            return client.request(
                method,
                url,
                headers=headers,
                timeout=timeout_pair,
                attach_internal_api_key=False,
            )
        except CircuitBreakerOpenError as exc:
            logger.warning("metabase_http_breaker_open method=%s url=%s err=%s", method, url, exc)
            return None
        except HttpClientError as exc:
            logger.warning("metabase_http_client_error method=%s url=%s err=%s", method, url, exc)
            return None
    kwargs: Dict[str, Any] = {"headers": headers, "timeout": timeout_seconds}
    if json is not None and method.upper() != "GET":
        kwargs["json"] = json
    return requests.request(method, url, **kwargs)


def check_metabase_health(*, retries: int = METABASE_HEALTH_RETRIES) -> bool:
    url = f"{_metabase_base_url()}/api/health"
    for attempt in range(retries + 1):
        try:
            response = _http_get(url, timeout=METABASE_TIMEOUT_SECONDS)
            if response is not None and response.status_code == 200:
                return True
        except Exception as exc:
            logger.warning("Metabase health check failed (attempt %s): %s", attempt + 1, exc)
        if attempt < retries:
            time.sleep(1 + attempt)
    return False


def metabase_fallback_payload(
    *,
    error_code: str,
    error_message: str,
    sql: Optional[str] = None,
    columns: Optional[list[str]] = None,
    rows: Optional[list[Any]] = None,
    chart_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Phase 13 / GAP-03: typed fallback returned when Metabase is
    unavailable so voice-service can render a "results-without-chart"
    response instead of treating it as a hard failure.
    """

    return {
        "status": "degraded",
        "error_code": error_code,
        "error_message": error_message,
        "embed_url": None,
        "metabase_card_id": None,
        "sql": sql,
        "columns": list(columns or []),
        "rows": list(rows or []),
        "chart_contract": chart_contract or {},
        "fallback_owner": "visualization-service",
    }


def get_metabase_session(force_refresh: bool = False) -> Optional[str]:
    global _session_token, _session_token_expires_at

    if (
        _session_token
        and not force_refresh
        and time.time() < _session_token_expires_at
    ):
        return _session_token

    username, password = _credentials()
    if not username or not password:
        logger.error("METABASE_USERNAME and METABASE_PASSWORD must be configured")
        clear_metabase_session()
        return None

    if not check_metabase_health():
        logger.error("Metabase is unavailable at %s", _metabase_base_url())
        clear_metabase_session()
        return None

    session_url = f"{_metabase_base_url()}/api/session"
    payload = {"username": username, "password": password}

    for attempt in range(METABASE_AUTH_RETRIES + 1):
        try:
            if _get_shared_http_client is not None:
                response = _get_shared_http_client().post(
                    session_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=(min(5.0, float(METABASE_TIMEOUT_SECONDS)), float(METABASE_TIMEOUT_SECONDS)),
                    attach_internal_api_key=False,
                )
            else:
                response = requests.post(
                    session_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=METABASE_TIMEOUT_SECONDS,
                )
            if response.status_code == 200:
                data = response.json()
                token = data.get("id")
                if token:
                    _session_token = token
                    _session_token_expires_at = time.time() + METABASE_SESSION_TTL_SECONDS
                    logger.info("Metabase session obtained successfully")
                    return _session_token
            logger.error(
                "Metabase login failed (attempt %s): status=%s body=%s",
                attempt + 1,
                response.status_code,
                (response.text or "")[:300],
            )
        except Exception as exc:
            logger.error("Metabase session error (attempt %s): %s", attempt + 1, exc)

        if attempt < METABASE_AUTH_RETRIES:
            time.sleep(1 + attempt)

    clear_metabase_session()
    return None


def clear_metabase_session() -> None:
    global _session_token, _session_token_expires_at
    _session_token = None
    _session_token_expires_at = 0.0


def get_metabase_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    session_id = get_metabase_session()
    if session_id:
        headers["X-Metabase-Session"] = session_id
    return headers


class MetabaseService:
    def __init__(self) -> None:
        self.base_url = _metabase_base_url()
        self.embed_base_url = _metabase_embed_base_url()
        self.database_id = int(os.getenv("METABASE_DATABASE_ID", "1"))
        self.last_error: Optional[str] = None
        self.last_display: Optional[str] = None
        self.last_fallback_applied: bool = False
        self.last_fallback_reason: str = ""

    @staticmethod
    def _clean_non_blank_string(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None

    @staticmethod
    def _extract_error_details(response: requests.Response) -> str:
        try:
            payload = response.json()
            return json.dumps(payload, ensure_ascii=False)[:500]
        except Exception:
            text = (response.text or "").strip()
            return text[:500] if text else f"status={response.status_code}"

    def _set_last_error(self, message: Optional[str]) -> None:
        self.last_error = message

    @staticmethod
    def _string_list(values: Any) -> list[str]:
        if not isinstance(values, (list, tuple)):
            return []
        cleaned: list[str] = []
        for value in values:
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    cleaned.append(stripped)
        return cleaned

    @staticmethod
    def _looks_like_hex_color(value: str) -> bool:
        cleaned = value.strip()
        if len(cleaned) != 7 or not cleaned.startswith("#"):
            return False
        return all(ch in "0123456789abcdefABCDEF" for ch in cleaned[1:])

    def _apply_series_style_hints(self, settings: Dict[str, Any], *, display: str) -> None:
        if display != "line":
            return

        series_config = settings.get("chart_series_config")
        if not isinstance(series_config, list):
            return

        breakout = self._string_list(settings.get("graph.breakout"))
        if not breakout:
            series_field = str(settings.get("series_type_field") or "").strip()
            if series_field:
                breakout = [series_field]
                settings["graph.breakout"] = breakout
        if not breakout:
            return

        colors: list[str] = []
        series_settings: Dict[str, Dict[str, Any]] = {}
        for item in series_config:
            if not isinstance(item, dict):
                continue
            series_type = str(item.get("series_type") or "").strip()
            series_label = str(item.get("series_label") or "").strip()
            preferred_color = str(item.get("preferred_color") or "").strip()
            if not series_type or not self._looks_like_hex_color(preferred_color):
                continue

            colors.append(preferred_color)
            style = {"color": preferred_color}
            if series_label:
                style["title"] = series_label
            series_settings[series_type] = dict(style)
            if series_label:
                series_settings[series_label] = dict(style)

        deduped_colors: list[str] = []
        for color in colors:
            if color not in deduped_colors:
                deduped_colors.append(color)
        if deduped_colors:
            settings["graph.colors"] = deduped_colors
        if series_settings:
            existing = settings.get("series_settings")
            merged = dict(existing) if isinstance(existing, dict) else {}
            merged.update(series_settings)
            settings["series_settings"] = merged

    @staticmethod
    def _extract_dataset_columns(settings: Dict[str, Any]) -> list[Dict[str, Any]]:
        """
        Normalize dataset column metadata from common payload shapes.
        Supported inputs include:
        - settings["dataset_columns"] / settings["columns"] / settings["result_columns"]
        where each item can be a string column name or a dict with at least a name.
        """
        raw_candidates = (
            settings.get("dataset_columns"),
            settings.get("columns"),
            settings.get("result_columns"),
        )
        for raw in raw_candidates:
            if not isinstance(raw, list):
                continue
            normalized: list[Dict[str, Any]] = []
            for item in raw:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if not name:
                        continue
                    normalized.append(item)
                elif isinstance(item, str):
                    name = item.strip()
                    if not name:
                        continue
                    normalized.append({"name": name})
            if normalized:
                return normalized
        return []

    @staticmethod
    def _dataset_numeric_columns(dataset_columns: list[Dict[str, Any]]) -> list[str]:
        numeric_columns: list[str] = []
        for column in dataset_columns:
            name = str(column.get("name") or "").strip()
            if not name:
                continue
            is_numeric = bool(column.get("is_numeric"))
            if not is_numeric:
                column_type = str(column.get("type") or "").strip().lower()
                is_numeric = any(token in column_type for token in ("int", "float", "double", "decimal", "numeric"))
            if is_numeric:
                numeric_columns.append(name)
        return numeric_columns

    @staticmethod
    def _extract_result_rows(settings: Dict[str, Any]) -> list[Dict[str, Any]]:
        raw_candidates = (
            settings.get("result_rows"),
            settings.get("rows"),
            settings.get("data_rows"),
        )
        for raw in raw_candidates:
            if not isinstance(raw, list):
                continue
            normalized = [row for row in raw if isinstance(row, dict)]
            if normalized:
                return normalized
        return []

    @staticmethod
    def _is_numeric_like(value: Any) -> bool:
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return False
            if stripped.startswith("-"):
                stripped = stripped[1:]
            return stripped.replace(".", "", 1).isdigit()
        return False

    def _result_row_numeric_columns(
        self,
        result_rows: list[Dict[str, Any]],
        preferred_order: list[str],
    ) -> list[str]:
        if not result_rows:
            return []

        ordered_names: list[str] = []
        seen: set[str] = set()
        for name in preferred_order:
            cleaned = str(name or "").strip()
            if cleaned and cleaned not in seen:
                ordered_names.append(cleaned)
                seen.add(cleaned)
        for row in result_rows:
            for key in row.keys():
                cleaned = str(key or "").strip()
                if cleaned and cleaned not in seen:
                    ordered_names.append(cleaned)
                    seen.add(cleaned)

        numeric_columns: list[str] = []
        sample_rows = result_rows[:25]
        for column_name in ordered_names:
            observed = [
                row.get(column_name)
                for row in sample_rows
                if column_name in row and row.get(column_name) is not None
            ]
            if observed and all(self._is_numeric_like(value) for value in observed):
                numeric_columns.append(column_name)
        return numeric_columns

    @staticmethod
    def _normalize_display(value: Optional[str]) -> Optional[str]:
        if not isinstance(value, str):
            return None
        cleaned = value.strip().lower()
        if not cleaned:
            return None
        return CHART_TYPE_MAPPING.get(cleaned, cleaned)

    def _resolve_scatter_axes(self, settings: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        dimensions = self._string_list(settings.get("graph.dimensions"))
        metrics = self._string_list(settings.get("graph.metrics"))
        if len(dimensions) == 1 and len(metrics) == 1:
            return dimensions[0], metrics[0]

        x_column = settings.get("x_column")
        y_column = settings.get("y_column")
        if isinstance(x_column, str) and isinstance(y_column, str):
            x_clean = x_column.strip()
            y_clean = y_column.strip()
            if x_clean and y_clean:
                return x_clean, y_clean

        numeric_columns = self._string_list(settings.get("numeric_columns"))
        if len(numeric_columns) >= 2:
            return numeric_columns[0], numeric_columns[1]

        return None, None

    def _resolve_line_dimension_metric(self, settings: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        dimensions = self._string_list(settings.get("graph.dimensions"))
        metrics = self._string_list(settings.get("graph.metrics"))
        if dimensions and metrics:
            return dimensions[0], metrics[0]

        time_columns = self._string_list(settings.get("time_columns"))
        numeric_columns = self._string_list(settings.get("numeric_columns"))
        if time_columns and numeric_columns:
            return time_columns[0], numeric_columns[0]
        category_columns = self._string_list(settings.get("category_columns"))
        if category_columns and numeric_columns:
            return category_columns[0], numeric_columns[0]
        return None, None

    def _resolve_bar_dimension_metric(self, settings: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        dimensions = self._string_list(settings.get("graph.dimensions"))
        metrics = self._string_list(settings.get("graph.metrics"))
        if dimensions and metrics:
            return dimensions[0], metrics[0]
        category_columns = self._string_list(settings.get("category_columns"))
        numeric_columns = self._string_list(settings.get("numeric_columns"))
        if category_columns and numeric_columns:
            return category_columns[0], numeric_columns[0]
        time_columns = self._string_list(settings.get("time_columns"))
        if time_columns and numeric_columns:
            return time_columns[0], numeric_columns[0]
        return None, None

    def _resolve_map_dimension_metric(self, settings: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        dimensions = self._string_list(settings.get("graph.dimensions"))
        metrics = self._string_list(settings.get("graph.metrics"))
        if dimensions:
            metric = metrics[0] if metrics else None
            return dimensions[0], metric
        geo_columns = self._string_list(settings.get("geo_columns"))
        numeric_columns = self._string_list(settings.get("numeric_columns"))
        if geo_columns:
            metric = numeric_columns[0] if numeric_columns else None
            return geo_columns[0], metric
        return None, None

    def _resolve_combo_dimension_metrics(self, settings: Dict[str, Any]) -> tuple[Optional[str], list[str]]:
        dimensions = self._string_list(settings.get("graph.dimensions"))
        metrics = self._string_list(settings.get("graph.metrics"))
        if dimensions and len(metrics) >= 2:
            return dimensions[0], metrics[:2]

        time_columns = self._string_list(settings.get("time_columns"))
        numeric_columns = self._string_list(settings.get("numeric_columns"))
        if time_columns and len(numeric_columns) >= 2:
            return time_columns[0], numeric_columns[:2]
        return None, []

    def _resolve_histogram_metric(self, settings: Dict[str, Any]) -> Optional[str]:
        # Priority:
        # 1) graph.metrics
        # 2) numeric_columns
        # 3) first numeric column in dataset metadata
        # 4) first numeric column from result column metadata
        # 5) first numeric column inferred from result rows
        # 6) first dataset column
        # 7) legacy axis hints (x_column / y_column)
        metrics = self._string_list(settings.get("graph.metrics"))
        if metrics:
            logger.info("Histogram metric resolved from graph.metrics: %s", metrics[0])
            return metrics[0]

        numeric_columns = self._string_list(settings.get("numeric_columns"))
        if numeric_columns:
            logger.info("Histogram metric resolved from numeric_columns: %s", numeric_columns[0])
            return numeric_columns[0]

        dataset_columns = self._extract_dataset_columns(settings)
        dataset_numeric_columns = self._dataset_numeric_columns(dataset_columns)
        if dataset_numeric_columns:
            logger.info("Histogram metric resolved from dataset_columns: %s", dataset_numeric_columns[0])
            return dataset_numeric_columns[0]

        result_columns = settings.get("result_columns")
        normalized_result_columns: list[Dict[str, Any]] = []
        if isinstance(result_columns, list):
            for item in result_columns:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        normalized_result_columns.append(item)
                elif isinstance(item, str):
                    cleaned = item.strip()
                    if cleaned:
                        normalized_result_columns.append({"name": cleaned})
        result_numeric_columns = self._dataset_numeric_columns(normalized_result_columns)
        if result_numeric_columns:
            logger.info("Histogram metric resolved from result_columns: %s", result_numeric_columns[0])
            return result_numeric_columns[0]

        result_rows = self._extract_result_rows(settings)
        dataset_column_names = [str(col.get("name") or "").strip() for col in dataset_columns if str(col.get("name") or "").strip()]
        row_numeric_columns = self._result_row_numeric_columns(result_rows, dataset_column_names)
        if row_numeric_columns:
            logger.info("Histogram metric resolved from result rows: %s", row_numeric_columns[0])
            return row_numeric_columns[0]

        if dataset_columns:
            fallback_name = str(dataset_columns[0].get("name") or "").strip()
            if fallback_name:
                logger.info("Histogram metric resolved from dataset_columns fallback: %s", fallback_name)
                return fallback_name

        for axis_key in ("x_column", "y_column"):
            axis_value = settings.get(axis_key)
            if isinstance(axis_value, str):
                cleaned = axis_value.strip()
                if cleaned:
                    logger.info("Histogram metric resolved from legacy %s hint: %s", axis_key, cleaned)
                    return cleaned
        logger.warning("Histogram metric resolution fell through all strategies; no metric available.")
        return None

    def _prepare_visualization_settings(
        self, visualization_settings: Optional[Dict[str, Any]]
    ) -> Tuple[str, Dict[str, Any], Optional[str]]:
        """Return (metabase_display, visualization_settings, error_code).

        Renderer-only policy: never change ``chart_type`` / ``final_chart_type`` from the
        upstream contract. Missing axis bindings yield a non-empty error instead of silently
        falling back to ``table``.
        """

        settings: Dict[str, Any] = dict(visualization_settings or {})
        chart_config = settings.get("chart_config") if isinstance(settings.get("chart_config"), dict) else {}
        chart_contract = settings.get("chart_contract") if isinstance(settings.get("chart_contract"), dict) else {}
        merged_contract: Dict[str, Any] = {
            **chart_config,
            **chart_contract,
        }
        for flag in ("explicit_chart_lock", "chart_locked", "locked", "chart_lock"):
            if flag in settings and flag not in merged_contract:
                merged_contract[flag] = settings[flag]

        raw_upstream_chart = str(
            merged_contract.get("chart_type")
            or merged_contract.get("type")
            or merged_contract.get("final_chart_type")
            or merged_contract.get("selected_chart_type")
            or settings.get("chart_type")
            or settings.get("type")
            or settings.get("final_chart_type")
            or settings.get("selected_chart_type")
            or ""
        ).strip()
        if not raw_upstream_chart:
            logger.error("chart_contract_missing_cannot_prepare_metabase_payload")
            return "", settings, "missing_upstream_chart_contract"
        requested_chart_type = raw_upstream_chart.lower()
        final_chart_type = requested_chart_type
        logger.info("Visualization using upstream chart type: %s", final_chart_type)

        # Preserve axis fields from chart contract unless explicitly provided at top-level settings.
        for axis_key in ("x_axis", "label_column", "value_column", "time_column", "time_grain", "metric_type"):
            if (axis_key not in settings or settings.get(axis_key) in (None, "", [])) and merged_contract.get(axis_key) not in (None, "", []):
                settings[axis_key] = merged_contract.get(axis_key)
        if "y_axis" not in settings or settings.get("y_axis") in (None, "", []):
            y_from_contract = merged_contract.get("y_axis")
            settings["y_axis"] = y_from_contract if isinstance(y_from_contract, list) else (
                [str(y_from_contract).strip()] if isinstance(y_from_contract, str) and str(y_from_contract).strip() else []
            )

        display = self._normalize_display(final_chart_type)
        if not display or display not in SUPPORTED_DISPLAYS:
            return "", settings, f"unsupported_metabase_display:{final_chart_type}"

        # Build column families for strict validation/logging only.
        dataset_columns = self._extract_dataset_columns(settings)
        result_rows = self._extract_result_rows(settings)
        dataset_column_names = [str(col.get("name") or "").strip() for col in dataset_columns if str(col.get("name") or "").strip()]
        numeric_columns = self._dataset_numeric_columns(dataset_columns)
        row_numeric_columns = self._result_row_numeric_columns(result_rows, dataset_column_names)
        for candidate in row_numeric_columns:
            if candidate not in numeric_columns:
                numeric_columns.append(candidate)

        candidate_names = list(dataset_column_names)
        if not candidate_names and result_rows:
            candidate_names = [str(key).strip() for key in result_rows[0].keys() if str(key).strip()]
        time_columns = [
            name for name in candidate_names
            if any(token in name.lower() for token in ("date", "time", "period", "day", "week", "month", "year", "ds"))
        ]
        geo_columns = [
            name for name in candidate_names
            if any(token in name.lower() for token in ("lat", "lng", "lon", "country", "state", "city", "geo", "location"))
        ]
        category_columns = [name for name in candidate_names if name not in numeric_columns]
        settings["numeric_columns"] = numeric_columns
        settings["time_columns"] = time_columns
        settings["geo_columns"] = geo_columns
        settings["category_columns"] = category_columns

        graph_contract = settings.get("graph") if isinstance(settings.get("graph"), dict) else {}
        graph_dimensions = self._string_list(graph_contract.get("dimensions") or settings.get("graph.dimensions"))
        graph_metrics = self._string_list(graph_contract.get("metrics") or settings.get("graph.metrics"))
        if not graph_dimensions:
            x_axis = str(settings.get("x_axis") or "").strip()
            if x_axis:
                graph_dimensions = [x_axis]
        if not graph_metrics:
            y_axis = self._string_list(settings.get("y_axis"))
            if y_axis:
                graph_metrics = y_axis
        label_column = str(settings.get("label_column") or "").strip()
        value_column = str(settings.get("value_column") or "").strip()
        if not graph_dimensions:
            if final_chart_type == "pie":
                return "", settings, "missing_required_label_value_bindings:pie"
            return "", settings, f"missing_required_axis_bindings:{final_chart_type}"
        if final_chart_type == "pie":
            label = label_column or graph_dimensions[0]
            value = value_column or (graph_metrics[0] if graph_metrics else "")
            if not label or not value:
                return "", settings, "missing_required_label_value_bindings:pie"
            settings["label_column"] = label
            settings["value_column"] = value
            graph_dimensions = [label]
            graph_metrics = [value]
        elif not graph_metrics:
            return "", settings, f"missing_required_axis_bindings:{final_chart_type}"

        settings["graph.dimensions"] = list(graph_dimensions)
        settings["graph.metrics"] = list(graph_metrics)

        settings["selected_chart_type"] = final_chart_type
        settings["chart_type"] = final_chart_type
        settings["final_chart_type"] = final_chart_type
        settings["display"] = display
        settings["requested_display"] = display
        settings["chart_locked"] = bool(settings.get("chart_locked", settings.get("explicit_chart_lock", True)))
        settings["explicit_chart_lock"] = bool(settings.get("explicit_chart_lock", merged_contract.get("locked", True)))
        settings["fallback_reason"] = ""
        settings["fallback_applied"] = False
        settings["overwritten_by"] = ""
        if str(settings.get("metric_type", "")).strip().lower() in {"percentage", "percent", "ratio"} and display == "pie":
            settings["value_format"] = "percent"

        self._apply_series_style_hints(settings, display=display)
        existing_trace = settings.get("chart_decision_trace")
        chart_trace = dict(existing_trace) if isinstance(existing_trace, dict) else {}
        chain = chart_trace.get("decision_chain")
        normalized_chain = list(chain) if isinstance(chain, list) else []
        normalized_chain.append(
            {
                "stage": "visualization-service",
                "chart": final_chart_type,
                "action": "sent_to_metabase",
                "reason": "renderer_only",
            }
        )
        chart_trace.update(
            {
                "upstream_chart": requested_chart_type,
                "initial_selected_chart": requested_chart_type,
                "final_chart": final_chart_type,
                "chart_locked": bool(settings.get("chart_locked")),
                "explicit_chart_lock": bool(settings.get("explicit_chart_lock")),
                "overwritten": False,
                "overwritten_by": None,
                "reason": "renderer_only",
                "fallback_reason": None,
                "decision_chain": normalized_chain,
            }
        )
        settings["chart_decision_trace"] = chart_trace
        self.last_display = display
        self.last_fallback_applied = False
        self.last_fallback_reason = ""
        logger.info(
            "chart_selection_result display=%s fallback_applied=%s fallback_reason=%s requested_display=%s",
            display,
            self.last_fallback_applied,
            self.last_fallback_reason,
            display,
        )
        return display, settings, None

    def health_check(self) -> bool:
        healthy = check_metabase_health()
        if not healthy:
            self._set_last_error("metabase_unavailable")
        return healthy

    def _headers(self) -> Dict[str, str]:
        return get_metabase_headers()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        retry_on_401: bool = True,
    ) -> Optional[requests.Response]:
        if not self.health_check():
            return None

        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        headers = self._headers()

        if not headers.get("X-Metabase-Session"):
            self._set_last_error("metabase_authentication_failed")
            return None

        response = _http_request(method, url, headers=headers, json=json, timeout_seconds=METABASE_TIMEOUT_SECONDS)
        if response is None:
            self._set_last_error("metabase_request_error")
            return None

        if response.status_code == 401 and retry_on_401:
            clear_metabase_session()
            if get_metabase_session(force_refresh=True):
                headers = self._headers()
                response = _http_request(method, url, headers=headers, json=json, timeout_seconds=METABASE_TIMEOUT_SECONDS)
                if response is None:
                    self._set_last_error("metabase_request_error_after_refresh")
                    logger.error("Metabase retry request failed %s %s", method, path)
                    return None
            else:
                self._set_last_error("metabase_authentication_failed")
                return None

        if response.status_code in {502, 503, 504}:
            time.sleep(1)
            response = _http_request(method, url, headers=headers, json=json, timeout_seconds=METABASE_TIMEOUT_SECONDS)
            if response is None:
                self._set_last_error("metabase_request_error_retry")
                logger.error("Metabase retry after 5xx failed %s %s", method, path)
                return None
        return response

    def authenticate(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        # username/password override intentionally ignored; env-based auth only.
        _ = username, password
        if not self.health_check():
            return False
        authenticated = get_metabase_session(force_refresh=True) is not None
        self._set_last_error(None if authenticated else "metabase_authentication_failed")
        return authenticated

    def create_question(
        self,
        name: str,
        sql: str,
        description: str = "",
        visualization_settings: Optional[Dict] = None,
    ) -> Optional[int]:
        self._set_last_error(None)
        if not str(name or "").strip() or not str(sql or "").strip():
            self._set_last_error("invalid_payload:name_and_sql_required")
            return None
        display, normalized_visualization_settings, prep_error = self._prepare_visualization_settings(visualization_settings)
        if prep_error:
            self._set_last_error(prep_error)
            return None

        sanitized_sql = sanitize_sql_for_metabase(sql)
        if str(sql or "").strip().endswith(";"):
            logger.warning("Trailing semicolon detected and removed for Metabase compatibility")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Metabase SQL sanitization original_sql=%r sanitized_sql=%r", sql, sanitized_sql)

        payload: Dict[str, Any] = {
            "name": name,
            "dataset_query": {
                "type": "native",
                "native": {"query": sanitized_sql},
                "database": self.database_id,
            },
            "display": display,
            "visualization_settings": normalized_visualization_settings,
        }
        clean_description = self._clean_non_blank_string(description)
        if clean_description is not None:
            payload["description"] = clean_description

        logger.info(
            "Creating Metabase question: name=%s database_id=%s display=%s sql_len=%s chart_selected=%s prep_error=%s",
            name,
            self.database_id,
            payload.get("display"),
            len(sanitized_sql or ""),
            visualization_settings.get("chart_type") if isinstance(visualization_settings, dict) else "",
            "",
        )
        response = self._request("POST", "/api/card", json=payload)
        if response and response.status_code in (200, 201):
            question_id = response.json().get("id")
            if not isinstance(question_id, int):
                self._set_last_error("create_question_failed: invalid_response_missing_id")
                logger.error(
                    "Create question returned invalid payload: %s",
                    self._extract_error_details(response)
                )
                return None
            logger.info("Created Metabase question id=%s", question_id)
            return question_id
        if response:
            details = self._extract_error_details(response)
            self._set_last_error(f"create_question_failed: {details}")
            logger.error("Create question failed: %s %s", response.status_code, details)
        elif self.last_error is None:
            self._set_last_error("create_question_failed: no_response")
        return None

    def update_question(
        self,
        card_id: int,
        name: str,
        sql: str,
        description: str = "",
        visualization_settings: Optional[Dict] = None,
    ) -> bool:
        self._set_last_error(None)
        display, normalized_visualization_settings, prep_error = self._prepare_visualization_settings(visualization_settings)
        if prep_error:
            self._set_last_error(prep_error)
            return False

        sanitized_sql = sanitize_sql_for_metabase(sql)
        if str(sql or "").strip().endswith(";"):
            logger.warning("Trailing semicolon detected and removed for Metabase compatibility")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Metabase SQL sanitization original_sql=%r sanitized_sql=%r", sql, sanitized_sql)

        payload: Dict[str, Any] = {
            "name": name,
            "dataset_query": {
                "type": "native",
                "native": {"query": sanitized_sql},
                "database": self.database_id,
            },
            "display": display,
            "visualization_settings": normalized_visualization_settings,
        }
        clean_description = self._clean_non_blank_string(description)
        if clean_description is not None:
            payload["description"] = clean_description

        response = self._request("PUT", f"/api/card/{card_id}", json=payload)
        if response and response.status_code == 200:
            return True
        if response:
            details = self._extract_error_details(response)
            self._set_last_error(f"update_question_failed: {details}")
        elif self.last_error is None:
            self._set_last_error("update_question_failed: no_response")
        return False

    def create_dashboard(self, name: str, description: str = "") -> Optional[int]:
        self._set_last_error(None)
        payload: Dict[str, Any] = {"name": name}
        clean_description = self._clean_non_blank_string(description)
        if clean_description is not None:
            payload["description"] = clean_description
        response = self._request("POST", "/api/dashboard", json=payload)
        if response and response.status_code in (200, 201):
            dashboard_id = response.json().get("id")
            return dashboard_id
        if response:
            details = self._extract_error_details(response)
            self._set_last_error(f"create_dashboard_failed: {details}")
        elif self.last_error is None:
            self._set_last_error("create_dashboard_failed: no_response")
        return None

    def update_dashboard(self, dashboard_id: int, name: Optional[str] = None, description: Optional[str] = None) -> bool:
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        clean_description = self._clean_non_blank_string(description)
        if clean_description is not None:
            payload["description"] = clean_description
        if not payload:
            return True
        response = self._request("PUT", f"/api/dashboard/{dashboard_id}", json=payload)
        if response and response.status_code == 200:
            return True
        if response:
            details = self._extract_error_details(response)
            self._set_last_error(f"update_dashboard_failed: {details}")
        elif self.last_error is None:
            self._set_last_error("update_dashboard_failed: no_response")
        return False

    def add_question_to_dashboard(
        self,
        question_id: int,
        dashboard_id: int,
        row: int = 0,
        col: int = 0,
        size_x: int = 6,
        size_y: int = 4,
    ) -> bool:
        self._set_last_error(None)
        if not isinstance(question_id, int) or question_id <= 0:
            self._set_last_error("add_to_dashboard_failed: invalid_question_id")
            return False
        if not isinstance(dashboard_id, int) or dashboard_id <= 0:
            self._set_last_error("add_to_dashboard_failed: invalid_dashboard_id")
            return False
        if self.get_dashboard(dashboard_id) is None:
            self._set_last_error("add_to_dashboard_failed: dashboard_not_found")
            return False
        if self.get_card(question_id) is None:
            self._set_last_error("add_to_dashboard_failed: card_not_found")
            return False
        payload = {
            "cardId": question_id,
            "row": row,
            "col": col,
            "sizeX": size_x,
            "sizeY": size_y,
        }
        response = self._request("POST", f"/api/dashboard/{dashboard_id}/cards", json=payload)
        if response and response.status_code in (200, 201):
            return True
        if response:
            details = self._extract_error_details(response)
            logger.error(
                "Metabase add-to-dashboard failed endpoint=%s status=%s dashboard_id=%s card_id=%s payload_keys=%s response=%s",
                f"/api/dashboard/{dashboard_id}/cards",
                response.status_code,
                dashboard_id,
                question_id,
                sorted(payload.keys()),
                details[:300],
            )
            self._set_last_error(f"add_to_dashboard_failed: {details}")
        elif self.last_error is None:
            self._set_last_error("add_to_dashboard_failed: no_response")
        return False

    def get_dashboard(self, dashboard_id: int) -> Optional[Dict]:
        response = self._request("GET", f"/api/dashboard/{dashboard_id}")
        if response and response.status_code == 200:
            return response.json()
        return None

    def get_card(self, card_id: int) -> Optional[Dict]:
        response = self._request("GET", f"/api/card/{card_id}")
        if response and response.status_code == 200:
            return response.json()
        return None

    def delete_question(self, question_id: int) -> bool:
        response = self._request("DELETE", f"/api/card/{question_id}")
        return bool(response and response.status_code == 204)

    def enable_dashboard_embedding(self, dashboard_id: int) -> bool:
        response = self._request(
            "PUT",
            f"/api/dashboard/{dashboard_id}",
            json={"enable_embedding": True},
        )
        return bool(response and response.status_code == 200)

    def enable_question_embedding(self, question_id: int) -> bool:
        response = self._request(
            "PUT",
            f"/api/card/{question_id}",
            json={"enable_embedding": True},
        )
        return bool(response and response.status_code == 200)

    def get_question_embed_url(self, question_id: int, params: Optional[Dict] = None) -> Optional[str]:
        self._set_last_error(None)
        try:
            from .jwt_embedding import get_jwt_service

            jwt_service = get_jwt_service()
            token = jwt_service.generate_question_token(question_id, params=params or {})
            return f"{self.embed_base_url}/embed/question/{token}#bordered=true&titled=true"
        except Exception as exc:
            self._set_last_error(f"question_embed_url_failed: {exc}")
            logger.error("Failed to generate question embed URL for %s: %s", question_id, exc)
            return None

    def get_dashboard_embed_url(self, dashboard_id: int, params: Optional[Dict] = None) -> Optional[str]:
        self._set_last_error(None)
        try:
            from .jwt_embedding import get_jwt_service

            jwt_service = get_jwt_service()
            token = jwt_service.generate_dashboard_token(dashboard_id, params=params or {})
            return f"{self.embed_base_url}/embed/dashboard/{token}#bordered=true&titled=true"
        except Exception as exc:
            self._set_last_error(f"dashboard_embed_url_failed: {exc}")
            logger.error("Failed to generate dashboard embed URL for %s: %s", dashboard_id, exc)
            return None


_metabase_service: Optional[MetabaseService] = None


def get_metabase_service() -> MetabaseService:
    global _metabase_service
    if _metabase_service is None:
        _metabase_service = MetabaseService()
    return _metabase_service


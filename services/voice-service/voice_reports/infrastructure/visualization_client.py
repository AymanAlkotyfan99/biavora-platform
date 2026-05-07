"""voice-service ⇄ visualization-service HTTP client.

This module is the canonical location of the visualization client (CRIT-12
of the BACKEND_FULL_AUDIT_AND_FIX_ROADMAP). It replaces
``voice_reports.infrastructure.report_client`` (deleted): the previous
``ReportClient`` class was misleadingly named because it actually drove
visualization-service.

The class deliberately contains NO chart-shape inference and NO direct
Metabase calls — chart contracts are produced by ai-service and sent to
visualization-service which is the sole owner of Metabase. See CRIT-03.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import requests

from bi_platform_shared.contracts.chart import ChartContract, normalize_chart_type
from bi_platform_shared.http import HttpClientError, get_default_client


logger = logging.getLogger(__name__)

_MIN_INTERNAL_TOKEN_LEN = 32


def _service_internal_authorization_header() -> str:
    """Bearer used for every visualization-service request (service-to-service)."""

    for env_name in (
        "INTERNAL_SERVICE_TOKEN",
        "QUERY_SERVICE_INTERNAL_TOKEN",
        "SERVICE_INTERNAL_TOKEN",
        "INTERNAL_API_TOKEN",
    ):
        raw = str(os.getenv(env_name, "") or "").strip()
        if raw.lower().startswith("bearer "):
            raw = raw[7:].strip()
        if len(raw) >= _MIN_INTERNAL_TOKEN_LEN:
            return f"Bearer {raw}"
    raise RuntimeError(
        "visualization_service_auth_not_configured: set SERVICE_INTERNAL_TOKEN "
        f"(or INTERNAL_API_TOKEN) with length >= {_MIN_INTERNAL_TOKEN_LEN} for internal calls."
    )


def _coerce_chart_contract_dict(chart_payload: Any) -> Dict[str, Any]:
    """Normalize whatever the orchestrator forwarded into a flat contract dict.

    The contract may arrive shaped as the canonical ``ChartContract`` (which
    serializes via ``model_dump``) or as a legacy dict that uses a mix of
    aliases (``selected_chart_type``, ``type``). We standardize the shape and
    let visualization-service do the strict Pydantic validation.
    """

    if isinstance(chart_payload, ChartContract):
        return chart_payload.model_dump()
    if not isinstance(chart_payload, dict):
        raise ValueError("missing_chart_contract_from_ai")

    chart_type = (
        chart_payload.get("chart_type")
        or chart_payload.get("selected_chart_type")
        or chart_payload.get("type")
        or ""
    )
    if not str(chart_type or "").strip():
        raise ValueError("invalid_chart_contract:missing_chart_type")
    canonical_type = normalize_chart_type(str(chart_type or "")).value

    raw_y = chart_payload.get("y_axis")
    if raw_y is None:
        y_axis: List[str] = []
    elif isinstance(raw_y, list):
        y_axis = [str(value).strip() for value in raw_y if str(value or "").strip()]
    else:
        y_axis = [str(raw_y).strip()] if str(raw_y or "").strip() else []

    return {
        "chart_type": canonical_type,
        "x_axis": chart_payload.get("x_axis") or None,
        "y_axis": y_axis,
        "series_dimension": chart_payload.get("series_dimension") or chart_payload.get("series") or None,
        "label_column": chart_payload.get("label_column") or None,
        "value_column": chart_payload.get("value_column") or None,
        "bin_column": chart_payload.get("bin_column") or None,
        "bin_count": chart_payload.get("bin_count"),
        "aggregations": list(chart_payload.get("aggregations") or []),
        "locked": bool(chart_payload.get("locked", chart_payload.get("explicit_chart_lock", True))),
        "chart_source": str(chart_payload.get("chart_source") or "ai_service"),
        "rationale": chart_payload.get("rationale") or chart_payload.get("reason") or chart_payload.get("chart_reason"),
        "metadata": chart_payload.get("metadata") if isinstance(chart_payload.get("metadata"), dict) else {},
        "chart_lock": bool(chart_payload.get("chart_lock", chart_payload.get("explicit_chart_lock", chart_payload.get("locked", True)))),
        "explicit_chart_lock": bool(chart_payload.get("explicit_chart_lock", chart_payload.get("locked", True))),
        "visualization_settings": chart_payload.get("visualization_settings")
        if isinstance(chart_payload.get("visualization_settings"), dict)
        else {},
    }


class VisualizationClient:
    """HTTP client for visualization-service.

    Voice-service owns orchestration; rendering belongs exclusively to
    visualization-service. This client never re-infers chart shape. Chart
    contract failures surface as structured errors (no silent table fallback).
    """

    def __init__(self) -> None:
        self.base_url = os.getenv("VISUALIZATION_SERVICE_URL", "http://visualization-service:8007").rstrip("/")
        self.connect_timeout_seconds = float(
            os.getenv("SERVICE_REQUEST_CONNECT_TIMEOUT_SECONDS", "5")
        )
        self.read_timeout_seconds = float(
            os.getenv("SERVICE_REQUEST_TIMEOUT_SECONDS", "30")
        )
        self._client = get_default_client()

    @staticmethod
    def _headers(authorization_header: str = "") -> Dict[str, str]:
        _ = authorization_header
        return {
            "Content-Type": "application/json",
            "Authorization": _service_internal_authorization_header(),
            "X-Internal-Service": "voice-service",
        }

    def create_visualization(
        self,
        *,
        report,
        sql: str,
        chart_payload: Optional[Dict[str, Any]],
        authorization_header: str = "",
    ) -> Dict[str, Any]:
        query_result = report.query_result if isinstance(report.query_result, dict) else {}
        rows = query_result.get("rows") if isinstance(query_result.get("rows"), list) else []
        columns = query_result.get("columns") if isinstance(query_result.get("columns"), list) else []
        try:
            contract_dict = _coerce_chart_contract_dict(chart_payload)
        except ValueError as exc:
            return {
                "success": False,
                "status": "failed",
                "error": "chart_contract_incompatible",
                "detail": str(exc),
                "chart_contract": {},
            }

        payload = {
            "name": str(report.transcription or f"Report {report.id}").strip() or f"Report {report.id}",
            "sql": sql,
            "rows": rows,
            "columns": columns,
            "intent": report.intent_json if isinstance(report.intent_json, dict) else {},
            "chart_contract": contract_dict,
        }
        endpoint = f"{self.base_url}/visualization/question/create/"
        try:
            response = self._client.post(
                endpoint,
                json=payload,
                headers=self._headers(authorization_header),
                timeout=(self.connect_timeout_seconds, self.read_timeout_seconds),
            )
        except HttpClientError as exc:
            logger.warning("visualization_service_unreachable", extra={"error": str(exc), "url": endpoint})
            return {"success": False, "status": "failed", "error": f"visualization_service_unavailable: {exc}"}
        except requests.RequestException as exc:
            return {"success": False, "status": "failed", "error": f"visualization_service_unavailable: {exc}"}

        try:
            body = response.json()
        except ValueError:
            body = {"error": response.text[:300]}

        if response.status_code == 400 and isinstance(body, dict) and body.get("error") == "chart_contract_incompatible":
            return {
                "success": False,
                "status": "failed",
                "error": "chart_contract_incompatible",
                "detail": str(body.get("detail") or ""),
                "upstream_chart": contract_dict.get("chart_type"),
                "chart_contract": contract_dict,
                "chart_contract_incompatible": True,
            }

        if (
            response.status_code == 200
            and isinstance(body, dict)
            and body.get("success")
            and str(body.get("render_status") or "").lower() == "degraded"
        ):
            return {
                "success": True,
                "status": "degraded",
                "render_status": "degraded",
                "metabase_status": str(body.get("metabase_status") or "unavailable"),
                "question_id": None,
                "embed_url": "",
                "chart_type": body.get("final_chart_type") or body.get("chart_type") or contract_dict.get("chart_type"),
                "requested_chart_type": contract_dict.get("chart_type"),
                "final_chart_type": body.get("final_chart_type") or body.get("chart_type") or contract_dict.get("chart_type"),
                "fallback_used": False,
                "fallback_reason": None,
                "user_message": str(body.get("user_message") or ""),
                "trace": body.get("trace", []),
                "chart_contract": body.get("chart_contract") or contract_dict,
            }

        if response.status_code >= 400 or not isinstance(body, dict) or not body.get("success"):
            return {
                "success": False,
                "status": "failed",
                "error": (body.get("error") if isinstance(body, dict) else "") or f"visualization_http_{response.status_code}",
                "detail": str(body.get("detail") or "") if isinstance(body, dict) else "",
                "chart_contract": contract_dict,
            }

        question_id = body.get("metabase_question_id") or body.get("question_id")
        embed_url = body.get("embed_url") or ""
        if question_id and not embed_url:
            embed_url = self.get_question_embed_url(question_id, authorization_header=authorization_header)

        return {
            "success": True,
            "status": body.get("status", "success"),
            "render_status": str(body.get("render_status") or "success"),
            "contract_preserved": bool(body.get("contract_preserved", True)),
            "question_id": question_id,
            "embed_url": embed_url,
            "chart_type": body.get("final_chart_type") or body.get("chart_type"),
            "requested_chart_type": body.get("requested_chart_type") or contract_dict.get("chart_type"),
            "final_chart_type": body.get("final_chart_type") or body.get("chart_type"),
            "fallback_used": bool(body.get("fallback_used") or body.get("fallback_applied")),
            "fallback_reason": body.get("fallback_reason"),
            "trace": body.get("trace", []),
            "chart_contract": body.get("chart_contract") or contract_dict,
        }

    def create_empty_state_card(
        self,
        *,
        sql: str,
        message: str,
        authorization_header: str = "",
        name: str = "Empty result",
    ) -> Dict[str, Any]:
        """GAP-04 helper for the orchestration empty-result branch."""

        endpoint = f"{self.base_url}/visualization/empty-state/"
        try:
            response = self._client.post(
                endpoint,
                json={"sql": sql, "message": message, "name": name},
                headers=self._headers(authorization_header),
                timeout=(self.connect_timeout_seconds, self.read_timeout_seconds),
            )
            body = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
        except (HttpClientError, requests.RequestException, ValueError) as exc:
            return {"success": False, "error": f"empty_state_unreachable: {exc}"}
        if response.status_code >= 400 or not body.get("success"):
            return {"success": False, "error": str(body.get("error") if isinstance(body, dict) else "") or "empty_state_failed"}
        return {
            "success": True,
            "embed_url": body.get("embed_url"),
            "metabase_question_id": body.get("metabase_question_id"),
        }

    def get_question_embed_url(self, question_id: int, *, authorization_header: str = "") -> str:
        endpoint = f"{self.base_url}/visualization/question/{question_id}/embed-url/"
        try:
            response = self._client.get(
                endpoint,
                headers=self._headers(authorization_header),
                timeout=(self.connect_timeout_seconds, self.read_timeout_seconds),
            )
            if response.status_code != 200:
                return ""
            body = response.json()
        except (HttpClientError, requests.RequestException, ValueError):
            return ""
        return str(body.get("embed_url") or "") if isinstance(body, dict) else ""

    def get_dashboard_embed_url(self, dashboard_id: int, *, authorization_header: str = "") -> str:
        endpoint = f"{self.base_url}/visualization/dashboard/{dashboard_id}/embed-url/"
        try:
            response = self._client.get(
                endpoint,
                headers=self._headers(authorization_header),
                timeout=(self.connect_timeout_seconds, self.read_timeout_seconds),
            )
            if response.status_code != 200:
                return ""
            body = response.json()
        except (HttpClientError, requests.RequestException, ValueError):
            return ""
        if not isinstance(body, dict):
            return ""
        return str(body.get("embed_url") or body.get("dashboard_url") or "")

    def health(self) -> bool:
        try:
            response = self._client.get(
                f"{self.base_url}/visualization/health/",
                timeout=(self.connect_timeout_seconds, 5.0),
                attach_internal_api_key=False,
            )
        except (HttpClientError, requests.RequestException):
            return False
        return response.status_code == 200


_singleton: Optional[VisualizationClient] = None


def get_visualization_client() -> VisualizationClient:
    """Process-wide singleton accessor for the visualization client."""

    global _singleton
    if _singleton is None:
        _singleton = VisualizationClient()
    return _singleton


__all__ = ["VisualizationClient", "get_visualization_client"]

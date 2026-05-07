"""voice-service ⇄ query-service client.

Per CRIT-04 voice-service no longer owns SQL safety validation: all SQL
flows through query-service via:

    POST /query/validate/   (safety gate)
    POST /query/execute/    (ClickHouse execution)

The shared HTTP client from ``bi_platform_shared.http`` is used so retries,
the circuit breaker, request-id propagation, and W3C trace context are
handled uniformly.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Optional, Tuple

from bi_platform_shared.http import HttpClientError, get_default_client

from voice_reports.services.query_execution_service import execute_sql_with_query_service

logger = logging.getLogger(__name__)


def _configured_internal_query_secret() -> str:
    raw = str(
        os.getenv("INTERNAL_SERVICE_TOKEN", "")
        or os.getenv("QUERY_SERVICE_INTERNAL_TOKEN", "")
        or os.getenv("INTERNAL_API_TOKEN", "")
        or os.getenv("SERVICE_INTERNAL_TOKEN", "")
        or ""
    ).strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return raw


def _attach_voice_internal_service_header(headers: dict[str, str], bearer_token: str) -> None:
    """Set ``X-Internal-Service`` only when the bearer is the shared internal secret (not a user JWT)."""

    candidate = str(bearer_token or "").strip()
    if candidate.lower().startswith("bearer "):
        candidate = candidate[7:].strip()
    secret = _configured_internal_query_secret()
    if secret and candidate and secrets.compare_digest(candidate, secret):
        headers["X-Internal-Service"] = "voice-service"


def _query_service_url() -> str:
    return os.getenv("QUERY_SERVICE_URL", "http://query-service:8006").rstrip("/")


def validate_sql_via_query_service(
    *,
    sql: str,
    token: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """Validate SQL by calling query-service /query/validate/.

    Returns ``(is_valid, error_message, normalized_sql)`` so call-sites can
    fail fast on rejection without inspecting HTTP responses themselves.
    """

    payload = {"sql": sql or ""}
    if workspace_id:
        payload["workspace_id"] = str(workspace_id)
    headers = {"Content-Type": "application/json"}
    bearer = str(token or "").strip()
    if not bearer:
        bearer = str(
            os.getenv("INTERNAL_API_TOKEN", "")
            or os.getenv("SERVICE_INTERNAL_TOKEN", "")
            or os.getenv("INTERNAL_SERVICE_TOKEN", "")
            or ""
        ).strip()
        if bearer.lower().startswith("bearer "):
            bearer = bearer[7:].strip()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
        _attach_voice_internal_service_header(headers, bearer)
    else:
        logger.error("validate_sql_missing_auth_no_user_token_and_no_SERVICE_INTERNAL_TOKEN")

    endpoint = f"{_query_service_url()}/query/validate/"
    try:
        response = get_default_client().post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=(5.0, float(os.getenv("SERVICE_REQUEST_TIMEOUT_SECONDS", "30"))),
            attach_internal_api_key=False,
        )
    except HttpClientError as exc:
        logger.warning("validate_sql_unreachable", extra={"error": str(exc)})
        return False, "query_service_unreachable", sql or ""

    if response.status_code == 401:
        return False, "query_service_unauthorized", sql or ""

    if response.status_code >= 500:
        return False, f"query_service_error:{response.status_code}", sql or ""

    try:
        body = response.json()
    except ValueError:
        return False, "query_service_invalid_response", sql or ""

    is_valid = bool(body.get("is_valid") or body.get("safe") or body.get("success"))
    error_message = str(body.get("error") or body.get("message") or ("validation_passed" if is_valid else "sql_rejected"))
    normalized = str(body.get("normalized_sql") or body.get("clean_sql") or sql or "")
    return is_valid, error_message, normalized


class QueryClient:
    """Thin wrapper for query-service ``/query/execute/`` calls.

    Phase 7 / CRIT-05: ``workspace_id`` is now required. The legacy
    ``workspace_database`` kwarg is accepted but ignored — query-service
    resolves the canonical ClickHouse database from the workspace itself.
    """

    def execute(
        self,
        *,
        sql: str,
        authorization_header: str,
        workspace_id: str,
        workspace_database: Optional[str] = None,
    ):
        if not workspace_id:
            return {"success": False, "error": "workspace_id_required"}
        headers = {"Content-Type": "application/json"}
        auth_hdr = str(authorization_header or "").strip()
        if auth_hdr:
            headers["Authorization"] = auth_hdr
            _attach_voice_internal_service_header(headers, auth_hdr)
        else:
            internal = str(
                os.getenv("INTERNAL_SERVICE_TOKEN", "")
                or os.getenv("QUERY_SERVICE_INTERNAL_TOKEN", "")
                or os.getenv("INTERNAL_API_TOKEN", "")
                or os.getenv("SERVICE_INTERNAL_TOKEN", "")
                or ""
            ).strip()
            if internal.lower().startswith("bearer "):
                internal = internal[7:].strip()
            if internal:
                headers["Authorization"] = f"Bearer {internal}"
                _attach_voice_internal_service_header(headers, internal)
            else:
                logger.error("query_execute_missing_auth_no_user_header_and_no_SERVICE_INTERNAL_TOKEN")
        headers["X-Workspace-Id"] = str(workspace_id)
        return execute_sql_with_query_service(
            clean_sql=sql,
            headers=headers,
            workspace_id=str(workspace_id),
            query_service_url=_query_service_url(),
            timeout_seconds=int(os.getenv("SERVICE_REQUEST_TIMEOUT_SECONDS", "30")),
            workspace_database=workspace_database,
        )


def get_query_client() -> QueryClient:
    return QueryClient()


__all__ = ["QueryClient", "get_query_client", "validate_sql_via_query_service"]

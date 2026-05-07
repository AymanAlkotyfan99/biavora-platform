"""Voice-service ⇄ query-service execution helper (Phase 7 / CRIT-05).

The body sent to ``/query/execute/`` MUST carry ``workspace_id``: query-service
ignores any client-supplied ``workspace_database`` and resolves the tenant's
ClickHouse database from the workspace itself. ``workspace_database`` is
deliberately not included in the payload to make the contract obvious.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
    _SHARED_CLIENT_AVAILABLE = True
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]
    _SHARED_CLIENT_AVAILABLE = False

logger = logging.getLogger(__name__)


def execute_sql_with_query_service(
    *,
    clean_sql: str,
    headers: dict[str, str],
    workspace_id: str,
    query_service_url: str,
    timeout_seconds: int,
    workspace_database: Optional[str] = None,
) -> dict[str, Any]:
    if not workspace_id:
        return {
            "success": False,
            "error": "workspace_id_required",
        }
    payload: dict[str, Any] = {
        "sql": clean_sql,
        "workspace_id": str(workspace_id),
    }
    # ``workspace_database`` is intentionally NOT forwarded: query-service
    # resolves the canonical ClickHouse DB from ``workspace_id``. We accept
    # the kwarg for backward compatibility with old call sites but ignore it.
    _ = workspace_database
    endpoint = f"{query_service_url.rstrip('/')}/query/execute/"
    timeout_s = max(1, int(timeout_seconds))
    try:
        if _SHARED_CLIENT_AVAILABLE:
            response = get_default_client().post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=(min(5.0, float(timeout_s)), float(timeout_s)),
                attach_internal_api_key=False,
            )
        else:
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=timeout_s,
            )
        if response.status_code == 200:
            result = response.json()
            if isinstance(result, dict) and result.get("success"):
                return result
            return {
                "success": False,
                "error": (result.get("error") if isinstance(result, dict) else "") or "query_service_execution_failed",
            }
        return {
            "success": False,
            "error": f"query_service_http_{response.status_code}",
            "details": (response.text or "")[:500],
        }
    except HttpClientError as exc:  # type: ignore[misc]
        logger.warning("Query service request failed: %s", exc)
        return {
            "success": False,
            "error": "query_service_unavailable",
        }
    except requests.RequestException as exc:
        logger.warning("Query service request failed: %s", exc)
        return {
            "success": False,
            "error": "query_service_unavailable",
        }

from __future__ import annotations

import logging
import os
from typing import Any

from bi_platform_shared.http import HttpClientError, get_default_client

logger = logging.getLogger(__name__)


def validate_sql_via_query_service(
    *,
    sql: str,
    token: str | None,
    workspace_id: str | None = None,
) -> tuple[bool, str, str]:
    """Validate SQL via query-service (GAP-05 shared HTTP client).

    ``workspace_id`` is required by query-service (Phase 7 / CRIT-05); when
    omitted this helper returns a deterministic client-side error.
    """

    if not (workspace_id and str(workspace_id).strip()):
        return False, "workspace_id_required", sql or ""

    endpoint = f"{os.getenv('QUERY_SERVICE_URL', 'http://query-service:8006').rstrip('/')}/query/validate/"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = get_default_client().post(
            endpoint,
            json={"sql": sql, "workspace_id": str(workspace_id).strip()},
            headers=headers,
            timeout=(5.0, 15.0),
            attach_internal_api_key=False,
        )
    except HttpClientError as exc:
        logger.warning("validate_sql_unreachable", extra={"error": str(exc)})
        return False, "query_service_unreachable", sql or ""

    try:
        payload: dict[str, Any] = response.json() if response.content else {}
    except ValueError:
        return False, "query_service_invalid_response", sql or ""

    if response.status_code == 200 and bool(payload.get("success")):
        return True, "", str(payload.get("sql") or sql)
    return False, str(payload.get("error") or "sql_validation_failed"), str(payload.get("sql") or sql)

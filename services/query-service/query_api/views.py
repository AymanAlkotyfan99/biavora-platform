"""query-service HTTP views (Phase 7 / CRIT-05).

Phase 7 of the audit removes the legacy hardcoded ``workspace_database = "etl"``
fallback and forces every internal entry point (``/query/validate/``,
``/query/execute/``) to:

1. REQUIRE a ``workspace_id`` in the request body.
2. Resolve the workspace's ClickHouse database via
   :func:`resolve_workspace_clickhouse_db`.
3. Bind that database into ``SQLGuard`` so cross-tenant table references are
   rejected with HTTP 403 instead of being silently re-routed.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import SessionAuthentication

from query_api.authentication import ServiceInternalTokenAuthentication
from query_api.application.query_execution import execute_sql_payload
from query_api.services import (
    SQLGuard,
    WorkspaceClickhouseDbResolutionError,
    get_clickhouse_executor,
    resolve_workspace_clickhouse_db,
)
from query_api.sql_parser import ensure_sql_parser_ready

logger = logging.getLogger(__name__)


def _resolution_error_response(exc: WorkspaceClickhouseDbResolutionError) -> Response:
    """Map a workspace-resolution error to a stable HTTP response."""

    return Response(
        {
            "success": False,
            "error": str(exc),
            "error_code": exc.code,
        },
        status=int(exc.http_status or status.HTTP_400_BAD_REQUEST),
    )


class QueryHealthView(APIView):
    permission_classes = []

    def get(self, request):
        executor = get_clickhouse_executor()
        parser_status = ensure_sql_parser_ready(strict=False)
        return Response(
            {
                "success": executor.test_connection(),
                "service": "query-service",
                "sql_parser": parser_status.parser,
                "sql_parser_available": parser_status.available,
            },
            status=status.HTTP_200_OK,
        )


class QueryValidateInternalView(APIView):
    """Validate a SQL string against the per-workspace ClickHouse database.

    Phase 7 / CRIT-05: ``workspace_id`` is mandatory; the legacy ``"etl"``
    fallback is gone. The response carries the resolved database name so the
    caller can verify it received the expected tenant.
    """

    authentication_classes = [
        ServiceInternalTokenAuthentication,
        JWTAuthentication,
        SessionAuthentication,
    ]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        sql = str(request.data.get("sql", "") or "")
        workspace_id = request.data.get("workspace_id")

        try:
            resolution = resolve_workspace_clickhouse_db(workspace_id)
        except WorkspaceClickhouseDbResolutionError as exc:
            logger.warning(
                "query_validate_workspace_unresolved code=%s message=%s",
                exc.code,
                str(exc),
            )
            return _resolution_error_response(exc)

        guard = SQLGuard(workspace_database=resolution.clickhouse_db)
        is_valid, error_msg, clean_sql = guard.validate_and_sanitize(sql)

        if not is_valid:
            cross_db = error_msg.startswith("database_mismatch") or error_msg.startswith("cross_db_violation")
            response_payload: Dict[str, Any] = {
                "success": False,
                "error": error_msg,
                "sql": clean_sql,
                "workspace_id": resolution.workspace_id,
                "workspace_database": resolution.clickhouse_db,
            }
            return Response(
                response_payload,
                status=status.HTTP_403_FORBIDDEN if cross_db else status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "success": True,
                "sql": clean_sql,
                "workspace_id": resolution.workspace_id,
                "workspace_database": resolution.clickhouse_db,
            },
            status=status.HTTP_200_OK,
        )


class QueryExecuteInternalView(APIView):
    """Execute a SQL statement against the per-workspace ClickHouse database.

    Phase 7 / CRIT-05: ``workspace_id`` is required. We resolve the
    ClickHouse database here, replace the previous client-supplied
    ``workspace_database`` field with the canonical value, then delegate to
    :func:`execute_sql_payload`.
    """

    authentication_classes = [
        ServiceInternalTokenAuthentication,
        JWTAuthentication,
        SessionAuthentication,
    ]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            resolution = resolve_workspace_clickhouse_db(request.data.get("workspace_id"))
        except WorkspaceClickhouseDbResolutionError as exc:
            logger.warning(
                "query_execute_workspace_unresolved code=%s message=%s",
                exc.code,
                str(exc),
            )
            return _resolution_error_response(exc)

        # Strip any client-provided ``workspace_database`` / ``database`` so a
        # malicious caller cannot override the workspace-derived value.
        sanitized_payload: Dict[str, Any] = {
            key: value
            for key, value in (request.data.items() if hasattr(request.data, "items") else dict(request.data).items())
            if key not in {"workspace_database", "database"}
        }
        sanitized_payload["workspace_id"] = resolution.workspace_id
        sanitized_payload["workspace_database"] = resolution.clickhouse_db

        payload, status_code = execute_sql_payload(sanitized_payload)
        payload = {"success": payload.get("status") == "success", **payload}
        return Response(payload, status=status_code)

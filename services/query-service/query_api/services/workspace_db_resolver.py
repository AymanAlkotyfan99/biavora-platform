"""Workspace -> ClickHouse database resolver (Phase 7 / CRIT-05).

Phase 7 of the audit requires that **every** internal query-service entry
point (validate, execute) explicitly resolves the per-workspace ClickHouse
database from the database/workspace models BEFORE handing SQL to
``SQLGuard``. The hardcoded ``"etl"`` fallback that lived in the views and
in ``execute_sql_payload`` has been deleted.

The platform stores the per-tenant ClickHouse database on the
``database.Database`` model (one-to-one with each manager). A Workspace is
owned by a manager, so resolving it is:

    workspace.owner.database.clickhouse_database

If any of those records is missing or the resulting string is empty we
raise :class:`WorkspaceClickhouseDbResolutionError` so the API returns a
precise HTTP 400/403 instead of silently routing the query to the wrong
database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class WorkspaceClickhouseDbResolutionError(Exception):
    """Raised when a workspace cannot be bound to a ClickHouse database.

    Carries a stable ``code`` so the API layer can branch deterministically:
      - ``workspace_id_missing``     – the request did not include workspace_id
      - ``workspace_not_found``      – workspace_id is unknown
      - ``workspace_owner_missing``  – workspace exists but has no owner
      - ``workspace_database_missing`` – owner has no ``Database`` record
      - ``workspace_clickhouse_db_missing`` – database row has no ``clickhouse_database``
    """

    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = int(http_status)


@dataclass(frozen=True)
class WorkspaceClickhouseDbResolution:
    workspace_id: int
    clickhouse_db: str
    workspace_name: str = ""


def resolve_workspace_clickhouse_db(workspace_id: object) -> WorkspaceClickhouseDbResolution:
    """Resolve a workspace_id to its bound ClickHouse database name.

    Phase 7 / CRIT-05: This helper is the **only** place that maps a
    workspace identifier to the ClickHouse database string. Both
    ``QueryValidateInternalView`` and ``QueryExecuteInternalView`` consume
    its output instead of trusting client-supplied ``workspace_database``
    values.
    """

    if workspace_id in (None, "", b""):
        raise WorkspaceClickhouseDbResolutionError(
            "workspace_id_missing",
            "Internal query API requires workspace_id; none was provided.",
            http_status=400,
        )

    try:
        workspace_id_int = int(workspace_id)
    except (TypeError, ValueError) as exc:
        raise WorkspaceClickhouseDbResolutionError(
            "workspace_id_missing",
            f"Internal query API requires a numeric workspace_id (got {workspace_id!r}).",
            http_status=400,
        ) from exc

    # Local imports keep this module Django-import-safe at module load time
    # (Django apps may not yet be ready when settings load).
    from workspace.models import Workspace  # type: ignore

    try:
        workspace = (
            Workspace.objects.select_related("owner__database").get(pk=workspace_id_int)
        )
    except Workspace.DoesNotExist as exc:
        raise WorkspaceClickhouseDbResolutionError(
            "workspace_not_found",
            f"Workspace {workspace_id_int} does not exist.",
            http_status=404,
        ) from exc

    owner = getattr(workspace, "owner", None)
    if owner is None:
        raise WorkspaceClickhouseDbResolutionError(
            "workspace_owner_missing",
            f"Workspace {workspace_id_int} has no owner; cannot resolve ClickHouse database.",
            http_status=403,
        )

    database = getattr(owner, "database", None)
    if database is None:
        raise WorkspaceClickhouseDbResolutionError(
            "workspace_database_missing",
            (
                f"Workspace {workspace_id_int} owner {owner.pk} has no uploaded database; "
                "no ClickHouse target can be resolved."
            ),
            http_status=403,
        )

    clickhouse_db = str(getattr(database, "clickhouse_database", "") or "").strip()
    if not clickhouse_db:
        raise WorkspaceClickhouseDbResolutionError(
            "workspace_clickhouse_db_missing",
            (
                f"Workspace {workspace_id_int} database row has an empty clickhouse_database; "
                "the workspace cannot run analytical queries."
            ),
            http_status=403,
        )

    return WorkspaceClickhouseDbResolution(
        workspace_id=workspace_id_int,
        clickhouse_db=clickhouse_db,
        workspace_name=str(workspace.name or ""),
    )


__all__ = [
    "WorkspaceClickhouseDbResolution",
    "WorkspaceClickhouseDbResolutionError",
    "resolve_workspace_clickhouse_db",
]

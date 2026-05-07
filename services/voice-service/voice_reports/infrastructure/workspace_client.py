from __future__ import annotations

import os
from dataclasses import dataclass

import requests

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
    _SHARED_CLIENT_AVAILABLE = True
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]
    _SHARED_CLIENT_AVAILABLE = False


@dataclass
class WorkspaceContext:
    workspace_id: str
    manager_id: str
    dataset_id: str
    source_id: str
    table_name: str


class WorkspaceClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("WORKSPACE_SERVICE_URL", "http://workspace-service:8002").rstrip("/")
        self.allow_local_fallback = str(
            os.getenv("VOICE_SERVICE_ALLOW_LOCAL_WORKSPACE_FALLBACK", "false")
        ).strip().lower() in {"1", "true", "yes", "on"}

    def _headers(self, authorization_header: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if authorization_header:
            headers["Authorization"] = authorization_header
        return headers

    def _get(self, url: str, *, headers: dict[str, str], timeout: float):
        if _SHARED_CLIENT_AVAILABLE:
            return get_default_client().get(
                url,
                headers=headers,
                timeout=(min(5.0, float(timeout)), float(timeout)),
                attach_internal_api_key=False,
            )
        return requests.get(url, headers=headers, timeout=timeout)

    def resolve(self, *, request, workspace_hint: str, user_id: str, allow_local_resolver=None) -> WorkspaceContext:
        workspace_id = workspace_hint
        manager_id = user_id

        if workspace_id:
            try:
                response = self._get(
                    f"{self.base_url}/workspace/{workspace_id}/",
                    headers=self._headers(str(request.META.get("HTTP_AUTHORIZATION") or "")),
                    timeout=10,
                )
                if response.status_code == 200:
                    payload = response.json() if response.content else {}
                    nested = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
                    manager_id = str(
                        payload.get("manager_id")
                        or nested.get("owner_id")
                        or manager_id
                    )
            except (HttpClientError, requests.RequestException, Exception):
                pass

        if (not workspace_id) and self.allow_local_fallback and callable(allow_local_resolver):
            workspace = allow_local_resolver(request.user)
            if workspace is not None:
                workspace_id = str(workspace.id)

        # Phase 13 / GAP-08: do not call query-service ``/database/`` to guess a
        # default dataset. Callers pass ``dataset_id`` / ``table_name`` on the
        # request (stored on the pipeline job trace) or leave them empty.

        return WorkspaceContext(
            workspace_id=str(workspace_id or "").strip(),
            manager_id=str(manager_id or "").strip(),
            dataset_id="",
            source_id="",
            table_name="",
        )


def get_workspace_client() -> WorkspaceClient:
    return WorkspaceClient()

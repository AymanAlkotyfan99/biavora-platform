from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class IdentityContext:
    user_id: str
    workspace_hint: str
    authorization_header: str


def extract_identity_context(request) -> IdentityContext:
    auth_header = str(request.META.get("HTTP_AUTHORIZATION") or "").strip()
    user_id = str(getattr(request.user, "id", "") or "").strip()
    workspace_hint = str(request.data.get("workspace_id") or request.query_params.get("workspace_id") or "").strip()
    return IdentityContext(user_id=user_id, workspace_hint=workspace_hint, authorization_header=auth_header)

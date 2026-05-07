"""
Single canonical DRF permission set used by every microservice.

Replaces the three duplicated copies that previously lived in:

    services/auth-service/users/permissions.py
    services/voice-service/voice_reports/permissions.py (and `users/permissions.py`)
    services/report-service/users/permissions.py

The behavior matches the original implementations: role is derived from
``request.user.role`` and a request is permitted only when the user is both
authenticated and assigned to one of the allowed roles. Anonymous users are
always rejected.
"""

from __future__ import annotations

from typing import FrozenSet

from rest_framework.permissions import BasePermission


def _user_role(request) -> str:
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    return str(getattr(user, "role", "") or "").strip().lower()


class _RoleGate(BasePermission):
    allowed_roles: FrozenSet[str] = frozenset()

    def has_permission(self, request, view) -> bool:  # noqa: D401
        return _user_role(request) in self.allowed_roles


class IsManager(_RoleGate):
    allowed_roles = frozenset({"manager"})


class IsAnalyst(_RoleGate):
    allowed_roles = frozenset({"analyst"})


class IsExecutive(_RoleGate):
    allowed_roles = frozenset({"executive"})


class IsAdmin(_RoleGate):
    allowed_roles = frozenset({"admin"})


class IsManagerOrAnalyst(_RoleGate):
    allowed_roles = frozenset({"manager", "analyst"})


__all__ = [
    "IsAdmin",
    "IsAnalyst",
    "IsExecutive",
    "IsManager",
    "IsManagerOrAnalyst",
]

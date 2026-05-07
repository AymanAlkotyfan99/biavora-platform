"""
Internal API key authentication for ai-service endpoints.

Phase 11 / CRIT-16 — Internal API key rotation:

* The decorator now accepts BOTH ``AI_SERVICE_INTERNAL_API_KEY`` (the
  current/primary key) and ``AI_SERVICE_INTERNAL_API_KEY_PREVIOUS`` (the
  previous key, kept valid through a rotation window).
* The ``X-Internal-Api-Key`` header is compared with ``hmac.compare_digest``
  to defeat timing-side-channel attacks.
* Empty keys are rejected so an operator cannot accidentally disable
  authentication by leaving the env var blank.

Operators rotate by:

  1. Setting ``AI_SERVICE_INTERNAL_API_KEY=<new>`` and
     ``AI_SERVICE_INTERNAL_API_KEY_PREVIOUS=<old>`` simultaneously.
  2. Rolling clients to the new key.
  3. Removing ``AI_SERVICE_INTERNAL_API_KEY_PREVIOUS`` to invalidate the old key.
"""

from __future__ import annotations

import hmac
import os
from functools import wraps
from typing import Any, Callable, List

from django.http import JsonResponse


def _auth_required() -> bool:
    return str(os.getenv("AI_SERVICE_REQUIRE_INTERNAL_AUTH", "true")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _accepted_secrets() -> List[str]:
    """Return the list of currently-accepted internal API keys."""

    secrets: List[str] = []
    primary = str(os.getenv("AI_SERVICE_INTERNAL_API_KEY", "")).strip()
    if primary:
        secrets.append(primary)
    previous = str(os.getenv("AI_SERVICE_INTERNAL_API_KEY_PREVIOUS", "")).strip()
    if previous and previous not in secrets:
        secrets.append(previous)
    return secrets


def _matches_any(provided: str, accepted: List[str]) -> bool:
    if not provided:
        return False
    for secret in accepted:
        if hmac.compare_digest(provided, secret):
            return True
    return False


def require_internal_api_key(view_func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not _auth_required():
            return view_func(request, *args, **kwargs)

        accepted = _accepted_secrets()
        if not accepted:
            return JsonResponse(
                {"error": "Internal API authentication is enabled but no shared key is configured."},
                status=503,
            )

        provided = str(request.headers.get("X-Internal-Api-Key", "")).strip()
        if not _matches_any(provided, accepted):
            return JsonResponse(
                {"error": "Unauthorized internal API request."},
                status=401,
            )
        return view_func(request, *args, **kwargs)

    return _wrapped

"""Service-to-service authentication for query-service internal SQL endpoints."""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any, Optional, Tuple

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)


class InternalServiceUser:
    """Minimal authenticated principal for trusted internal callers."""

    is_authenticated = True
    is_active = True
    is_staff = False
    is_superuser = False
    pk = -1

    def __str__(self) -> str:
        return "internal_service"


def _expected_internal_token() -> str:
    return str(
        getattr(settings, "INTERNAL_API_TOKEN", "")
        or getattr(settings, "SERVICE_INTERNAL_TOKEN", "")
        or getattr(settings, "INTERNAL_SERVICE_TOKEN", "")
        or getattr(settings, "QUERY_SERVICE_INTERNAL_TOKEN", "")
        or ""
    ).strip()


def _trusted_internal_services() -> frozenset[str]:
    raw = os.getenv(
        "QUERY_SERVICE_TRUSTED_INTERNAL_SERVICES",
        "ai-service,voice-service,visualization-service,report-service",
    )
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def _dev_internal_auth_bypass_enabled() -> bool:
    return str(os.getenv("DEV_ONLY_INTERNAL_AUTH_BYPASS", "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _looks_like_jwt(token: str) -> bool:
    parts = str(token or "").split(".")
    return len(parts) == 3 and all(len(p) > 0 for p in parts)


class ServiceInternalTokenAuthentication(BaseAuthentication):
    """Authenticate ``Authorization: Bearer`` against the internal API token.

    Policy:

    * Callers that identify as trusted microservices via ``X-Internal-Service``
      **must** present the shared ``INTERNAL_SERVICE_TOKEN`` (or legacy aliases
      resolved in settings). Mismatch → ``AuthenticationFailed`` (HTTP 401).
    * Optional ``DEV_ONLY_INTERNAL_AUTH_BYPASS=true`` allows those callers
      through in development when misconfigured — logged at ``warning`` with
      structured context.
    * Callers **without** ``X-Internal-Service`` that present a Bearer secret
      equal to the configured internal token authenticate as
      ``InternalServiceUser``.
    * A Bearer value that is **not** the internal secret and **not** sent as a
      trusted internal service (e.g. a user JWT) returns ``None`` so
      ``JWTAuthentication`` can handle it — **no** ``invalid_bearer`` noise.
    """

    keyword = "Bearer"

    def authenticate(self, request) -> Optional[Tuple[Any, Any]]:
        expected = _expected_internal_token()
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        internal_svc = str(request.META.get("HTTP_X_INTERNAL_SERVICE", "") or "").strip().lower()
        trusted = internal_svc in _trusted_internal_services()
        dev_bypass = _dev_internal_auth_bypass_enabled()

        if not auth_header or not isinstance(auth_header, str):
            if trusted:
                if dev_bypass:
                    logger.warning(
                        "query_internal_auth_dev_bypass",
                        extra={"service": internal_svc, "reason": "missing_authorization"},
                    )
                    return InternalServiceUser(), {"auth": "dev_bypass_missing_bearer"}
                raise AuthenticationFailed("Internal service calls require Authorization: Bearer.")
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != self.keyword.lower():
            if trusted and not dev_bypass:
                raise AuthenticationFailed("Malformed Authorization header for internal service.")
            return None

        raw_token = parts[1].strip()
        if not raw_token:
            if trusted:
                if dev_bypass:
                    logger.warning(
                        "query_internal_auth_dev_bypass",
                        extra={"service": internal_svc, "reason": "empty_bearer"},
                    )
                    return InternalServiceUser(), {"auth": "dev_bypass_empty_bearer"}
                raise AuthenticationFailed("Empty bearer token for internal service call.")
            logger.warning("query_service_internal_auth_empty_bearer")
            raise AuthenticationFailed("Invalid internal service token.")

        if not expected:
            if trusted:
                if dev_bypass:
                    logger.warning(
                        "query_internal_auth_dev_bypass_unsafe",
                        extra={"service": internal_svc, "reason": "internal_token_unconfigured"},
                    )
                    return InternalServiceUser(), {"auth": "dev_bypass_no_server_token"}
                raise AuthenticationFailed(
                    "query_service internal token is not configured; refusing trusted internal caller."
                )
            return None

        if secrets.compare_digest(raw_token, expected):
            return InternalServiceUser(), {"auth": "internal_service_token"}

        if trusted:
            if dev_bypass:
                logger.warning(
                    "query_internal_auth_dev_bypass_invalid_bearer",
                    extra={"service": internal_svc, "reason": "bearer_does_not_match_server_secret"},
                )
                return InternalServiceUser(), {"auth": "dev_bypass_invalid_bearer"}
            logger.warning(
                "query_internal_auth_rejected",
                extra={"service": internal_svc, "reason": "invalid_internal_bearer"},
            )
            raise AuthenticationFailed("Invalid internal service token.")

        # Opaque bearer that is not the internal secret: let JWT/session try next.
        if not _looks_like_jwt(raw_token):
            logger.debug(
                "query_service_auth_non_internal_opaque_bearer",
                extra={"hint": "Bearer did not match internal secret; delegating to JWT/session"},
            )
        return None

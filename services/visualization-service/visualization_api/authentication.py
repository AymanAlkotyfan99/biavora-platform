"""Internal service bearer authentication (voice-service → visualization-service)."""

from __future__ import annotations

import logging
import secrets
from typing import Any, Optional, Tuple

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)


class InternalServiceUser:
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
        or ""
    ).strip()


class ServiceInternalTokenAuthentication(BaseAuthentication):
    """Validate ``Authorization: Bearer`` against ``SERVICE_INTERNAL_TOKEN``."""

    keyword = "Bearer"

    def authenticate(self, request) -> Optional[Tuple[Any, Any]]:
        expected = _expected_internal_token()
        if not expected:
            return None

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header or not isinstance(auth_header, str):
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != self.keyword.lower():
            return None

        raw_token = parts[1].strip()
        if not raw_token:
            logger.warning("visualization_internal_auth_empty_bearer")
            raise AuthenticationFailed("Invalid internal service token.")

        if not secrets.compare_digest(raw_token, expected):
            logger.warning("visualization_internal_auth_invalid_bearer")
            return None

        return InternalServiceUser(), {"auth": "internal_service_token"}

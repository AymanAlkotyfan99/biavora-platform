"""Bearer token resolution for query-service (Dagster pipeline + sql_review)."""

from __future__ import annotations

import logging
import os
import secrets
from contextvars import ContextVar

logger = logging.getLogger(__name__)

_forwarded_bearer_token: ContextVar[str] = ContextVar("_forwarded_bearer_token", default="")


def set_forwarded_query_service_bearer_token(token: str) -> None:
    """Store a user JWT from the pipeline request (same worker / thread as downstream assets)."""

    raw = str(token or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    _forwarded_bearer_token.set(raw)


def _forwarded_bearer() -> str:
    return str(_forwarded_bearer_token.get() or "").strip()


def _strip_bearer_prefix(raw: str) -> str:
    token = str(raw or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def _django_settings_internal_token() -> str:
    try:
        from django.conf import settings

        for attr in (
            "INTERNAL_SERVICE_TOKEN",
            "QUERY_SERVICE_INTERNAL_TOKEN",
            "INTERNAL_API_TOKEN",
            "SERVICE_INTERNAL_TOKEN",
        ):
            raw = str(getattr(settings, attr, "") or "").strip()
            if raw:
                return _strip_bearer_prefix(raw)
    except Exception:  # noqa: BLE001
        return ""
    return ""


def _service_internal_token_from_env() -> str:
    """Primary shared secret for service-to-service query-service calls."""

    for env_name in (
        "INTERNAL_SERVICE_TOKEN",
        "QUERY_SERVICE_INTERNAL_TOKEN",
        "INTERNAL_API_TOKEN",
        "SERVICE_INTERNAL_TOKEN",
        "QUERY_SERVICE_BEARER_TOKEN",
    ):
        raw = str(os.getenv(env_name, "") or "").strip()
        if raw:
            token = _strip_bearer_prefix(raw)
            logger.info(
                "service_internal_token_resolved",
                extra={"env_var": env_name, "token_length": len(token)},
            )
            return token
    django_tok = _django_settings_internal_token()
    if django_tok:
        logger.info(
            "service_internal_token_resolved",
            extra={"env_var": "django_settings", "token_length": len(django_tok)},
        )
        return django_tok
    logger.warning(
        "service_internal_token_not_found",
        extra={
            "checked_vars": [
                "INTERNAL_SERVICE_TOKEN",
                "QUERY_SERVICE_INTERNAL_TOKEN",
                "INTERNAL_API_TOKEN",
                "SERVICE_INTERNAL_TOKEN",
                "QUERY_SERVICE_BEARER_TOKEN",
            ]
        },
    )
    return ""


def resolve_query_service_bearer_token() -> str:
    """Return bearer secret for query-service: internal token first, then forwarded user JWT."""

    internal = _service_internal_token_from_env()
    if internal:
        logger.debug("query_service_auth_using_internal_token")
        return internal
    
    forwarded = _forwarded_bearer()
    if forwarded:
        logger.debug("query_service_auth_using_forwarded_jwt")
        return forwarded
    
    logger.error(
        "query_service_auth_resolution_failed",
        extra={"hint": "Set SERVICE_INTERNAL_TOKEN or forward user bearer token"},
    )
    return ""


_MIN_INTERNAL_TOKEN_LEN = 32


def bearer_matches_configured_internal_secret(token: str) -> bool:
    """True when ``token`` (with or without ``Bearer ``) equals the configured internal S2S secret."""

    candidate = _strip_bearer_prefix(str(token or ""))
    if not candidate:
        return False
    internal = _service_internal_token_from_env()
    if not internal:
        return False
    return secrets.compare_digest(candidate, internal)


def require_query_service_bearer_token() -> str:
    """Fail fast when no token is available for query-service HTTP (no silent unauthenticated calls)."""

    token = resolve_query_service_bearer_token()
    if not token:
        raise RuntimeError(
            "query_service_auth_not_configured: set INTERNAL_API_TOKEN for service-to-service calls, "
            "or ensure the pipeline forwards the user's Authorization bearer for validation."
        )
    internal = _service_internal_token_from_env()
    if internal and token == internal and len(token) < _MIN_INTERNAL_TOKEN_LEN:
        raise RuntimeError(
            f"query_service_token_too_short: SERVICE_INTERNAL_TOKEN must be >= {_MIN_INTERNAL_TOKEN_LEN} characters "
            "for internal service-to-service authentication."
        )
    return token

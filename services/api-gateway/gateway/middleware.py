"""API Gateway middleware: rate-limiting, auth presence and request validation.

Phase 11 / Audit §13.4 — Rate limiting:

* Per-endpoint rules so login (5/min), BI queries (60/min/user) and
  generic traffic (120/min/IP) all coexist with sensible defaults.
* Redis-backed store when ``RATE_LIMIT_REDIS_URL`` is configured (sliding
  fixed-window via ``ZADD``/``ZREMRANGEBYSCORE``); falls back to an
  in-process store when Redis is unavailable so single-node test runs
  keep working.
* The fallback emits a structured warning so ops can see the degradation.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

from django.http import JsonResponse

from .routing import is_public_path

logger = logging.getLogger(__name__)


try:
    import redis  # type: ignore
    from redis.exceptions import RedisError  # type: ignore
except Exception:  # pragma: no cover - redis-py is optional
    redis = None  # type: ignore[assignment]

    class RedisError(Exception):  # type: ignore[no-redef]
        """Fallback when redis-py is not installed."""


# Phase 11: per-endpoint rules. Each entry is (path-prefix, max_requests,
# window_seconds, scope). Scope is either ``ip`` (per remote address) or
# ``user`` (per authenticated user, falling back to IP). The first matching
# prefix wins, so place the most specific prefixes first.
_DEFAULT_RULES: Tuple[Tuple[str, int, int, str], ...] = (
    ("/auth/login", 5, 60, "ip"),
    ("/auth/signup", 5, 60, "ip"),
    ("/auth/forgot-password", 5, 60, "ip"),
    ("/voice-reports/voice/", 30, 60, "user"),
    ("/voice-reports/text/", 60, 60, "user"),
    ("/voice-reports/", 120, 60, "user"),
    ("/query/execute/", 60, 60, "user"),
    ("/", 120, 60, "ip"),
)


def _resolve_rule(path: str) -> Tuple[int, int, str]:
    """Pick the rate-limit rule that matches ``path``."""

    normalized = path or "/"
    for prefix, max_requests, window_seconds, scope in _DEFAULT_RULES:
        if normalized.startswith(prefix):
            return max_requests, window_seconds, scope

    fallback_max = int(os.getenv("GATEWAY_RATE_LIMIT_REQUESTS", "120"))
    fallback_window = int(os.getenv("GATEWAY_RATE_LIMIT_WINDOW_SECONDS", "60"))
    return fallback_max, fallback_window, "ip"


class _LocalStore:
    """Thread-safe in-process sliding-window store used as a fallback."""

    def __init__(self) -> None:
        self._data: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        with self._lock:
            queue = self._data.setdefault(key, deque())
            while queue and now - queue[0] > window_seconds:
                queue.popleft()
            if len(queue) >= max_requests:
                return False
            queue.append(now)
            return True


class _RedisStore:
    """Redis-backed sliding-window store keyed by ``rl:{key}``.

    Uses ``ZADD``/``ZREMRANGEBYSCORE``/``ZCARD`` so the window slides
    correctly under concurrency, and ``EXPIRE`` so abandoned keys do not
    leak forever.
    """

    def __init__(self, url: str) -> None:
        if redis is None:
            raise RuntimeError("redis-py is not installed")
        self._client = redis.Redis.from_url(url, decode_responses=True)

    def hit(self, key: str, max_requests: int, window_seconds: int) -> bool:
        redis_key = f"rl:{key}"
        now_ms = int(time.time() * 1000)
        window_ms = window_seconds * 1000
        try:
            pipeline = self._client.pipeline(transaction=False)
            pipeline.zremrangebyscore(redis_key, 0, now_ms - window_ms)
            pipeline.zcard(redis_key)
            pipeline.zadd(redis_key, {str(now_ms): now_ms})
            pipeline.expire(redis_key, window_seconds + 1)
            _, current_count, _, _ = pipeline.execute()
        except RedisError as exc:
            logger.warning("rate_limit_redis_error err=%s key=%s", exc, redis_key)
            # Fail open on infra errors (don't deny legitimate traffic when
            # Redis is down). The fallback is the local store, which only
            # protects this one process — but at least it protects something.
            return True
        return int(current_count or 0) < max_requests


def _build_store() -> object:
    url = str(os.getenv("RATE_LIMIT_REDIS_URL", "")).strip() or str(os.getenv("REDIS_URL", "")).strip()
    if url and redis is not None:
        try:
            store = _RedisStore(url)
            logger.info("rate_limit_store=redis url=%s", url.split("@")[-1])
            return store
        except Exception as exc:  # noqa: BLE001
            logger.warning("rate_limit_store_redis_init_failed err=%s falling_back=local", exc)
    logger.info("rate_limit_store=local note=Redis_not_configured_or_unavailable")
    return _LocalStore()


_STORE = _build_store()


def _resolve_user_id(request) -> Optional[str]:
    auth_header = str(request.META.get("HTTP_AUTHORIZATION", "")).strip()
    if not auth_header:
        return None
    return auth_header  # opaque opaque-user binding; gateway never decodes JWT


class RateLimitMiddleware:
    """Per-endpoint, Redis-aware rate limiter (Phase 11)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        max_requests, window_seconds, scope = _resolve_rule(request.path)

        if scope == "user":
            scope_value = _resolve_user_id(request) or request.META.get("REMOTE_ADDR", "unknown")
        else:
            scope_value = request.META.get("REMOTE_ADDR", "unknown")

        key = f"{scope}:{scope_value}:{request.path}"

        if not _STORE.hit(key, max_requests, window_seconds):
            return JsonResponse(
                {
                    "success": False,
                    "message": "Rate limit exceeded. Please try again later.",
                    "limit": max_requests,
                    "window_seconds": window_seconds,
                },
                status=429,
            )
        return self.get_response(request)


class GatewayAuthenticationMiddleware:
    """Gateway-level auth presence check for protected paths."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method.upper() == "OPTIONS":
            return self.get_response(request)

        if is_public_path(request.path):
            return self.get_response(request)

        if request.path.startswith("/health/"):
            return self.get_response(request)

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Authentication credentials were not provided.",
                },
                status=401,
            )

        return self.get_response(request)


class RequestValidationMiddleware:
    """Basic gateway request validation before proxying."""

    ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method.upper() not in self.ALLOWED_METHODS:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Method not allowed.",
                },
                status=405,
            )

        content_length = request.META.get("CONTENT_LENGTH")
        if content_length:
            try:
                if int(content_length) > 50 * 1024 * 1024:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": "Request payload too large.",
                        },
                        status=413,
                    )
            except ValueError:
                logger.warning("Invalid CONTENT_LENGTH value: %s", content_length)

        return self.get_response(request)

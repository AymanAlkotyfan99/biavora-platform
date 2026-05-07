"""
Shared HTTP client used for every cross-service call.

Features (audit GAP-05 / CRIT-10):

* Exponential-backoff retries on idempotent methods only (GET / HEAD / PUT /
  DELETE / OPTIONS), with a configurable cap.
* Per-host circuit breaker: 5 consecutive failures opens the breaker for 30
  seconds; subsequent calls fast-fail with ``CircuitBreakerOpenError`` until
  the cool-down expires.
* W3C Trace Context propagation: copies / generates ``traceparent`` and
  ``tracestate`` headers on every outbound call.
* Request-id injection (``X-Request-Id``) — generated when not supplied.
* Optional internal-API-key injection (``X-Internal-Api-Key``) so services
  do not have to repeat that boilerplate.
* Configurable connect/read timeouts (default 5 s / 30 s).
* Structured JSON-friendly logging on every attempt.

This module is intentionally dependency-light: it uses only ``requests`` and
the Python standard library.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

import requests

logger = logging.getLogger("bi_platform_shared.http")


_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS"})


class HttpClientError(RuntimeError):
    """Raised when an HTTP call fails after exhausting retries."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, url: Optional[str] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class CircuitBreakerOpenError(HttpClientError):
    """Raised when a request is short-circuited because the breaker is open."""


@dataclass
class _BreakerState:
    failures: int = 0
    opened_at: float = 0.0


class _CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 5, reset_after_seconds: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_after_seconds = reset_after_seconds
        self._states: Dict[str, _BreakerState] = {}
        self._lock = threading.Lock()

    def _state(self, host: str) -> _BreakerState:
        with self._lock:
            state = self._states.get(host)
            if state is None:
                state = _BreakerState()
                self._states[host] = state
            return state

    def is_open(self, host: str) -> bool:
        state = self._state(host)
        if state.failures < self.failure_threshold:
            return False
        if (time.time() - state.opened_at) >= self.reset_after_seconds:
            with self._lock:
                state.failures = 0
                state.opened_at = 0.0
            return False
        return True

    def record_success(self, host: str) -> None:
        with self._lock:
            state = self._states.get(host)
            if state:
                state.failures = 0
                state.opened_at = 0.0

    def record_failure(self, host: str) -> None:
        with self._lock:
            state = self._states.setdefault(host, _BreakerState())
            state.failures += 1
            if state.failures >= self.failure_threshold and state.opened_at == 0.0:
                state.opened_at = time.time()
                logger.warning(
                    "circuit_breaker_opened",
                    extra={"host": host, "failures": state.failures, "cooldown_s": self.reset_after_seconds},
                )


def _generate_traceparent() -> str:
    """Generate a W3C-compatible traceparent header value."""

    trace_id = uuid.uuid4().hex + uuid.uuid4().hex[:16]
    span_id = uuid.uuid4().hex[:16]
    return f"00-{trace_id[:32]}-{span_id}-01"


class HttpClient:
    """Configurable HTTP client used by every microservice."""

    def __init__(
        self,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 0.5,
        backoff_max_seconds: float = 5.0,
        circuit_breaker: Optional[_CircuitBreaker] = None,
        internal_api_key_env: str = "AI_SERVICE_INTERNAL_API_KEY",
        service_name: str = "bi_platform",
    ) -> None:
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_retries = max(1, int(max_retries))
        self.backoff_base = backoff_base_seconds
        self.backoff_max = backoff_max_seconds
        self.circuit_breaker = circuit_breaker or _CircuitBreaker()
        self.internal_api_key_env = internal_api_key_env
        self.service_name = service_name
        self._session = requests.Session()

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json: Any = None,
        data: Any = None,
        headers: Optional[Mapping[str, str]] = None,
        files: Any = None,
        timeout: Optional[Tuple[float, float]] = None,
        request_id: Optional[str] = None,
        traceparent: Optional[str] = None,
        tracestate: Optional[str] = None,
        attach_internal_api_key: bool = True,
        allow_redirects: bool = True,
    ) -> requests.Response:
        method_upper = method.upper()
        host = _host_of(url)

        if self.circuit_breaker.is_open(host):
            raise CircuitBreakerOpenError(
                f"Circuit breaker is open for host {host!r}",
                url=url,
            )

        merged_headers = self._build_headers(
            user_headers=headers or {},
            request_id=request_id,
            traceparent=traceparent,
            tracestate=tracestate,
            attach_internal_api_key=attach_internal_api_key,
        )

        timeout_tuple = timeout or (self.connect_timeout, self.read_timeout)
        retry_eligible = method_upper in _IDEMPOTENT_METHODS
        attempts = self.max_retries if retry_eligible else 1

        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            t_start = time.time()
            try:
                response = self._session.request(
                    method=method_upper,
                    url=url,
                    params=params,
                    json=json,
                    data=data,
                    headers=merged_headers,
                    files=files,
                    timeout=timeout_tuple,
                    allow_redirects=allow_redirects,
                )
            except requests.RequestException as exc:
                last_exc = exc
                self.circuit_breaker.record_failure(host)
                logger.warning(
                    "http_request_exception",
                    extra={
                        "service": self.service_name,
                        "method": method_upper,
                        "url": url,
                        "host": host,
                        "attempt": attempt,
                        "error": str(exc),
                        "request_id": merged_headers.get("X-Request-Id"),
                    },
                )
                if attempt >= attempts:
                    break
                self._sleep_backoff(attempt)
                continue

            duration_ms = round((time.time() - t_start) * 1000.0, 2)
            logger.info(
                "http_request",
                extra={
                    "service": self.service_name,
                    "method": method_upper,
                    "url": url,
                    "host": host,
                    "status": response.status_code,
                    "attempt": attempt,
                    "duration_ms": duration_ms,
                    "request_id": merged_headers.get("X-Request-Id"),
                },
            )

            if response.status_code >= 500 and retry_eligible and attempt < attempts:
                self.circuit_breaker.record_failure(host)
                self._sleep_backoff(attempt)
                continue

            if response.status_code >= 500:
                self.circuit_breaker.record_failure(host)
            else:
                self.circuit_breaker.record_success(host)

            return response

        if last_exc is not None:
            raise HttpClientError(f"HTTP {method_upper} {url} failed after {attempts} attempts: {last_exc}") from last_exc
        raise HttpClientError(f"HTTP {method_upper} {url} failed after {attempts} attempts")

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("DELETE", url, **kwargs)

    def _build_headers(
        self,
        *,
        user_headers: Mapping[str, str],
        request_id: Optional[str],
        traceparent: Optional[str],
        tracestate: Optional[str],
        attach_internal_api_key: bool,
    ) -> Dict[str, str]:
        headers: Dict[str, str] = {k: v for k, v in user_headers.items() if v is not None}
        headers.setdefault("X-Request-Id", request_id or str(uuid.uuid4()))
        headers.setdefault("traceparent", traceparent or _generate_traceparent())
        if tracestate:
            headers.setdefault("tracestate", tracestate)
        headers.setdefault("X-BI-Service", self.service_name)

        if attach_internal_api_key:
            api_key = os.getenv(self.internal_api_key_env, "").strip()
            if api_key and "X-Internal-Api-Key" not in headers:
                headers["X-Internal-Api-Key"] = api_key
        return headers

    def _sleep_backoff(self, attempt: int) -> None:
        delay = min(self.backoff_max, self.backoff_base * (2 ** (attempt - 1)))
        delay += random.uniform(0.0, self.backoff_base)
        time.sleep(delay)


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc or "unknown"
    except Exception:
        return "unknown"


_default_client: Optional[HttpClient] = None
_default_client_lock = threading.Lock()


def get_default_client() -> HttpClient:
    """Return a process-wide singleton HTTP client.

    Most callers should use this so retry/breaker state is shared across the
    whole service instead of being re-instantiated on every request.
    """

    global _default_client
    if _default_client is None:
        with _default_client_lock:
            if _default_client is None:
                _default_client = HttpClient(
                    service_name=os.getenv("BI_SERVICE_NAME", "bi_platform"),
                    connect_timeout=float(os.getenv("BI_HTTP_CONNECT_TIMEOUT", "5")),
                    read_timeout=float(os.getenv("BI_HTTP_READ_TIMEOUT", "30")),
                    max_retries=int(os.getenv("BI_HTTP_MAX_RETRIES", "3")),
                )
    return _default_client


__all__ = [
    "CircuitBreakerOpenError",
    "HttpClient",
    "HttpClientError",
    "get_default_client",
]

"""Shared HTTP client with retry, circuit breaker, and trace propagation."""

from bi_platform_shared.http.client import (
    CircuitBreakerOpenError,
    HttpClient,
    HttpClientError,
    get_default_client,
)

__all__ = [
    "CircuitBreakerOpenError",
    "HttpClient",
    "HttpClientError",
    "get_default_client",
]

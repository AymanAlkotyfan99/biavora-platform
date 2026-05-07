"""Tests for ``ServiceInternalTokenAuthentication`` (no Django DB required)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from rest_framework.exceptions import AuthenticationFailed

SERVICE_ROOT = Path(__file__).resolve().parents[2]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from query_api import authentication as authn  # noqa: E402


class _Request:
    def __init__(self, meta: dict) -> None:
        self.META = meta


def test_internal_token_matches_authenticates(monkeypatch):
    monkeypatch.setattr(authn, "_expected_internal_token", lambda: "expected-secret-token-32-chars-minimum-ok")
    request = _Request({"HTTP_AUTHORIZATION": "Bearer expected-secret-token-32-chars-minimum-ok"})
    user, meta = authn.ServiceInternalTokenAuthentication().authenticate(request)
    assert user.is_authenticated is True
    assert meta == {"auth": "internal_service_token"}


def test_internal_token_mismatch_without_trusted_header_falls_through(monkeypatch):
    monkeypatch.setattr(authn, "_expected_internal_token", lambda: "expected-secret-token-32-chars-minimum-ok")
    request = _Request({"HTTP_AUTHORIZATION": "Bearer wrong-token"})
    assert authn.ServiceInternalTokenAuthentication().authenticate(request) is None


def test_internal_token_unset_returns_none(monkeypatch):
    monkeypatch.setattr(authn, "_expected_internal_token", lambda: "")
    request = _Request({"HTTP_AUTHORIZATION": "Bearer any-token"})
    assert authn.ServiceInternalTokenAuthentication().authenticate(request) is None


def test_trusted_service_invalid_bearer_raises(monkeypatch):
    monkeypatch.setattr(authn, "_expected_internal_token", lambda: "expected-secret-token-32-chars-minimum-ok")
    monkeypatch.setattr(authn, "_dev_internal_auth_bypass_enabled", lambda: False)
    monkeypatch.setattr(authn, "_trusted_internal_services", lambda: frozenset({"voice-service"}))
    request = _Request(
        {
            "HTTP_AUTHORIZATION": "Bearer wrong-token",
            "HTTP_X_INTERNAL_SERVICE": "voice-service",
        }
    )
    with pytest.raises(AuthenticationFailed):
        authn.ServiceInternalTokenAuthentication().authenticate(request)


def test_trusted_service_invalid_bearer_dev_bypass_authenticates(monkeypatch):
    monkeypatch.setattr(authn, "_expected_internal_token", lambda: "expected-secret-token-32-chars-minimum-ok")
    monkeypatch.setattr(authn, "_dev_internal_auth_bypass_enabled", lambda: True)
    monkeypatch.setattr(authn, "_trusted_internal_services", lambda: frozenset({"ai-service"}))
    request = _Request(
        {
            "HTTP_AUTHORIZATION": "Bearer wrong-token",
            "HTTP_X_INTERNAL_SERVICE": "ai-service",
        }
    )
    user, meta = authn.ServiceInternalTokenAuthentication().authenticate(request)
    assert user.is_authenticated is True
    assert meta["auth"] == "dev_bypass_invalid_bearer"


def test_validate_and_execute_policy_same_authenticator(monkeypatch):
    """Both endpoints use the same class — smoke-check instantiation."""

    monkeypatch.setattr(authn, "_expected_internal_token", lambda: "expected-secret-token-32-chars-minimum-ok")
    auth = authn.ServiceInternalTokenAuthentication()
    ok = _Request(
        {
            "HTTP_AUTHORIZATION": "Bearer expected-secret-token-32-chars-minimum-ok",
            "HTTP_X_INTERNAL_SERVICE": "voice-service",
        }
    )
    user, _meta = auth.authenticate(ok)
    assert user.is_authenticated is True

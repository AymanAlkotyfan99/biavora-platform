from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")
os.environ.setdefault("DJANGO_CORS_ALLOWED_ORIGINS", "http://localhost:3000")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DJANGO_TEST_SQLITE", "1")

SERVICE_ROOT = str(Path(__file__).resolve().parents[1])
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

if "rest_framework_simplejwt" not in sys.modules:
    stub_path = os.path.abspath("c:/tmp")
    simplejwt = types.ModuleType("rest_framework_simplejwt")
    simplejwt.__file__ = __file__
    simplejwt.__path__ = [stub_path]
    sys.modules["rest_framework_simplejwt"] = simplejwt
    auth_mod = types.ModuleType("rest_framework_simplejwt.authentication")

    class JWTAuthentication:  # pragma: no cover - test settings stub
        pass

    auth_mod.JWTAuthentication = JWTAuthentication
    sys.modules["rest_framework_simplejwt.authentication"] = auth_mod
    token_blacklist = types.ModuleType("rest_framework_simplejwt.token_blacklist")
    token_blacklist.__file__ = __file__
    token_blacklist.__path__ = [stub_path]
    sys.modules["rest_framework_simplejwt.token_blacklist"] = token_blacklist

if "corsheaders" not in sys.modules:
    corsheaders = types.ModuleType("corsheaders")
    corsheaders.__file__ = __file__
    corsheaders.__path__ = [os.path.abspath("c:/tmp")]
    sys.modules["corsheaders"] = corsheaders
    middleware_mod = types.ModuleType("corsheaders.middleware")

    class CorsMiddleware:  # pragma: no cover - test settings stub
        def __init__(self, get_response=None):
            self.get_response = get_response

        def __call__(self, request):
            return self.get_response(request) if self.get_response else None

    middleware_mod.CorsMiddleware = CorsMiddleware
    sys.modules["corsheaders.middleware"] = middleware_mod

django.setup()

from voice_reports.application.orchestration_service import _ai_sql_gate  # noqa: E402


def _ai_result(confidence: float) -> dict:
    return {
        "success": True,
        "status": "success",
        "classification": {
            "type": "analytical",
            "confidence": confidence,
            "is_analytical": True,
        },
    }


def test_ai_sql_gate_accepts_borderline_confidence(monkeypatch):
    monkeypatch.setenv("VOICE_AI_MIN_CLASSIFICATION_CONFIDENCE", "0.60")
    allowed, _, message = _ai_sql_gate(_ai_result(0.5999999))
    assert allowed is True
    assert message == ""


def test_ai_sql_gate_accepts_small_rounding_gap(monkeypatch):
    monkeypatch.setenv("VOICE_AI_MIN_CLASSIFICATION_CONFIDENCE", "0.60")
    monkeypatch.setenv("VOICE_AI_CLASSIFICATION_CONFIDENCE_EPSILON", "0.005")
    allowed, _, message = _ai_sql_gate(_ai_result(0.5966))
    assert allowed is True
    assert message == ""


def test_ai_sql_gate_rejects_clear_low_confidence(monkeypatch):
    monkeypatch.setenv("VOICE_AI_MIN_CLASSIFICATION_CONFIDENCE", "0.60")
    allowed, code, message = _ai_sql_gate(_ai_result(0.58))
    assert allowed is False
    assert code
    assert "below required" in message

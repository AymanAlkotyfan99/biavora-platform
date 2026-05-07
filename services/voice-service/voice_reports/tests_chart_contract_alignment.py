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

from voice_reports.application.orchestration_service import _align_chart_contract_with_result  # noqa: E402


def test_align_chart_contract_infers_missing_y_axis_for_line_multi():
    contract = {"chart_type": "line_multi", "x_axis": "date", "y_axis": None}
    rows = [{"date": "2026-05-01", "sum_total_sales": 120.0, "sum_customers": 10}]
    columns = [{"name": "date"}, {"name": "sum_total_sales"}, {"name": "sum_customers"}]

    aligned = _align_chart_contract_with_result(contract, columns=columns, rows=rows)

    assert aligned["x_axis"] == "date"
    assert aligned["y_axis"] == ["sum_total_sales", "sum_customers"]

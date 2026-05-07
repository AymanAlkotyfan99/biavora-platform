from __future__ import annotations

import os
from typing import Any

import requests

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
    _SHARED_CLIENT_AVAILABLE = True
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]
    _SHARED_CLIENT_AVAILABLE = False


class ForecastingBridgeError(Exception):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _ai_service_base_url() -> str:
    return (
        os.getenv("AI_SERVICE_URL")
        or os.getenv("SMALL_WHISPER_URL")
        or "http://ai-service:8005"
    ).rstrip("/")


def _request_timeout_seconds() -> int:
    raw = str(os.getenv("FORECASTING_BRIDGE_TIMEOUT_SECONDS", "60")).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 60
    return max(5, value)


def _headers() -> dict[str, str]:
    api_key = str(os.getenv("AI_SERVICE_INTERNAL_API_KEY", "") or "").strip()
    return {"X-Internal-Api-Key": api_key} if api_key else {}


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_ai_service_base_url()}{path}"
    timeout_s = _request_timeout_seconds()
    try:
        if _SHARED_CLIENT_AVAILABLE:
            response = get_default_client().post(
                url,
                json=payload,
                headers=_headers(),
                timeout=(min(5.0, float(timeout_s)), float(timeout_s)),
                attach_internal_api_key=False,
            )
        else:
            response = requests.post(
                url,
                json=payload,
                headers=_headers(),
                timeout=timeout_s,
            )
    except HttpClientError as exc:  # type: ignore[misc]
        raise ForecastingBridgeError(
            "forecasting_bridge_request_failed",
            f"AI-service forecasting request failed: {exc}",
        ) from exc
    except requests.RequestException as exc:
        raise ForecastingBridgeError(
            "forecasting_bridge_request_failed",
            f"AI-service forecasting request failed: {exc}",
        ) from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise ForecastingBridgeError(
            "forecasting_bridge_invalid_json",
            "AI-service forecasting response was not valid JSON.",
            details={"status_code": response.status_code, "text": response.text[:300]},
        ) from exc

    if response.status_code >= 400:
        if isinstance(body, dict):
            error = body.get("error", {})
            if isinstance(error, dict):
                raise ForecastingBridgeError(
                    str(error.get("code") or "forecasting_bridge_upstream_error"),
                    str(error.get("message") or "Forecasting request failed in AI service."),
                    details=error.get("details") if isinstance(error.get("details"), dict) else {},
                )
            if isinstance(error, str) and error.strip():
                raise ForecastingBridgeError("forecasting_bridge_upstream_error", error.strip())
        raise ForecastingBridgeError(
            "forecasting_bridge_http_error",
            "Forecasting request failed in AI service.",
            details={"status_code": response.status_code},
        )
    return body if isinstance(body, dict) else {}


def detect_forecast_metadata(
    *,
    intent: dict[str, Any] | None,
    question_type: str | None = None,
    final_route: str | None = None,
) -> dict[str, Any]:
    payload = {
        "intent": intent if isinstance(intent, dict) else {},
        "question_type": question_type,
        "final_route": final_route,
    }
    response = _post_json("/api/llm/forecasting/detect/", payload)
    return {
        "requires_forecast": bool(response.get("requires_forecast", False)),
        "question_type": str(response.get("question_type", "")).strip(),
        "reason": str(response.get("reason", "")).strip(),
    }


def build_forecast_payload(
    *,
    columns: list[str],
    rows: list[dict[str, Any]],
    intent: dict[str, Any] | None = None,
    horizon: int | None = None,
) -> dict[str, Any]:
    payload = {
        "columns": columns if isinstance(columns, list) else [],
        "rows": rows if isinstance(rows, list) else [],
        "intent": intent if isinstance(intent, dict) else {},
        "horizon": horizon,
    }
    return _post_json("/api/llm/forecasting/dataset/", payload)

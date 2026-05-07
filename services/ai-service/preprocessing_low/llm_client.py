from __future__ import annotations

import logging
import re
from typing import Callable

import requests

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
    _SHARED_CLIENT_AVAILABLE = True
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]
    _SHARED_CLIENT_AVAILABLE = False

from preprocessing_low.error_handler import (
    PreprocessInfrastructureError,
    PreprocessModelOutputError,
    PreprocessTimeoutError,
)
from preprocessing_low.schemas import TextPreprocessConfig


_MEANINGLESS_OUTPUTS = {"__empty__", "empty", "n/a", "na", "none", "null"}


def _build_preprocess_prompt(raw_text: str) -> str:
    return (
        "You are a text cleaning assistant for a business intelligence system.\n\n"
        "Your task:\n"
        "1. Remove filler words such as: hi, hello, umm, please, kindly, can you, etc.\n"
        "2. Correct ALL spelling mistakes in the sentence.\n"
        "3. Keep the original meaning EXACTLY the same.\n"
        "4. Do NOT remove important business terms like:\n"
        "   customers, sales, orders, revenue, date, etc.\n"
        "5. Return ONLY the cleaned sentence.\n\n"
        "Examples:\n"
        "Input: 'umm Which days had the heghest number of costomers please?'\n"
        "Output: 'Which days had the highest number of customers?'\n\n"
        "Input: 'hi show averge orders per day'\n"
        "Output: 'Show average orders per day'\n\n"
        "Input: 'can you predict montly totol sales'\n"
        "Output: 'Predict monthly total sales'\n\n"
        "Now clean this sentence:\n"
        f"{raw_text}\n"
    )


def _is_meaningful_cleaned_output(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    if not normalized:
        return False

    if normalized.lower() in _MEANINGLESS_OUTPUTS:
        return False

    if not re.search(r"\w", normalized, flags=re.UNICODE):
        return False

    compact = re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)
    return len(compact) >= 2


def _extract_ollama_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error_value = payload.get("error")
            if isinstance(error_value, str) and error_value.strip():
                return error_value.strip()
    except ValueError:
        pass
    return response.text.strip()


def _call_ollama_prompt(
    prompt: str,
    config: TextPreprocessConfig,
    logger: logging.Logger,
    log_event: Callable[[logging.Logger, int, str], None] | Callable[..., None],
    *,
    purpose: str = "text_preprocessor",
) -> str:
    payload = {
        "model": config.ollama_model,
        "prompt": prompt,
        "stream": False,
    }

    log_event(
        logger,
        logging.INFO,
        "Calling Ollama text processor",
        purpose=purpose,
        model=config.ollama_model,
        endpoint=config.ollama_url,
        prompt_chars=len(prompt),
    )

    try:
        if _SHARED_CLIENT_AVAILABLE:
            response = get_default_client().post(
                config.ollama_url,
                json=payload,
                timeout=(min(5.0, float(config.request_timeout_seconds)), float(config.request_timeout_seconds)),
                attach_internal_api_key=False,
            )
        else:
            response = requests.post(
                config.ollama_url,
                json=payload,
                timeout=config.request_timeout_seconds,
            )
    except requests.Timeout as exc:
        raise PreprocessTimeoutError(
            f"Ollama request timed out after {config.request_timeout_seconds}s."
        ) from exc
    except requests.ConnectionError as exc:
        raise PreprocessInfrastructureError(f"Ollama unavailable: {exc}") from exc
    except HttpClientError as exc:  # type: ignore[misc]
        raise PreprocessInfrastructureError(f"Ollama HTTP request failed: {exc}") from exc
    except requests.RequestException as exc:
        raise PreprocessInfrastructureError(f"Ollama request failed: {exc}") from exc

    if response.status_code in {408, 504}:
        raise PreprocessTimeoutError(
            f"Ollama returned timeout HTTP {response.status_code}: {_extract_ollama_error_message(response)}"
        )

    if response.status_code >= 400:
        error_message = _extract_ollama_error_message(response)
        raise PreprocessInfrastructureError(
            f"Ollama returned HTTP {response.status_code}: {error_message}"
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise PreprocessModelOutputError("Ollama returned a non-JSON response.") from exc

    model_output = str(body.get("response", "")).strip()
    normalized_output = re.sub(r"\s+", " ", model_output).strip()
    log_event(
        logger,
        logging.INFO,
        "Ollama text processor completed",
        purpose=purpose,
        output_chars=len(normalized_output),
    )
    return normalized_output


def _call_ollama_preprocessor(
    text: str,
    config: TextPreprocessConfig,
    logger: logging.Logger,
    log_event: Callable[[logging.Logger, int, str], None] | Callable[..., None],
) -> str:
    prompt = _build_preprocess_prompt(text)
    model_output = _call_ollama_prompt(
        prompt,
        config=config,
        logger=logger,
        log_event=log_event,
        purpose="preprocessing_low_cleaning",
    )
    if not _is_meaningful_cleaned_output(model_output):
        raise PreprocessModelOutputError(
            f"Model output is empty or meaningless: {model_output!r}"
        )
    return model_output

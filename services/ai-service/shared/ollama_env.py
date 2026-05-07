"""Shared Ollama timeout defaults (OLLAMA_TIMEOUT_SECONDS)."""

from __future__ import annotations

import os


def global_ollama_read_timeout_seconds() -> float:
    """Default read timeout for Ollama HTTP calls when a feature-specific env var is unset."""

    raw = str(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")).strip() or "180"
    try:
        value = float(raw)
    except ValueError:
        return 180.0
    return max(1.0, value)


def ollama_retry_backoff_seconds() -> float:
    """Pause between preprocessing_low Ollama retries (timeouts / transient failures)."""

    raw = str(os.getenv("OLLAMA_RETRY_BACKOFF_SECONDS", "3")).strip() or "3"
    try:
        value = float(raw)
    except ValueError:
        return 3.0
    return max(0.0, value)

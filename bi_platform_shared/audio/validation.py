"""
Single source of truth for audio validation rules.

Replaces:

    services/voice-service/voice_reports/services/audio_validation.py:SUPPORTED_AUDIO_EXTENSIONS
    services/ai-service/whisper_app/transcription_task.py:_SUPPORTED_AUDIO_EXTENSIONS

The two services previously declared overlapping but slightly different sets,
which silently caused the gateway to accept files the inner service rejected.
Both services now import this constant.
"""

from __future__ import annotations

import os
from typing import FrozenSet


SUPPORTED_AUDIO_EXTENSIONS: FrozenSet[str] = frozenset({
    ".wav",
    ".mp3",
    ".mp4",
    ".m4a",
    ".ogg",
    ".flac",
    ".aac",
    ".wma",
    ".mpga",
    ".webm",
})


SUPPORTED_AUDIO_MIME_TYPES: FrozenSet[str] = frozenset({
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/vnd.wave",
    "audio/x-pn-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/mpga",
    "audio/mp4",
    "application/mp4",
    "audio/x-m4a",
    "audio/m4a",
    "audio/ogg",
    "application/ogg",
    "audio/opus",
    "audio/flac",
    "audio/x-flac",
    "audio/aac",
    "audio/x-aac",
    "audio/aacp",
    "audio/x-ms-wma",
    "audio/webm",
    "video/webm",
    "video/mp4",
    "application/octet-stream",
})


MAX_AUDIO_DURATION_SECONDS: int = 300
MAX_AUDIO_SIZE_BYTES: int = 100 * 1024 * 1024


class AudioValidationError(ValueError):
    """Raised when an audio upload fails any validation rule."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def extension_for_filename(filename: str) -> str:
    """Return the lowercase extension (including the leading dot)."""

    if not filename:
        return ""
    _, ext = os.path.splitext(filename)
    return ext.lower()


def is_supported_extension(filename: str) -> bool:
    return extension_for_filename(filename) in SUPPORTED_AUDIO_EXTENSIONS


__all__ = [
    "MAX_AUDIO_DURATION_SECONDS",
    "MAX_AUDIO_SIZE_BYTES",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "SUPPORTED_AUDIO_MIME_TYPES",
    "AudioValidationError",
    "extension_for_filename",
    "is_supported_extension",
]

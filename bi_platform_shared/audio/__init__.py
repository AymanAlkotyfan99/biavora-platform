"""Shared audio validation primitives."""

from bi_platform_shared.audio.validation import (
    MAX_AUDIO_DURATION_SECONDS,
    MAX_AUDIO_SIZE_BYTES,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_AUDIO_MIME_TYPES,
    AudioValidationError,
    extension_for_filename,
    is_supported_extension,
)

__all__ = [
    "MAX_AUDIO_DURATION_SECONDS",
    "MAX_AUDIO_SIZE_BYTES",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "SUPPORTED_AUDIO_MIME_TYPES",
    "AudioValidationError",
    "extension_for_filename",
    "is_supported_extension",
]

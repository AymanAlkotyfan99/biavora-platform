"""Audio upload validation (CRIT-11 hardening).

Validation order (per the BACKEND_FULL_AUDIT_AND_FIX_ROADMAP):

1. **File size cap** — fast reject of obviously oversized uploads. The cap is
   sourced from ``bi_platform_shared.audio.validation.MAX_AUDIO_SIZE_BYTES``
   (overridable via ``AUDIO_MAX_SIZE_BYTES`` env var) so voice-service and
   ai-service agree byte-for-byte.
2. **ClamAV virus scan FIRST** — run before any byte of the file is parsed
   for content-type, magic bytes, or duration. Streams the upload over TCP
   to the ClamAV daemon (``CLAMAV_HOST``/``CLAMAV_PORT``). When
   ``CLAMAV_REQUIRED`` is true (default in production), an unreachable
   daemon causes the upload to be rejected. In DEBUG it can be flipped off
   so local test runs do not need ClamAV.
3. **Extension + MIME type** — uses the *single* set of allowed extensions
   exported from ``bi_platform_shared.audio.validation``.
4. **Magic bytes** — the file content header must match the declared
   extension. Catches mislabelled uploads (e.g., ``.wav`` containing PE
   binary).
5. **Duration cap** — uses ``mutagen`` to read the audio container without
   transcoding. Files longer than ``MAX_AUDIO_DURATION_SECONDS`` are
   rejected so voice-service does not blow up the AI pipeline budget.

All error messages are user-safe (no stack traces, no internal paths).
"""

from __future__ import annotations

import logging
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, BinaryIO, Optional

from django.conf import settings

from bi_platform_shared.audio.validation import (
    AudioValidationError,
    MAX_AUDIO_DURATION_SECONDS as SHARED_MAX_AUDIO_DURATION_SECONDS,
    MAX_AUDIO_SIZE_BYTES as SHARED_MAX_AUDIO_SIZE_BYTES,
    SUPPORTED_AUDIO_EXTENSIONS as _SHARED_SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_AUDIO_MIME_TYPES as _SHARED_SUPPORTED_AUDIO_MIME_TYPES,
    extension_for_filename,
)
from bi_platform_shared.logging_utils import log_with_safe_extra


SUPPORTED_AUDIO_EXTENSIONS = _SHARED_SUPPORTED_AUDIO_EXTENSIONS
SUPPORTED_AUDIO_MIME_TYPES = _SHARED_SUPPORTED_AUDIO_MIME_TYPES


logger = logging.getLogger(__name__)


_USER_SAFE_ERROR_PREFIX = "audio_rejected"

_MIME_COMPATIBILITY_BY_EXTENSION: dict[str, set[str]] = {
    ".wav": {"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave", "audio/x-pn-wav"},
    ".mp3": {"audio/mpeg", "audio/mp3", "audio/mpga"},
    ".mpga": {"audio/mpeg", "audio/mp3", "audio/mpga"},
    ".mp4": {"audio/mp4", "video/mp4", "application/mp4"},
    ".m4a": {"audio/mp4", "audio/m4a", "audio/x-m4a", "video/mp4", "application/mp4"},
    ".webm": {"audio/webm", "video/webm"},
    ".ogg": {"audio/ogg", "application/ogg", "audio/opus"},
    ".flac": {"audio/flac", "audio/x-flac"},
    ".aac": {"audio/aac", "audio/x-aac", "audio/aacp", "audio/mp4"},
    ".wma": {"audio/x-ms-wma"},
}


@dataclass(frozen=True)
class AudioValidationResult:
    valid: bool
    error: str = ""
    error_code: str = ""
    extension: str = ""
    content_type: str = ""
    duration_seconds: Optional[float] = None
    size_bytes: Optional[int] = None


def _max_size_bytes() -> int:
    return int(getattr(settings, "AUDIO_MAX_SIZE_BYTES", SHARED_MAX_AUDIO_SIZE_BYTES) or SHARED_MAX_AUDIO_SIZE_BYTES)


def _max_duration_seconds() -> int:
    return int(getattr(settings, "AUDIO_MAX_DURATION_SECONDS", SHARED_MAX_AUDIO_DURATION_SECONDS) or SHARED_MAX_AUDIO_DURATION_SECONDS)


def _read_size(uploaded_file: Any) -> int:
    """Return the size of an UploadedFile-like object without exhausting it."""

    declared = getattr(uploaded_file, "size", None)
    if isinstance(declared, int) and declared >= 0:
        return declared
    if hasattr(uploaded_file, "tell") and hasattr(uploaded_file, "seek"):
        original = uploaded_file.tell()
        uploaded_file.seek(0, os.SEEK_END)
        size = uploaded_file.tell()
        uploaded_file.seek(original)
        return int(size)
    return 0


def _read_prefix(uploaded_file: BinaryIO, size: int = 64) -> bytes:
    position = uploaded_file.tell() if hasattr(uploaded_file, "tell") else None
    try:
        prefix = uploaded_file.read(size)
    finally:
        if position is not None and hasattr(uploaded_file, "seek"):
            uploaded_file.seek(position)
    return prefix or b""


def _detect_magic_extensions(prefix: bytes) -> set[str]:
    detected: set[str] = set()
    if prefix.startswith(b"RIFF") and b"WAVE" in prefix[:12]:
        detected.add(".wav")
    if prefix.startswith(b"RF64") and b"WAVE" in prefix[:16]:
        detected.add(".wav")
    if prefix.startswith(b"ID3") or prefix[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        detected.update({".mp3", ".mpga"})
    if b"ftyp" in prefix[:32]:
        detected.update({".mp4", ".m4a"})
    if prefix[:2] in {b"\xff\xf1", b"\xff\xf9"}:
        detected.add(".aac")
    if prefix.startswith(b"\x1a\x45\xdf\xa3"):
        detected.add(".webm")
    if prefix.startswith(b"OggS"):
        detected.add(".ogg")
    if prefix.startswith(b"fLaC"):
        detected.add(".flac")
    if prefix.startswith(b"\x30\x26\xb2\x75"):
        detected.add(".wma")
    return detected


def _magic_looks_supported(prefix: bytes, extension: str) -> bool:
    detected_extensions = _detect_magic_extensions(prefix)
    if not detected_extensions:
        return False
    if extension in detected_extensions:
        return True
    if extension == ".m4a" and ".mp4" in detected_extensions:
        return True
    if extension == ".mp4" and ".m4a" in detected_extensions:
        return True
    if extension == ".mpga" and ".mp3" in detected_extensions:
        return True
    if extension == ".mp3" and ".mpga" in detected_extensions:
        return True
    if extension == ".aac" and ".mp4" in detected_extensions:
        return True
    return False


def _mime_allowed_for_extension(*, extension: str, content_type: str) -> bool:
    if not content_type:
        return True
    if content_type in SUPPORTED_AUDIO_MIME_TYPES:
        if content_type == "application/octet-stream":
            return True
        allowed = _MIME_COMPATIBILITY_BY_EXTENSION.get(extension)
        if not allowed:
            return True
        if content_type in allowed:
            return True
    guessed = (mimetypes.guess_type(f"file{extension}")[0] or "").strip().lower()
    if guessed and guessed == content_type:
        return True
    return False


def _probe_audio_stream(uploaded_file: Any, extension: str) -> tuple[bool, str]:
    ffprobe_bin = shutil.which("ffprobe") or shutil.which("ffmpeg")
    ffprobe_required = bool(getattr(settings, "AUDIO_FFPROBE_REQUIRED", True))
    binary_name = os.path.basename(ffprobe_bin or "").strip().lower()
    is_ffprobe = binary_name.startswith("ffprobe")
    if not ffprobe_bin:
        message = "ffprobe/ffmpeg is missing from PATH."
        if ffprobe_required:
            logger.error("audio_ffprobe_missing")
            return False, "Audio validation infrastructure is unavailable. Please retry shortly."
        logger.warning("audio_ffprobe_missing_skipped")
        return True, message

    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)

    suffix = extension or ".bin"
    with tempfile.NamedTemporaryFile(prefix="audio_probe_", suffix=suffix, delete=False) as tmp:
        if hasattr(uploaded_file, "chunks"):
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
        else:
            tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    try:
        if is_ffprobe:
            command = [
                ffprobe_bin,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "json",
                tmp_path,
            ]
        else:
            command = [
                ffprobe_bin,
                "-v",
                "error",
                "-i",
                tmp_path,
                "-f",
                "null",
                "-",
            ]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
        if proc.returncode != 0:
            logger.info(
                "audio_ffprobe_unreadable",
                extra={
                    "returncode": proc.returncode,
                    "stderr": str(proc.stderr or "")[:400],
                    "stdout": str(proc.stdout or "")[:400],
                },
            )
            return False, "Uploaded file could not be decoded as audio."
        if is_ffprobe:
            payload = {}
            try:
                payload = json.loads(proc.stdout or "{}")
            except json.JSONDecodeError:
                logger.warning("audio_ffprobe_invalid_json")
            streams = payload.get("streams", []) if isinstance(payload, dict) else []
            has_audio_stream = any(
                isinstance(stream, dict) and str(stream.get("codec_type", "")).strip().lower() == "audio"
                for stream in streams
            )
            if not has_audio_stream:
                return False, "Uploaded file does not contain a readable audio stream."
        return True, ""
    except subprocess.TimeoutExpired:
        logger.warning("audio_ffprobe_timeout")
        return False, "Audio validation timed out. Please retry."
    except Exception as exc:  # noqa: BLE001
        logger.exception("audio_ffprobe_error")
        if ffprobe_required:
            return False, "Audio validation infrastructure is unavailable. Please retry shortly."
        return True, f"ffprobe_skipped_error: {exc}"
    finally:
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _scan_with_clamav(uploaded_file: Any) -> tuple[bool, str]:
    """Return ``(clean, message)``.

    Streams the upload over TCP to the ClamAV daemon. When the daemon is
    unreachable and ``CLAMAV_REQUIRED`` is true (default), we deliberately
    fail-closed and reject the upload; otherwise we log and let the upload
    proceed (DEBUG / dev local convenience).
    """

    try:
        import clamd  # type: ignore
    except ImportError:
        message = "virus scanner not installed"
        if getattr(settings, "CLAMAV_REQUIRED", True):
            return False, message
        logger.warning("clamd_unavailable_allowing_upload", extra={"reason": message})
        return True, message

    host = getattr(settings, "CLAMAV_HOST", "clamav")
    port = int(getattr(settings, "CLAMAV_PORT", 3310) or 3310)
    timeout = int(getattr(settings, "CLAMAV_TIMEOUT_SECONDS", 30) or 30)

    try:
        scanner = clamd.ClamdNetworkSocket(host=host, port=port, timeout=timeout)
        # ``ping`` raises if the daemon is unreachable.
        scanner.ping()
    except Exception as exc:
        message = f"virus_scanner_unreachable: {exc}"
        if getattr(settings, "CLAMAV_REQUIRED", True):
            logger.error("clamav_unreachable_blocking_upload", extra={"host": host, "port": port, "error": str(exc)})
            return False, "Virus scanning is unavailable. Please retry shortly."
        logger.warning("clamav_unreachable_allowing_upload", extra={"host": host, "port": port, "error": str(exc)})
        return True, message

    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)

    try:
        result = scanner.instream(uploaded_file)
    except Exception as exc:
        logger.exception("clamav_scan_error")
        if getattr(settings, "CLAMAV_REQUIRED", True):
            return False, "Virus scanning failed. Please retry."
        return True, f"clamav_scan_error: {exc}"
    finally:
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)

    if not isinstance(result, dict) or "stream" not in result:
        return False, "Virus scanning returned an unexpected response."
    status, signature = result["stream"]
    if str(status).upper() == "OK":
        return True, ""
    if str(status).upper() == "FOUND":
        logger.warning("clamav_signature_match", extra={"signature": signature})
        return False, "Uploaded file failed virus scanning and has been rejected."
    return False, "Uploaded file failed virus scanning and has been rejected."


def _measure_duration_seconds(uploaded_file: Any, extension: str) -> Optional[float]:
    """Best-effort duration measurement.

    ``mutagen`` understands every container we accept and only needs the
    file header (no ffmpeg shell-out). Returns ``None`` when the container
    cannot be parsed (we then skip the duration check rather than rejecting
    a structurally valid file).
    """

    try:
        from mutagen import File as MutagenFile  # type: ignore
    except ImportError:
        logger.warning("mutagen_unavailable_skipping_duration_check")
        return None

    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)

    suffix = extension or ".bin"
    with tempfile.NamedTemporaryFile(prefix="audio_validation_", suffix=suffix, delete=False) as tmp:
        if hasattr(uploaded_file, "chunks"):
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
        else:
            tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    try:
        media = MutagenFile(tmp_path)
        if media is None or not getattr(media, "info", None):
            return None
        duration = getattr(media.info, "length", None)
        return float(duration) if duration is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("mutagen_duration_failed", extra={"error": str(exc)})
        return None
    finally:
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def validate_audio_upload(uploaded_file: Any) -> AudioValidationResult:
    """Run the full hardened audio validation pipeline.

    Returns a structured :class:`AudioValidationResult`. The error messages
    are deliberately user-safe (no stack traces, no internal paths).
    """

    if uploaded_file is None:
        return AudioValidationResult(False, "No audio file provided.", error_code=f"{_USER_SAFE_ERROR_PREFIX}_missing")

    filename = os.path.basename(str(getattr(uploaded_file, "name", "") or ""))
    extension = extension_for_filename(filename)
    content_type = str(getattr(uploaded_file, "content_type", "") or "").split(";")[0].strip().lower()

    # 1. Size cap (cheap rejection).
    size_bytes = _read_size(uploaded_file)
    max_size = _max_size_bytes()
    if size_bytes <= 0:
        return AudioValidationResult(
            False,
            "Uploaded file is empty.",
            error_code=f"{_USER_SAFE_ERROR_PREFIX}_empty",
            extension=extension,
            content_type=content_type,
            size_bytes=size_bytes,
        )
    if size_bytes > max_size:
        return AudioValidationResult(
            False,
            f"Audio file is too large. Limit is {max_size // (1024 * 1024)} MB.",
            error_code=f"{_USER_SAFE_ERROR_PREFIX}_too_large",
            extension=extension,
            content_type=content_type,
            size_bytes=size_bytes,
        )

    # 2. Virus scan FIRST — before we parse a single byte for type detection.
    clean, scan_message = _scan_with_clamav(uploaded_file)
    if not clean:
        return AudioValidationResult(
            False,
            scan_message or "Uploaded file failed virus scanning.",
            error_code=f"{_USER_SAFE_ERROR_PREFIX}_virus",
            extension=extension,
            content_type=content_type,
            size_bytes=size_bytes,
        )

    # 3. Extension + MIME type checks against shared canonical sets.
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        allowed = sorted(ext for ext in SUPPORTED_AUDIO_EXTENSIONS)
        return AudioValidationResult(
            False,
            f"Unsupported audio extension '{extension or 'none'}'. Allowed: {', '.join(allowed)}.",
            error_code=f"{_USER_SAFE_ERROR_PREFIX}_extension",
            extension=extension,
            content_type=content_type,
            size_bytes=size_bytes,
        )
    if content_type and not _mime_allowed_for_extension(extension=extension, content_type=content_type):
        allowed_mimes = sorted(_MIME_COMPATIBILITY_BY_EXTENSION.get(extension, set()))
        log_with_safe_extra(
            logger,
            logging.INFO,
            "audio_validation_mime_rejected",
            extra={
                "uploaded_filename": filename,
                "extension": extension,
                "content_type": content_type,
                "allowed_mimes": allowed_mimes,
            },
        )
        return AudioValidationResult(
            False,
            (
                f"Unsupported audio MIME type '{content_type}' for '{extension}'."
                + (f" Expected one of: {', '.join(allowed_mimes)}." if allowed_mimes else "")
            ),
            error_code=f"{_USER_SAFE_ERROR_PREFIX}_mime",
            extension=extension,
            content_type=content_type,
            size_bytes=size_bytes,
        )

    # 4. Magic-byte sniff.
    prefix = _read_prefix(uploaded_file)
    if not _magic_looks_supported(prefix, extension):
        detected = sorted(_detect_magic_extensions(prefix))
        log_with_safe_extra(
            logger,
            logging.INFO,
            "audio_validation_magic_rejected",
            extra={
                "uploaded_filename": filename,
                "extension": extension,
                "content_type": content_type,
                "detected_extensions": detected,
                "prefix_hex": prefix[:16].hex(),
            },
        )
        return AudioValidationResult(
            False,
            (
                "Uploaded file content does not match the declared audio extension."
                + (f" Detected: {', '.join(detected)}." if detected else "")
            ),
            error_code=f"{_USER_SAFE_ERROR_PREFIX}_magic_bytes",
            extension=extension,
            content_type=content_type,
            size_bytes=size_bytes,
        )

    # 5. ffprobe readability check (container + stream-level validation).
    readable, probe_error = _probe_audio_stream(uploaded_file, extension)
    if not readable:
        log_with_safe_extra(
            logger,
            logging.INFO,
            "audio_validation_ffprobe_rejected",
            extra={
                "uploaded_filename": filename,
                "extension": extension,
                "content_type": content_type,
                "reason": probe_error,
            },
        )
        return AudioValidationResult(
            False,
            probe_error or "Uploaded file could not be decoded as audio.",
            error_code=f"{_USER_SAFE_ERROR_PREFIX}_ffprobe",
            extension=extension,
            content_type=content_type,
            size_bytes=size_bytes,
        )

    # 6. Duration cap (best effort).
    duration_seconds = _measure_duration_seconds(uploaded_file, extension)
    max_duration = _max_duration_seconds()
    if duration_seconds is not None and duration_seconds > max_duration:
        return AudioValidationResult(
            False,
            f"Audio duration ({int(duration_seconds)}s) exceeds the {max_duration}-second limit.",
            error_code=f"{_USER_SAFE_ERROR_PREFIX}_duration",
            extension=extension,
            content_type=content_type,
            size_bytes=size_bytes,
            duration_seconds=duration_seconds,
        )

    return AudioValidationResult(
        True,
        "",
        error_code="",
        extension=extension,
        content_type=content_type,
        size_bytes=size_bytes,
        duration_seconds=duration_seconds,
    )


__all__ = [
    "AudioValidationError",
    "AudioValidationResult",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "SUPPORTED_AUDIO_MIME_TYPES",
    "validate_audio_upload",
]

from __future__ import annotations

import sys
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
import pytest

SERVICE_ROOT = str(Path(__file__).resolve().parents[1])
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

if not settings.configured:
    settings.configure(
        DEBUG=True,
        CLAMAV_REQUIRED=False,
        AUDIO_FFPROBE_REQUIRED=False,
        AUDIO_MAX_SIZE_BYTES=100 * 1024 * 1024,
        AUDIO_MAX_DURATION_SECONDS=300,
    )

from voice_reports.services import audio_validation as validator  # noqa: E402


def _wav_header_bytes() -> bytes:
    # Minimal RIFF/WAVE header bytes; enough for magic-byte validation.
    return b"RIFF\x24\x08\x00\x00WAVEfmt " + (b"\x00" * 64)


def _mp4_header_bytes() -> bytes:
    # Typical ISO BMFF header with ftyp atom.
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + (b"\x00" * 64)


@pytest.fixture(autouse=True)
def _stub_external_checks(monkeypatch):
    monkeypatch.setattr(validator, "_scan_with_clamav", lambda uploaded_file: (True, ""))
    monkeypatch.setattr(validator, "_measure_duration_seconds", lambda uploaded_file, extension: 12.0)
    monkeypatch.setattr(validator, "_probe_audio_stream", lambda uploaded_file, extension: (True, ""))
    yield


def test_upload_valid_wav_passes():
    upload = SimpleUploadedFile("voice.wav", _wav_header_bytes(), content_type="audio/vnd.wave")
    result = validator.validate_audio_upload(upload)
    assert result.valid is True
    assert result.error_code == ""


def test_upload_valid_mp4_passes():
    upload = SimpleUploadedFile("voice.mp4", _mp4_header_bytes(), content_type="application/mp4")
    result = validator.validate_audio_upload(upload)
    assert result.valid is True
    assert result.error_code == ""


def test_upload_corrupted_file_fails_with_magic_error():
    upload = SimpleUploadedFile("broken.wav", b"not-real-audio-content", content_type="audio/wav")
    result = validator.validate_audio_upload(upload)
    assert result.valid is False
    assert result.error_code == "audio_rejected_magic_bytes"
    assert "does not match" in result.error.lower()


def test_upload_unsupported_file_fails_with_extension_error():
    upload = SimpleUploadedFile("not-audio.txt", b"hello", content_type="text/plain")
    result = validator.validate_audio_upload(upload)
    assert result.valid is False
    assert result.error_code == "audio_rejected_extension"
    assert "Unsupported audio extension" in result.error

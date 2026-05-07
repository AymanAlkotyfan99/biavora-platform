from __future__ import annotations

import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from pathlib import Path
import unittest

import django
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from bi_platform_shared.logging_utils import sanitize_log_extra

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

from django.contrib.auth.models import Group, Permission  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.db import connection  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from users.models import User  # noqa: E402
from voice_reports.services.audio_validation import AudioValidationResult  # noqa: E402
from voice_reports.models import DashboardPage, ReportPageAssignment, SQLEditHistory, VoicePipelineJob, VoiceReport  # noqa: E402
from workspace.models import Invitation, Workspace, WorkspaceMember  # noqa: E402


def _wav_header_bytes() -> bytes:
    return b"RIFF\x24\x08\x00\x00WAVEfmt " + (b"\x00" * 64)


class VoiceUploadLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._original_media_root = getattr(settings, "MEDIA_ROOT", None)
        cls._original_allowed_hosts = list(getattr(settings, "ALLOWED_HOSTS", []))
        settings.MEDIA_ROOT = str(Path(SERVICE_ROOT) / ".test-media")
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        settings.ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
        existing = set(connection.introspection.table_names())
        models = [
            ContentType,
            Permission,
            Group,
            User,
            Workspace,
            WorkspaceMember,
            Invitation,
            VoiceReport,
            DashboardPage,
            ReportPageAssignment,
            SQLEditHistory,
            VoicePipelineJob,
        ]
        with connection.schema_editor() as schema_editor:
            for model in models:
                if model._meta.db_table in existing:
                    continue
                schema_editor.create_model(model)
                existing.add(model._meta.db_table)

    @classmethod
    def tearDownClass(cls):
        settings.MEDIA_ROOT = cls._original_media_root
        settings.ALLOWED_HOSTS = cls._original_allowed_hosts
        super().tearDownClass()

    def setUp(self):
        VoicePipelineJob.objects.all().delete()
        ReportPageAssignment.objects.all().delete()
        DashboardPage.objects.all().delete()
        SQLEditHistory.objects.all().delete()
        VoiceReport.objects.all().delete()
        Invitation.objects.all().delete()
        WorkspaceMember.objects.all().delete()
        Workspace.objects.all().delete()
        self.client = APIClient()
        self.user = User.objects.create_user(
            email=f"manager-upload-{uuid4()}@example.com",
            password="pass1234",
            name="Manager",
            role="manager",
            is_verified=True,
        )
        self.workspace = Workspace.objects.create(name="Upload WS", owner=self.user)
        self.client.force_authenticate(user=self.user)

    def test_sanitize_log_extra_renames_reserved_keys(self):
        sanitized = sanitize_log_extra(
            {
                "filename": "voice.wav",
                "module": "voice_reports.views",
                "name": "voice_logger",
                "levelname": "WARNING",
            }
        )
        self.assertEqual(sanitized["uploaded_filename"], "voice.wav")
        self.assertEqual(sanitized["source_module"], "voice_reports.views")
        self.assertEqual(sanitized["logger_name"], "voice_logger")
        self.assertEqual(sanitized["log_level_name"], "WARNING")
        self.assertNotIn("filename", sanitized)
        self.assertNotIn("module", sanitized)
        self.assertNotIn("name", sanitized)

    @patch("voice_reports.views.log_with_safe_extra")
    @patch("voice_reports.views.validate_audio_upload")
    def test_upload_validation_warning_no_logging_exception(self, validate_audio_mock, safe_log_mock):
        validate_audio_mock.return_value = AudioValidationResult(
            valid=False,
            error="Unsupported audio MIME type",
            error_code="audio_rejected_mime",
            extension=".wav",
            content_type="application/octet-stream",
            size_bytes=128,
        )

        response = self.client.post(
            "/voice-reports/upload/",
            {"audio": SimpleUploadedFile("voice.wav", _wav_header_bytes(), content_type="audio/wav")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data.get("error_code"), "audio_rejected_mime")
        safe_log_mock.assert_called_once()
        call_kwargs = safe_log_mock.call_args.kwargs
        self.assertEqual(call_kwargs["extra"]["uploaded_filename"], "voice.wav")

    def test_upload_json_payload_returns_415(self):
        response = self.client.post(
            "/voice-reports/upload/",
            {"audio": "not-a-file"},
            format="json",
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.data.get("error_code"), "unsupported_media_type")

    @patch("voice_reports.views.enqueue_audio_job")
    @patch("voice_reports.views.get_workspace_client")
    @patch("voice_reports.views.get_subscription_client")
    @patch("voice_reports.views.validate_audio_upload")
    def test_upload_valid_audio_enqueues_job(
        self,
        validate_audio_mock,
        subscription_client_mock,
        workspace_client_mock,
        enqueue_audio_job_mock,
    ):
        validate_audio_mock.return_value = AudioValidationResult(
            valid=True,
            extension=".wav",
            content_type="audio/wav",
            size_bytes=128,
            duration_seconds=1.2,
        )
        subscription_client_mock.return_value.check_access.return_value = {
            "success": True,
            "allowed": True,
            "remaining_requests": 5,
        }
        workspace_client_mock.return_value.resolve.return_value = SimpleNamespace(
            workspace_id=str(self.workspace.id),
            manager_id=str(self.user.id),
            dataset_id="ds1",
            source_id="src1",
            table_name="etl.sales",
        )
        enqueue_audio_job_mock.return_value = (
            SimpleNamespace(id=321),
            SimpleNamespace(job_id=uuid4(), current_stage="QUEUED", progress=0),
        )

        response = self.client.post(
            "/voice-reports/upload/",
            {"audio": SimpleUploadedFile("voice.wav", _wav_header_bytes(), content_type="audio/wav")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.data.get("success"))
        self.assertEqual(response.data.get("status"), "queued")
        self.assertIn("job_id", response.data)
        self.assertIn("status_url", response.data)
        enqueue_audio_job_mock.assert_called_once()

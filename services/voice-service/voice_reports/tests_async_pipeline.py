from __future__ import annotations

import os
from unittest.mock import patch

import django
from django.test import TestCase, override_settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")
os.environ.setdefault("DJANGO_CORS_ALLOWED_ORIGINS", "http://localhost:3000")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")
django.setup()

from rest_framework.test import APIClient

from users.models import User
from voice_reports.application.orchestration_service import process_pipeline_job
from voice_reports.models import VoicePipelineJob, VoiceReport
from workspace.models import Workspace


@override_settings(MEDIA_ROOT="c:/tmp/voice-service-test-media")
class AsyncPipelineTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="manager@example.com",
            password="pass1234",
            name="Manager",
            role="manager",
            is_verified=True,
        )
        self.workspace = Workspace.objects.create(name="WS", owner=self.user)
        self.client.force_authenticate(user=self.user)

    @patch("voice_reports.views.get_subscription_client")
    @patch("voice_reports.views.get_workspace_client")
    def test_text_query_async_lifecycle_completed(self, workspace_client_mock, subscription_client_mock):
        subscription_client_mock.return_value.check_access.return_value = {"success": True, "allowed": True, "remaining_requests": 5}
        workspace_client_mock.return_value.resolve.return_value.workspace_id = str(self.workspace.id)
        workspace_client_mock.return_value.resolve.return_value.manager_id = str(self.user.id)
        workspace_client_mock.return_value.resolve.return_value.dataset_id = "ds1"
        workspace_client_mock.return_value.resolve.return_value.source_id = "ds1"
        workspace_client_mock.return_value.resolve.return_value.table_name = "etl.table1"

        response = self.client.post("/voice-reports/text-query/", {"text": "total sales by city"}, format="json")
        self.assertEqual(response.status_code, 202)
        self.assertIn("job_id", response.data)
        self.assertIn("status_url", response.data)

        job_id = response.data["job_id"]

        with (
            patch("voice_reports.application.orchestration_service.get_ai_client") as ai_client_mock,
            patch("voice_reports.application.orchestration_service.get_query_client") as query_client_mock,
            patch("voice_reports.application.orchestration_service.get_visualization_client") as visualization_client_mock,
            patch("voice_reports.application.orchestration_service.validate_sql_via_query_service") as validate_sql_mock,
            patch("voice_reports.application.orchestration_service.get_workspace_client") as worker_workspace_client_mock,
        ):
            worker_workspace_client_mock.return_value.resolve.return_value.workspace_id = str(self.workspace.id)
            worker_workspace_client_mock.return_value.resolve.return_value.manager_id = str(self.user.id)
            worker_workspace_client_mock.return_value.resolve.return_value.dataset_id = "ds1"
            worker_workspace_client_mock.return_value.resolve.return_value.source_id = "ds1"
            worker_workspace_client_mock.return_value.resolve.return_value.table_name = "etl.table1"
            ai_client_mock.return_value.process_text.return_value = {
                "success": True,
                "text": "total sales by city",
                "question_type": "analytical",
                "intent": {"intent": "aggregation"},
                "reviewed_sql": "SELECT city, SUM(sales) AS sum_sales FROM etl.table1 GROUP BY city",
                "chart_contract": {"chart_type": "bar", "x_axis": "city", "y_axis": ["sum_sales"], "locked": True},
                "pipeline_trace": {"overall_status": {"status": "success"}},
            }
            validate_sql_mock.return_value = (
                True,
                "validation_passed",
                "SELECT city, SUM(sales) AS sum_sales FROM etl.table1 GROUP BY city",
            )
            query_client_mock.return_value.execute.return_value = {
                "success": True,
                "columns": ["city", "sum_sales"],
                "rows": [["A", 10], ["B", 20]],
                "row_count": 2,
                "execution_time_ms": 33,
            }
            visualization_client_mock.return_value.create_visualization.return_value = {
                "success": True,
                "question_id": 101,
                "embed_url": "http://embed",
                "chart_type": "bar",
            }

            job = process_pipeline_job(job_id)

        self.assertEqual(job.status, VoicePipelineJob.STATUS_COMPLETED)
        report = VoiceReport.objects.get(id=job.report_id)
        self.assertTrue(report.final_sql)
        self.assertEqual(report.row_count, 2)
        self.assertEqual(report.metabase_question_id, 101)
        self.assertIsInstance(job.trace, dict)
        self.assertTrue(query_client_mock.return_value.execute.called)

    @patch("voice_reports.views.get_subscription_client")
    @patch("voice_reports.views.get_workspace_client")
    def test_text_query_async_lifecycle_query_failure(self, workspace_client_mock, subscription_client_mock):
        subscription_client_mock.return_value.check_access.return_value = {"success": True, "allowed": True, "remaining_requests": 5}
        workspace_client_mock.return_value.resolve.return_value.workspace_id = str(self.workspace.id)
        workspace_client_mock.return_value.resolve.return_value.manager_id = str(self.user.id)
        workspace_client_mock.return_value.resolve.return_value.dataset_id = "ds1"
        workspace_client_mock.return_value.resolve.return_value.source_id = "ds1"
        workspace_client_mock.return_value.resolve.return_value.table_name = "etl.table1"

        response = self.client.post("/voice-reports/text-query/", {"text": "total sales by city"}, format="json")
        self.assertEqual(response.status_code, 202)
        job_id = response.data["job_id"]

        with (
            patch("voice_reports.application.orchestration_service.get_ai_client") as ai_client_mock,
            patch("voice_reports.application.orchestration_service.get_query_client") as query_client_mock,
            patch("voice_reports.application.orchestration_service.get_visualization_client") as visualization_client_mock,
            patch("voice_reports.application.orchestration_service.validate_sql_via_query_service") as validate_sql_mock,
            patch("voice_reports.application.orchestration_service.get_workspace_client") as worker_workspace_client_mock,
        ):
            worker_workspace_client_mock.return_value.resolve.return_value.workspace_id = str(self.workspace.id)
            worker_workspace_client_mock.return_value.resolve.return_value.manager_id = str(self.user.id)
            worker_workspace_client_mock.return_value.resolve.return_value.dataset_id = "ds1"
            worker_workspace_client_mock.return_value.resolve.return_value.source_id = "ds1"
            worker_workspace_client_mock.return_value.resolve.return_value.table_name = "etl.table1"
            ai_client_mock.return_value.process_text.return_value = {
                "success": True,
                "text": "total sales by city",
                "question_type": "analytical",
                "intent": {"intent": "aggregation"},
                "reviewed_sql": "SELECT city, SUM(sales) AS sum_sales FROM etl.table1 GROUP BY city",
                "chart_contract": {"chart_type": "bar", "x_axis": "city", "y_axis": ["sum_sales"], "locked": True},
                "pipeline_trace": {"overall_status": {"status": "success"}},
            }
            validate_sql_mock.return_value = (
                True,
                "validation_passed",
                "SELECT city, SUM(sales) AS sum_sales FROM etl.table1 GROUP BY city",
            )
            query_client_mock.return_value.execute.return_value = {
                "success": False,
                "error": "query_execution_failed",
            }
            visualization_client_mock.return_value.create_visualization.return_value = {"success": True, "question_id": 101}

            job = process_pipeline_job(job_id)

        self.assertEqual(job.status, VoicePipelineJob.STATUS_FAILED)
        self.assertEqual(job.error_code, "query_execution_failed")

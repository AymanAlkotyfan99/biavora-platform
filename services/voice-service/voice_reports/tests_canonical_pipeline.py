from __future__ import annotations

import os
import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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

from django.contrib.auth.models import Group, Permission  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.db import connection  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402
from users.models import User  # noqa: E402
from voice_reports.application.job_service import create_pipeline_job  # noqa: E402
from voice_reports.application.orchestration_service import process_pipeline_job  # noqa: E402
from voice_reports.models import DashboardPage, ReportPageAssignment, SQLEditHistory, VoicePipelineJob, VoiceReport  # noqa: E402
from voice_reports import views as voice_views  # noqa: E402
from workspace.models import Invitation, Workspace, WorkspaceMember  # noqa: E402


class CanonicalPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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

    def setUp(self):
        VoicePipelineJob.objects.all().delete()
        ReportPageAssignment.objects.all().delete()
        DashboardPage.objects.all().delete()
        SQLEditHistory.objects.all().delete()
        VoiceReport.objects.all().delete()
        self.user = User.objects.create_user(
            email=f"manager-contract-{uuid.uuid4()}@example.com",
            password="pass1234",
            name="Manager",
            role="manager",
            is_verified=True,
        )
        self.workspace = Workspace.objects.create(name="Contract WS", owner=self.user)

    def _job(self, question: str) -> VoicePipelineJob:
        report = VoiceReport.objects.create(
            workspace=self.workspace,
            created_by=self.user,
            audio_file="text-input/test.txt",
            transcription=question,
            status=VoiceReport.STATUS_PENDING,
        )
        return create_pipeline_job(
            report=report,
            input_type=VoicePipelineJob.INPUT_TYPE_TEXT,
            original_question=question,
            payload={"authorization_header": "Bearer test"},
        )

    def _workspace_ctx(self):
        return SimpleNamespace(
            workspace_id=str(self.workspace.id),
            manager_id=str(self.user.id),
            dataset_id="ds1",
            source_id="ds1",
            table_name="sales",
        )

    def test_non_data_question_stops_before_sql_and_query_service(self):
        job = self._job("Hello, how are you?")
        with (
            patch("voice_reports.application.orchestration_service.get_workspace_client") as workspace_client,
            patch("voice_reports.application.orchestration_service.get_ai_client") as ai_client,
            patch("voice_reports.application.orchestration_service.get_query_client") as query_client,
            patch("voice_reports.application.orchestration_service.get_visualization_client") as report_client,
        ):
            workspace_client.return_value.resolve.return_value = self._workspace_ctx()
            ai_client.return_value.process_text.return_value = {
                "success": True,
                "status": "rejected",
                "text": "Hello, how are you?",
                "classification": {
                    "is_analytical": False,
                    "is_predictive": False,
                    "type": "non_data",
                    "confidence": 0.99,
                    "reasoning": "Greeting does not ask for data.",
                },
                "intent": {},
                "sql": "",
                "pipeline_trace": {"overall_status": {"status": "rejected"}},
            }

            result = process_pipeline_job(str(job.job_id))

        self.assertEqual(result.status, VoicePipelineJob.STATUS_FAILED)
        self.assertFalse(query_client.return_value.execute.called)
        self.assertFalse(report_client.return_value.create_visualization.called)
        report = VoiceReport.objects.get(id=job.report_id)
        self.assertEqual(report.generated_sql, "")

    def test_analytical_question_executes_query_and_preserves_line_multi_chart(self):
        job = self._job("Compare total sales and number of customers over time")
        with (
            patch("voice_reports.application.orchestration_service.get_workspace_client") as workspace_client,
            patch("voice_reports.application.orchestration_service.get_ai_client") as ai_client,
            patch("voice_reports.application.orchestration_service.get_query_client") as query_client,
            patch("voice_reports.application.orchestration_service.get_visualization_client") as report_client,
            patch("voice_reports.application.orchestration_service.validate_sql_via_query_service") as validate_sql_mock,
        ):
            validate_sql_mock.return_value = (True, "ok", "SELECT toDate(order_date) AS ds, SUM(total_sales) AS total_sales, COUNT(DISTINCT customer_id) AS customers FROM etl.sales GROUP BY ds ORDER BY ds")
            workspace_client.return_value.resolve.return_value = self._workspace_ctx()
            ai_client.return_value.process_text.return_value = {
                "success": True,
                "status": "success",
                "text": "Compare total sales and number of customers over time",
                "classification": {
                    "is_analytical": True,
                    "is_predictive": False,
                    "type": "analytical",
                    "confidence": 0.95,
                    "reasoning": "Analytical comparison.",
                },
                "intent": {"query_type": "analytical", "metrics": ["total_sales", "customers"], "dimensions": ["ds"]},
                "reviewed_sql": "SELECT toDate(order_date) AS ds, SUM(total_sales) AS total_sales, COUNT(DISTINCT customer_id) AS customers FROM etl.sales GROUP BY ds ORDER BY ds",
                "chart_contract": {"chart_type": "line_multi", "x_axis": "ds", "y_axis": ["total_sales", "customers"], "locked": True},
                "pipeline_trace": {"overall_status": {"status": "success"}},
            }
            query_client.return_value.execute.return_value = {
                "success": True,
                "status": "success",
                "columns": ["ds", "total_sales", "customers"],
                "rows": [{"ds": "2026-04-01", "total_sales": 100.0, "customers": 7}],
                "row_count": 1,
                "empty_result": False,
                "execution_time_ms": 12,
            }
            report_client.return_value.create_visualization.return_value = {
                "success": True,
                "status": "success",
                "question_id": 99,
                "embed_url": "http://embed",
                "requested_chart_type": "line_multi",
                "final_chart_type": "line_multi",
                "chart_type": "line_multi",
            }

            result = process_pipeline_job(str(job.job_id))

        self.assertEqual(result.status, VoicePipelineJob.STATUS_COMPLETED)
        self.assertTrue(query_client.return_value.execute.called)
        viz_kwargs = report_client.return_value.create_visualization.call_args.kwargs
        self.assertEqual(viz_kwargs["chart_payload"]["chart_type"], "line_multi")
        report = VoiceReport.objects.get(id=job.report_id)
        self.assertEqual(report.chart_type, "line_multi")

    def test_predictive_question_runs_forecasting_before_visualization(self):
        job = self._job("Forecast total sales for the next 7 days")

        def _viz_side_effect(*, report, **_kwargs):
            rows = report.query_result["rows"]
            assert any(row.get("series_type") == "actual" for row in rows)
            assert any(row.get("series_type") == "forecast" for row in rows)
            return {
                "success": True,
                "status": "success",
                "question_id": 100,
                "embed_url": "http://embed",
                "requested_chart_type": "line_multi",
                "final_chart_type": "line_multi",
                "chart_type": "line_multi",
            }

        with (
            patch("voice_reports.application.orchestration_service.get_workspace_client") as workspace_client,
            patch("voice_reports.application.orchestration_service.get_ai_client") as ai_client,
            patch("voice_reports.application.orchestration_service.get_query_client") as query_client,
            patch("voice_reports.application.orchestration_service.build_forecast_payload") as forecast_builder,
            patch("voice_reports.application.orchestration_service.get_visualization_client") as report_client,
            patch("voice_reports.application.orchestration_service.validate_sql_via_query_service") as validate_sql_mock,
        ):
            validate_sql_mock.return_value = (True, "ok", "SELECT toDate(order_date) AS ds, SUM(total_sales) AS total_sales FROM etl.sales GROUP BY ds ORDER BY ds")
            workspace_client.return_value.resolve.return_value = self._workspace_ctx()
            ai_client.return_value.process_text.return_value = {
                "success": True,
                "status": "success",
                "text": "Forecast total sales for the next 7 days",
                "classification": {
                    "is_analytical": False,
                    "is_predictive": True,
                    "type": "predictive",
                    "confidence": 0.96,
                    "reasoning": "Forecast request.",
                },
                "intent": {
                    "query_type": "predictive",
                    "forecast": {"enabled": True, "horizon": 7, "target_column": "total_sales", "date_column": "ds"},
                },
                "reviewed_sql": "SELECT toDate(order_date) AS ds, SUM(total_sales) AS total_sales FROM etl.sales GROUP BY ds ORDER BY ds",
                "chart_contract": {"chart_type": "line_multi", "x_axis": "ds", "y_axis": ["value"], "series": "series_type", "locked": True},
                "pipeline_trace": {"overall_status": {"status": "success"}},
            }
            query_client.return_value.execute.return_value = {
                "success": True,
                "status": "success",
                "columns": ["ds", "total_sales"],
                "rows": [{"ds": "2026-04-01", "total_sales": 100.0}],
                "row_count": 1,
                "empty_result": False,
                "execution_time_ms": 12,
            }
            forecast_builder.return_value = {
                "columns": ["ds", "value", "series_type"],
                "rows": [
                    {"ds": "2026-04-01", "value": 100.0, "series_type": "actual"},
                    {"ds": "2026-04-02", "value": 110.0, "series_type": "forecast"},
                ],
                "sql": "SELECT * FROM forecast_inline",
                "meta": {
                    "time_column": "ds",
                    "value_column": "total_sales",
                    "horizon": 7,
                    "forecast_available": True,
                    "forecasting_model_status": {"provider": "timesfm", "used_fallback": False},
                },
            }
            report_client.return_value.create_visualization.side_effect = _viz_side_effect

            result = process_pipeline_job(str(job.job_id))

        self.assertEqual(result.status, VoicePipelineJob.STATUS_COMPLETED)
        self.assertTrue(query_client.return_value.execute.called)
        self.assertTrue(forecast_builder.called)
        self.assertTrue(report_client.return_value.create_visualization.called)
        report = VoiceReport.objects.get(id=job.report_id)
        self.assertEqual(report.chart_config["forecasting"]["horizon"], 7)
        self.assertEqual(report.chart_config["forecasting"]["target_column"], "total_sales")

    def test_empty_result_is_degraded_and_does_not_call_visualization(self):
        job = self._job("Show total sales by city")
        with (
            patch("voice_reports.application.orchestration_service.get_workspace_client") as workspace_client,
            patch("voice_reports.application.orchestration_service.get_ai_client") as ai_client,
            patch("voice_reports.application.orchestration_service.get_query_client") as query_client,
            patch("voice_reports.application.orchestration_service.get_visualization_client") as report_client,
            patch("voice_reports.application.orchestration_service.validate_sql_via_query_service") as validate_sql_mock,
        ):
            validate_sql_mock.return_value = (True, "ok", "SELECT city, SUM(total_sales) AS total_sales FROM etl.sales GROUP BY city")
            workspace_client.return_value.resolve.return_value = self._workspace_ctx()
            ai_client.return_value.process_text.return_value = {
                "success": True,
                "status": "success",
                "text": "Show total sales by city",
                "classification": {
                    "is_analytical": True,
                    "is_predictive": False,
                    "type": "analytical",
                    "confidence": 0.95,
                    "reasoning": "Analytical aggregation.",
                },
                "intent": {"query_type": "analytical"},
                "reviewed_sql": "SELECT city, SUM(total_sales) AS total_sales FROM etl.sales GROUP BY city",
                "chart_contract": {"chart_type": "bar", "x_axis": "city", "y_axis": ["total_sales"], "locked": True},
                "pipeline_trace": {"overall_status": {"status": "success"}},
            }
            query_client.return_value.execute.return_value = {
                "success": True,
                "status": "success",
                "columns": ["city", "total_sales"],
                "rows": [],
                "row_count": 0,
                "empty_result": True,
                "execution_time_ms": 3,
            }

            result = process_pipeline_job(str(job.job_id))

        self.assertEqual(result.status, VoicePipelineJob.STATUS_COMPLETED)
        self.assertFalse(report_client.return_value.create_visualization.called)
        report = VoiceReport.objects.get(id=job.report_id)
        self.assertTrue(report.chart_config["empty_result"])
        self.assertIn("returned no rows", report.error_message)

    def test_contract_table_downgrade_is_rejected(self):
        job = self._job("Compare total sales and customers over time")
        with (
            patch("voice_reports.application.orchestration_service.get_workspace_client") as workspace_client,
            patch("voice_reports.application.orchestration_service.get_ai_client") as ai_client,
            patch("voice_reports.application.orchestration_service.get_query_client") as query_client,
            patch("voice_reports.application.orchestration_service.get_visualization_client") as report_client,
            patch("voice_reports.application.orchestration_service.validate_sql_via_query_service") as validate_sql_mock,
        ):
            validate_sql_mock.return_value = (True, "ok", "SELECT toDate(ds) AS date, SUM(total_sales) AS sum_total_sales, SUM(customers) AS sum_customers FROM etl.sales GROUP BY date ORDER BY date")
            workspace_client.return_value.resolve.return_value = self._workspace_ctx()
            ai_client.return_value.process_text.return_value = {
                "success": True,
                "status": "success",
                "text": "Compare total sales and customers over time",
                "classification": {"is_analytical": True, "type": "analytical", "confidence": 0.95},
                "intent": {"query_type": "analytical"},
                "reviewed_sql": "SELECT toDate(ds) AS date, SUM(total_sales) AS sum_total_sales, SUM(customers) AS sum_customers FROM etl.sales GROUP BY date ORDER BY date",
                "chart_contract": {"type": "line_multi", "chart_type": "line_multi", "x_axis": "date", "y_axis": ["sum_total_sales", "sum_customers"], "locked": True, "chart_lock": True, "explicit_chart_lock": True},
                "pipeline_trace": {"overall_status": {"status": "success"}},
            }
            query_client.return_value.execute.return_value = {
                "success": True,
                "status": "success",
                "columns": ["date", "sum_total_sales", "sum_customers"],
                "rows": [{"date": "2026-04-01", "sum_total_sales": 100.0, "sum_customers": 7}],
                "row_count": 1,
                "empty_result": False,
                "execution_time_ms": 9,
            }
            report_client.return_value.create_visualization.return_value = {
                "success": True,
                "status": "success",
                "render_status": "degraded",
                "chart_type": "table",
                "final_chart_type": "table",
                "contract_preserved": False,
                "question_id": None,
                "embed_url": "",
            }

            result = process_pipeline_job(str(job.job_id))

        self.assertEqual(result.status, VoicePipelineJob.STATUS_FAILED)
        report = VoiceReport.objects.get(id=job.report_id)
        self.assertNotEqual(report.chart_type, "table")

    def test_preprocessing_normalization_helpers_do_not_raise_on_change_types(self):
        low = voice_views.normalize_preprocessing_low(
            {
                "original_text": "sales by city",
                "cleaned_text": "sales by city",
                "changes": [{"type": "normalized", "before": "sales", "after": "sales"}],
            }
        )
        high = voice_views.normalize_preprocessing_high(
            {
                "corrected_query": "sales by city",
                "schema_adjustments": [{"type": "mapped_column", "description": "mapped city"}],
                "selected_table": "etl.sales",
                "selected_columns": ["city", "total_sales"],
            }
        )

        self.assertEqual(low.get("changes", [])[0].get("type"), "normalized")
        self.assertEqual(high.get("schema_adjustments", [])[0].get("type"), "mapped_column")

    def test_report_list_does_not_bulk_refresh_embed_urls(self):
        VoiceReport.objects.create(
            workspace=self.workspace,
            created_by=self.user,
            audio_file="text-input/test.txt",
            transcription="Compare total sales across months",
            status=VoiceReport.STATUS_VISUALIZATION_CREATED,
            metabase_question_id=1256,
        )
        request = APIRequestFactory().get(
            "/voice-reports/reports/",
            HTTP_AUTHORIZATION="Bearer list-token",
        )
        force_authenticate(request, user=self.user)

        with patch("voice_reports.views.get_visualization_client") as report_client:
            report_client.return_value.get_question_embed_url.return_value = "http://embed"
            response = voice_views.ReportListView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["reports"][0]["embed_url"], "")
        report_client.return_value.get_question_embed_url.assert_not_called()

    def test_report_detail_forwards_authorization_when_refreshing_embed_url(self):
        report = VoiceReport.objects.create(
            workspace=self.workspace,
            created_by=self.user,
            audio_file="text-input/test.txt",
            transcription="Compare total sales across months",
            status=VoiceReport.STATUS_VISUALIZATION_CREATED,
            metabase_question_id=1256,
        )
        request = APIRequestFactory().get(
            f"/voice-reports/{report.id}/",
            HTTP_AUTHORIZATION="Bearer detail-token",
        )
        force_authenticate(request, user=self.user)

        with patch("voice_reports.views.get_visualization_client") as report_client:
            report_client.return_value.get_question_embed_url.return_value = "http://embed"
            response = voice_views.ReportDetailView.as_view()(request, report_id=report.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["report"]["embed_url"], "http://embed")
        report_client.return_value.get_question_embed_url.assert_called_once_with(
            1256,
            authorization_header="Bearer detail-token",
        )

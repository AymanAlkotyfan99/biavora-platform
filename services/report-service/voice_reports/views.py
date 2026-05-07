"""
Voice Reports Views (read-only).

Per CRIT-01 of the BACKEND_FULL_AUDIT_AND_FIX_ROADMAP, report-service no
longer owns any orchestration. Voice ingestion, SQL generation, query
execution, and chart rendering are exclusively handled by:

    voice-service   -> orchestration of the agent pipeline
    ai-service      -> LLM stages (transcription, intent, SQL, chart contract)
    query-service   -> ClickHouse execution + SQLGuard
    visualization-service -> Metabase question/dashboard rendering

This module exposes ONLY read-only endpoints that fetch persisted reports
from the report-service database. They never trigger pipeline execution.
"""

from __future__ import annotations

import logging

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import VoiceReport

logger = logging.getLogger(__name__)


def _get_user_workspace(user):
    """Return the workspace this user is bound to (read-only side of the model)."""

    role = str(getattr(user, "role", "") or "").lower()
    if role == "manager":
        return user.owned_workspaces.first()
    membership = user.workspace_memberships.filter(status="active").first()
    return membership.workspace if membership else None


def _serialize_report_summary(report: VoiceReport) -> dict:
    return {
        "id": report.id,
        "transcription": report.transcription,
        "status": report.status,
        "created_at": report.created_at,
        "created_by": getattr(report.created_by, "email", None),
        "chart_type": report.chart_type,
        "row_count": report.row_count,
        "execution_time_ms": report.execution_time_ms,
        "sql": report.final_sql,
        "embed_url": report.embed_url if hasattr(report, "embed_url") else "",
        "metabase_question_id": report.metabase_question_id,
        "metabase_dashboard_id": report.metabase_dashboard_id,
    }


def _serialize_report_detail(report: VoiceReport) -> dict:
    payload = _serialize_report_summary(report)
    payload.update(
        {
            "intent": report.intent_json,
            "generated_sql": report.generated_sql,
            "final_sql": report.final_sql,
            "sql_validated": report.sql_validated,
            "sql_edited": report.sql_edited,
            "query_result": report.query_result,
            "preprocessing_low": report.preprocessing_low,
            "preprocessing_high": report.preprocessing_high,
            "pipeline_trace": report.pipeline_trace,
            "ai_trace": report.ai_trace,
            "error_message": report.error_message,
            "edited_by": getattr(report.edited_by, "email", None) if report.edited_by else None,
            "chart_config": report.chart_config,
        }
    )
    return payload


class ReportListView(APIView):
    """Read-only list of persisted reports for the user's workspace."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        workspace = _get_user_workspace(request.user)
        if not workspace:
            return Response(
                {"success": False, "error": "User must belong to a workspace"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reports_qs = VoiceReport.objects.filter(workspace=workspace).order_by("-created_at")

        if str(getattr(request.user, "role", "")).lower() == "manager":
            reports_qs = reports_qs.filter(created_by=request.user)

        data = [_serialize_report_summary(report) for report in reports_qs]
        logger.info(
            "report_list_loaded",
            extra={
                "user_id": request.user.id,
                "workspace_id": workspace.id,
                "count": len(data),
            },
        )
        return Response({"success": True, "reports": data, "count": len(data)})


class ReportDetailView(APIView):
    """Read-only detail of a single persisted report."""

    permission_classes = [IsAuthenticated]

    def get(self, request, report_id):
        workspace = _get_user_workspace(request.user)
        if not workspace:
            return Response(
                {"success": False, "error": "User must belong to a workspace"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            report = get_object_or_404(VoiceReport, id=report_id, workspace=workspace)
        except Http404:
            return Response(
                {"success": False, "error": "Report not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({"success": True, "report": _serialize_report_detail(report)})

    def delete(self, request, report_id):
        if str(getattr(request.user, "role", "")).lower() != "manager":
            return Response(
                {"success": False, "error": "Only managers can delete reports"},
                status=status.HTTP_403_FORBIDDEN,
            )

        workspace = _get_user_workspace(request.user)
        if not workspace:
            return Response(
                {"success": False, "error": "User must belong to a workspace"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace,
                created_by=request.user,
            )
        except Http404:
            return Response(
                {"success": False, "error": "Report not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        report.delete()
        logger.info("report_deleted", extra={"report_id": report_id, "user_id": request.user.id})
        return Response({"success": True, "message": "Report deleted successfully"})


class DashboardStatsView(APIView):
    """Aggregate counters over the user's persisted reports (read-only)."""

    permission_classes = [IsAuthenticated]

    SUCCESS_STATUSES = (
        VoiceReport.STATUS_VISUALIZATION_CREATED,
        VoiceReport.STATUS_EXECUTED,
        VoiceReport.STATUS_COMPLETED,
    )

    PROCESSING_STATUSES = (
        VoiceReport.STATUS_PENDING,
        VoiceReport.STATUS_PROCESSING,
        VoiceReport.STATUS_PENDING_EXECUTION,
        VoiceReport.STATUS_EXECUTING,
    )

    def get(self, request):
        workspace = _get_user_workspace(request.user)
        if not workspace:
            return Response(
                {"success": False, "error": "User must belong to a workspace"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reports = VoiceReport.objects.filter(workspace=workspace)
        if str(getattr(request.user, "role", "")).lower() == "manager":
            reports = reports.filter(created_by=request.user)

        total_rows = reports.aggregate(total_rows=Coalesce(Sum("row_count"), 0))["total_rows"]
        return Response(
            {
                "success": True,
                "total_reports": reports.count(),
                "completed_reports": reports.filter(status__in=self.SUCCESS_STATUSES).count(),
                "failed_reports": reports.filter(status=VoiceReport.STATUS_FAILED).count(),
                "processing_reports": reports.filter(status__in=self.PROCESSING_STATUSES).count(),
                "total_rows": int(total_rows or 0),
            }
        )


class HealthCheckView(APIView):
    """Lightweight health probe for report-service itself only.

    Cross-service health probing was removed: it caused report-service to
    masquerade as the orchestration service. Each downstream service now
    exposes its own health endpoint and is probed via the gateway.
    """

    permission_classes = []

    def get(self, request):
        return Response({"success": True, "service": "report-service", "status": "healthy"})

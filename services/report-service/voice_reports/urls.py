"""
Voice Reports URLs (read-only).

Per CRIT-01: every orchestration endpoint (upload, execute, sql edit,
dashboard creation) was moved to voice-service. Only read-only endpoints
that hit the report-service database remain here.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthCheckView.as_view(), name="voice-reports-health"),
    path("reports/", views.ReportListView.as_view(), name="report-list"),
    path("<int:report_id>/", views.ReportDetailView.as_view(), name="report-detail"),
    path("dashboard/stats/", views.DashboardStatsView.as_view(), name="dashboard-stats"),
]

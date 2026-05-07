"""
Voice Reports URLs

API endpoints for voice-driven BI system.
"""

from django.urls import path
from . import views

urlpatterns = [
    # Health check
    path('health/', views.HealthCheckView.as_view(), name='voice-reports-health'),
    
    # Voice upload and processing
    path('upload/', views.VoiceUploadView.as_view(), name='voice-upload'),
    path('text-query/', views.TextQueryView.as_view(), name='text-query'),
    
    # Query execution
    path('<int:report_id>/execute/', views.QueryExecuteView.as_view(), name='query-execute'),
    # CRIT-02 canonical async job status endpoint
    path('jobs/<uuid:job_id>/status/', views.JobStatusView.as_view(), name='job-status'),
    path('jobs/<uuid:job_id>/', views.JobStatusView.as_view(), name='job-status-legacy'),
    
    # SQL editing (Analyst only)
    path('<int:report_id>/sql/', views.SQLEditView.as_view(), name='sql-edit'),
    
    # Report management
    path('reports/', views.ReportListView.as_view(), name='report-list'),
    path('<int:report_id>/ai-trace/', views.AITraceDetailView.as_view(), name='report-ai-trace'),
    path('<int:report_id>/', views.ReportDetailView.as_view(), name='report-detail'),
    
    # Workspace dashboard (Executive view)
    path('dashboard/stats/', views.DashboardStatsView.as_view(), name='dashboard-stats'),
    path('dashboard/', views.WorkspaceDashboardView.as_view(), name='workspace-dashboard'),
]



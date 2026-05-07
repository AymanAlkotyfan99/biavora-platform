from django.urls import path

from . import views

urlpatterns = [
    path('health/', views.HealthCheckView.as_view(), name='voice-reports-health'),
    path('upload/', views.VoiceUploadView.as_view(), name='voice-upload'),
    path('text-query/', views.TextQueryView.as_view(), name='text-query'),
    path('<int:report_id>/execute/', views.QueryExecuteView.as_view(), name='query-execute'),
    path('<int:report_id>/ai-trace/', views.AITraceDetailView.as_view(), name='report-ai-trace'),
    path('jobs/<uuid:job_id>/status/', views.JobStatusView.as_view(), name='job-status'),
]


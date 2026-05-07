from django.db import models
from django.conf import settings
from django.utils import timezone
from workspace.models import Workspace
from .constants import ChartType


class VoiceReport(models.Model):
    """
    Voice-driven BI report with full audit trail.
    Links audio → transcription → SQL → visualization.
    """
    
    CHART_CHOICES = [
        (ChartType.LINE, 'Line Chart'),
        (ChartType.LINE_MULTI, 'Multi-Line Chart'),
        (ChartType.BAR, 'Bar Chart'),
        (ChartType.BAR_GROUPED, 'Grouped Bar Chart'),
        (ChartType.BAR_STACKED, 'Stacked Bar Chart'),
        (ChartType.PIE, 'Pie Chart'),
        (ChartType.AREA, 'Area Chart'),
        (ChartType.MAP, 'Map'),
        (ChartType.COMBO_LINE_BAR, 'Combo Line/Bar Chart'),
        (ChartType.CARD, 'Card'),
        (ChartType.TABLE, 'Table'),
        (ChartType.SCATTER, 'Scatter Plot'),
        (ChartType.HISTOGRAM, 'Histogram'),
        # Legacy chart values kept for backward compatibility with old rows.
        ('kpi', 'Legacy KPI'),
        ('number', 'Legacy Number/KPI'),
        ('scalar', 'Legacy Scalar'),
        ('grouped_bar', 'Legacy Grouped Bar'),
        ('stacked_bar', 'Legacy Stacked Bar'),
        ('combo', 'Legacy Combo'),
    ]

    STATUS_UPLOADED = 'uploaded'
    STATUS_TRANSCRIBING = 'transcribing'
    STATUS_TRANSCRIBED = 'transcribed'
    STATUS_GENERATING_SQL = 'generating_sql'
    STATUS_SQL_GENERATED = 'sql_generated'

    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_EXECUTED = 'executed'
    STATUS_VISUALIZATION_CREATED = 'visualization_created'
    STATUS_FAILED = 'failed'

    # Legacy execution statuses kept for backward compatibility.
    STATUS_PENDING_EXECUTION = 'pending_execution'
    STATUS_EXECUTING = 'executing'
    STATUS_COMPLETED = 'completed'

    STATUS_CHOICES = [
        (STATUS_UPLOADED, 'Audio Uploaded'),
        (STATUS_TRANSCRIBING, 'Transcribing'),
        (STATUS_TRANSCRIBED, 'Transcribed'),
        (STATUS_GENERATING_SQL, 'Generating SQL'),
        (STATUS_SQL_GENERATED, 'SQL Generated'),
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_EXECUTED, 'Executed'),
        (STATUS_VISUALIZATION_CREATED, 'Visualization Created'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_PENDING_EXECUTION, 'Legacy Pending Execution'),
        (STATUS_EXECUTING, 'Legacy Executing Query'),
        (STATUS_COMPLETED, 'Legacy Completed'),
    ]
    
    # Ownership & Workspace Isolation
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='voice_reports'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_reports'
    )
    
    # Audio
    audio_file = models.FileField(
        upload_to='workspaces/%Y/%m/%d/',
        help_text='Audio file path: /media/workspaces/{workspace_id}/audio/'
    )
    audio_duration = models.FloatField(null=True, blank=True, help_text='Duration in seconds')
    
    # Transcription
    transcription = models.TextField(blank=True, help_text='Whisper STT output')
    transcription_language = models.CharField(max_length=10, blank=True, default='en')
    
    # SQL Generation
    intent_json = models.JSONField(null=True, blank=True, help_text='Extracted intent from text')
    preprocessing_low = models.JSONField(
        null=True,
        blank=True,
        help_text='Low-level text preprocessing metadata'
    )
    preprocessing_high = models.JSONField(
        null=True,
        blank=True,
        help_text='High-level schema-aware preprocessing metadata'
    )
    pipeline_trace = models.JSONField(
        null=True,
        blank=True,
        help_text='Full analyst-grade execution trace for the AI pipeline'
    )
    ai_trace = models.JSONField(
        null=True,
        blank=True,
        help_text='Normalized AI transparency trace for analyst explainability UI'
    )
    generated_sql = models.TextField(blank=True, help_text='Generated SQL query')
    final_sql = models.TextField(blank=True, help_text='Final SQL after validation/edits')
    sql_validated = models.BooleanField(default=False)
    sql_edited = models.BooleanField(default=False, help_text='Has SQL been manually edited')
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='edited_reports',
        help_text='User who last edited the SQL'
    )
    
    # Execution
    query_result = models.JSONField(null=True, blank=True, help_text='Query execution result')
    execution_time_ms = models.IntegerField(null=True, blank=True)
    row_count = models.IntegerField(null=True, blank=True)
    
    # Visualization
    chart_type = models.CharField(max_length=20, choices=CHART_CHOICES, blank=True)
    chart_config = models.JSONField(null=True, blank=True, help_text='Chart configuration')
    
    # Metabase Integration
    metabase_question_id = models.IntegerField(null=True, blank=True)
    metabase_dashboard_id = models.IntegerField(null=True, blank=True)
    embed_url = models.TextField(blank=True, help_text='JWT-signed embed URL')
    
    # Status & Timestamps
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_UPLOADED
    )
    error_message = models.TextField(blank=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Report Metadata
    title = models.CharField(max_length=255, blank=True, help_text='Auto-generated or user-provided')
    description = models.TextField(blank=True)
    
    class Meta:
        db_table = 'voice_reports'
        verbose_name = 'Voice Report'
        verbose_name_plural = 'Voice Reports'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', 'created_by']),
            models.Index(fields=['workspace', 'status']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.title or f'Report #{self.id}'} - {self.workspace.name}"
    
    def can_edit_transcription(self, user):
        """Check if user can edit transcription."""
        return user.role in ['manager', 'analyst']
    
    def can_edit_sql(self, user):
        """Check if user can edit SQL."""
        return user.role == 'analyst'
    
    def can_delete(self, user):
        """Check if user can delete report."""
        return user.role == 'manager'


class SQLEditHistory(models.Model):
    """
    Track all SQL edits for audit purposes.
    """
    report = models.ForeignKey(
        VoiceReport,
        on_delete=models.CASCADE,
        related_name='sql_history'
    )
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    
    previous_sql = models.TextField()
    new_sql = models.TextField()
    
    validation_passed = models.BooleanField(default=False)
    validation_errors = models.JSONField(null=True, blank=True)
    
    edited_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'sql_edit_history'
        verbose_name = 'SQL Edit History'
        verbose_name_plural = 'SQL Edit Histories'
        ordering = ['-edited_at']
    
    def __str__(self):
        return f"SQL Edit for Report #{self.report.id} by {self.edited_by.email}"


class DashboardPage(models.Model):
    """
    Dashboard pages/tabs for organizing reports.
    """
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='dashboard_pages'
    )
    
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    
    # Metabase Dashboard ID
    metabase_dashboard_id = models.IntegerField(null=True, blank=True)
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'dashboard_pages'
        verbose_name = 'Dashboard Page'
        verbose_name_plural = 'Dashboard Pages'
        ordering = ['workspace', 'order']
        unique_together = [['workspace', 'name']]
    
    def __str__(self):
        return f"{self.name} - {self.workspace.name}"


class ReportPageAssignment(models.Model):
    """
    Many-to-many relationship between reports and dashboard pages.
    """
    report = models.ForeignKey(
        VoiceReport,
        on_delete=models.CASCADE,
        related_name='page_assignments'
    )
    page = models.ForeignKey(
        DashboardPage,
        on_delete=models.CASCADE,
        related_name='report_assignments'
    )
    order = models.IntegerField(default=0)
    
    added_at = models.DateTimeField(default=timezone.now)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    
    class Meta:
        db_table = 'report_page_assignments'
        verbose_name = 'Report Page Assignment'
        verbose_name_plural = 'Report Page Assignments'
        ordering = ['page', 'order']
        unique_together = [['report', 'page']]
    
    def __str__(self):
        return f"{self.report} → {self.page}"


class VoicePipelineJob(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_QUEUED = "QUEUED"
    STATUS_TRANSCRIBING = "TRANSCRIBING"
    STATUS_AI_PROCESSING = "AI_PROCESSING"
    STATUS_SQL_GENERATED = "SQL_GENERATED"
    STATUS_EXECUTING_QUERY = "EXECUTING_QUERY"
    STATUS_VISUALIZING = "VISUALIZING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"
    STATUS_PARTIAL = "PARTIAL"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_TRANSCRIBING, "Transcribing"),
        (STATUS_AI_PROCESSING, "AI Processing"),
        (STATUS_SQL_GENERATED, "SQL Generated"),
        (STATUS_EXECUTING_QUERY, "Executing Query"),
        (STATUS_VISUALIZING, "Visualizing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_PARTIAL, "Partial"),
    ]

    INPUT_TYPE_AUDIO = "audio"
    INPUT_TYPE_TEXT = "text"
    INPUT_TYPE_CHOICES = [
        (INPUT_TYPE_AUDIO, "Audio"),
        (INPUT_TYPE_TEXT, "Text"),
    ]

    job_id = models.UUIDField(unique=True, db_index=True)
    report = models.ForeignKey(VoiceReport, on_delete=models.CASCADE, related_name="jobs")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="voice_pipeline_jobs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="voice_pipeline_jobs")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    current_stage = models.CharField(max_length=64, blank=True, default=STATUS_PENDING)
    input_type = models.CharField(max_length=16, choices=INPUT_TYPE_CHOICES)
    original_question = models.TextField(blank=True)
    cleaned_question = models.TextField(blank=True)
    generated_sql = models.TextField(blank=True)
    execution_result_summary = models.JSONField(null=True, blank=True)
    visualization_id = models.CharField(max_length=128, blank=True)
    progress = models.PositiveSmallIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=128, blank=True)
    error_message = models.TextField(blank=True)
    trace = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "voice_pipeline_jobs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["user", "status"]),
            models.Index(fields=["report"]),
        ]

    def __str__(self):
        return f"{self.job_id} ({self.status})"


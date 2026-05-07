from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('voice_reports', '0006_add_ai_trace'),
        ('workspace', '0005_add_workspace_company_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='VoicePipelineJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('job_id', models.UUIDField(db_index=True, unique=True)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('TRANSCRIBING', 'Transcribing'), ('AI_PROCESSING', 'AI Processing'), ('SQL_GENERATED', 'SQL Generated'), ('EXECUTING_QUERY', 'Executing Query'), ('VISUALIZING', 'Visualizing'), ('COMPLETED', 'Completed'), ('FAILED', 'Failed'), ('PARTIAL', 'Partial')], default='PENDING', max_length=32)),
                ('current_stage', models.CharField(blank=True, default='PENDING', max_length=64)),
                ('input_type', models.CharField(choices=[('audio', 'Audio'), ('text', 'Text')], max_length=16)),
                ('original_question', models.TextField(blank=True)),
                ('cleaned_question', models.TextField(blank=True)),
                ('generated_sql', models.TextField(blank=True)),
                ('execution_result_summary', models.JSONField(blank=True, null=True)),
                ('visualization_id', models.CharField(blank=True, max_length=128)),
                ('progress', models.PositiveSmallIntegerField(default=0)),
                ('retry_count', models.PositiveIntegerField(default=0)),
                ('error_code', models.CharField(blank=True, max_length=128)),
                ('error_message', models.TextField(blank=True)),
                ('trace', models.JSONField(blank=True, null=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('report', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='jobs', to='voice_reports.voicereport')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='voice_pipeline_jobs', to=settings.AUTH_USER_MODEL)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='voice_pipeline_jobs', to='workspace.workspace')),
            ],
            options={
                'db_table': 'voice_pipeline_jobs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='voicepipelinejob',
            index=models.Index(fields=['workspace', 'status'], name='voice_pipel_workspa_621303_idx'),
        ),
        migrations.AddIndex(
            model_name='voicepipelinejob',
            index=models.Index(fields=['user', 'status'], name='voice_pipel_user_id_f6202c_idx'),
        ),
        migrations.AddIndex(
            model_name='voicepipelinejob',
            index=models.Index(fields=['report'], name='voice_pipel_report__d6dd59_idx'),
        ),
    ]

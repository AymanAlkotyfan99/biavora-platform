"""Management command to redispatch stuck voice pipeline jobs.

Originally this command ran ``process_pipeline_job`` in-process. After
CRIT-02 the pipeline is owned by a Celery worker; this command now simply
re-enqueues PENDING/QUEUED jobs onto Celery so an operator can recover
from a worker crash without losing the job rows.
"""

from django.core.management.base import BaseCommand

from voice_reports.domain import statuses
from voice_reports.models import VoicePipelineJob
from voice_reports.tasks import run_pipeline_async


class Command(BaseCommand):
    help = "Redispatch pending voice pipeline jobs to the Celery worker queue"

    def add_arguments(self, parser):
        parser.add_argument(
            "--inline",
            action="store_true",
            help="Run jobs synchronously in this process (DEBUG/recovery only).",
        )

    def handle(self, *args, **options):
        pending_jobs = VoicePipelineJob.objects.filter(
            status__in=[statuses.PENDING, statuses.QUEUED, statuses.TRANSCRIBING, statuses.AI_PROCESSING]
        )
        total = pending_jobs.count()
        self.stdout.write(self.style.SUCCESS(f"Found {total} job(s) to redispatch"))
        for job in pending_jobs.iterator():
            if options.get("inline"):
                from voice_reports.application.orchestration_service import process_pipeline_job
                process_pipeline_job(str(job.job_id))
            else:
                run_pipeline_async.delay(str(job.job_id))

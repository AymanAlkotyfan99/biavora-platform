import uuid
from typing import Any

from django.utils import timezone

from voice_reports.domain import statuses
from voice_reports.models import VoicePipelineJob, VoiceReport


def create_pipeline_job(*, report: VoiceReport, input_type: str, original_question: str = "", payload: dict[str, Any] | None = None) -> VoicePipelineJob:
    trace_payload = payload or {}
    job = VoicePipelineJob.objects.create(
        job_id=uuid.uuid4(),
        report=report,
        workspace=report.workspace,
        user=report.created_by,
        input_type=input_type,
        original_question=original_question,
        status=statuses.PENDING,
        current_stage=statuses.PENDING,
        progress=0,
        trace=trace_payload,
    )
    return job


def mark_job_stage(job: VoicePipelineJob, *, status: str, stage: str, progress: int, error_code: str = "", error_message: str = "") -> VoicePipelineJob:
    job.status = status
    job.current_stage = stage
    job.progress = max(0, min(100, int(progress)))
    if error_code:
        job.error_code = error_code
    if error_message:
        job.error_message = error_message
    if status in {statuses.COMPLETED, statuses.FAILED, statuses.PARTIAL}:
        job.completed_at = timezone.now()
    job.save()
    return job

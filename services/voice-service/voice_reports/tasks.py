"""Celery tasks for the voice pipeline.

Created for CRIT-02. Voice-service's HTTP handlers used to run
``process_pipeline_job`` synchronously in-process; that produced 30+s
request times, made retries impossible, and prevented horizontal scaling
of the pipeline worker pool. After Phase 2 of the audit:

1. ``VoiceUploadView`` / ``TextQueryView`` create the ``VoicePipelineJob``
   row and immediately return ``HTTP 202`` with the job id.
2. The orchestration helpers (``enqueue_audio_job`` / ``enqueue_text_job``)
   dispatch this task to Celery via ``run_pipeline_async.delay(job_id)``.
3. The Celery worker container declared in ``docker-compose.yml`` consumes
   the task and runs the pipeline.
4. Clients poll ``GET /voice-reports/jobs/<job_id>/status/`` for status.

``CELERY_TASK_ALWAYS_EAGER`` is enabled by tests and DEBUG environments so
the same code path is exercised without needing a running worker.
"""

from __future__ import annotations

import logging

from celery import shared_task


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="voice_reports.run_pipeline_async",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=2,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_pipeline_async(self, job_id: str):
    """Run the voice pipeline for ``job_id``.

    The orchestrator already implements its own per-job lock and idempotent
    retry handling; the Celery layer just provides distributed dispatch and
    automatic retries on transport-level failures.
    """

    from voice_reports.application.orchestration_service import process_pipeline_job

    logger.info("celery_run_pipeline_start", extra={"job_id": job_id, "task_id": self.request.id})
    try:
        return str(process_pipeline_job(job_id).job_id)
    except Exception:  # noqa: BLE001
        logger.exception("celery_run_pipeline_failed", extra={"job_id": job_id})
        raise


__all__ = ["run_pipeline_async"]

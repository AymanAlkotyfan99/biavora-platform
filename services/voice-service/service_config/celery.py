"""Celery application bootstrap for voice-service.

Created as part of CRIT-02 of the BACKEND_FULL_AUDIT_AND_FIX_ROADMAP. The
voice pipeline used to run synchronously in the request handler; that
caused 30 s+ blocking POSTs and made the gateway brittle. The pipeline now
runs on Celery workers backed by Redis.
"""

from __future__ import annotations

import os

from celery import Celery


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")

app = Celery("voice_service")

# All Celery settings live in Django settings under the ``CELERY_*`` namespace
# so the worker, beat (if added later), and flower share configuration with
# Django.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks declared in ``<app>.tasks``. Today this picks up
# ``voice_reports.tasks`` (the pipeline runner).
app.autodiscover_tasks()


@app.task(bind=True, name="voice_service.celery.healthcheck")
def healthcheck(self) -> str:  # pragma: no cover - smoke test only
    return "ok"


__all__ = ["app"]

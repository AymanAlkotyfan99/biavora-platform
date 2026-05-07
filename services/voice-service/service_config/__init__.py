"""voice-service Django project package.

Importing the Celery application here ensures it is loaded as soon as
Django itself is loaded, so the ``@shared_task`` decorator in
``voice_reports.tasks`` registers tasks against the right app. This is the
standard Celery + Django integration pattern.
"""

try:
    from .celery import app as celery_app
except ImportError:  # pragma: no cover - unit tests without Celery installed
    celery_app = None  # type: ignore[misc, assignment]

__all__ = ["celery_app"]

import logging
import threading

from celery import shared_task
from django.db import connection

from . import pipeline, services

logger = logging.getLogger(__name__)

# Thread fallback only: don't fire 25 OpenAI calls at once (rate limits); 6 at a time. Celery's own
# worker concurrency governs the normal path.
_THREAD_SLOTS = threading.BoundedSemaphore(6)


@shared_task(name='aibooster.tasks.enhance_image_job')
def enhance_image_job(job_id):
    pipeline.run(job_id)


def _run_in_thread(job_id):
    try:
        with _THREAD_SLOTS:
            pipeline.run(job_id)
    finally:
        connection.close()


def dispatch(job_id):
    """Queue a job on Celery; if the broker is unreachable (e.g. local dev with
    no Redis), run it on a background thread instead. Never blocks the request."""
    try:
        enhance_image_job.apply_async(args=[str(job_id)], retry=False)
    except Exception:
        logger.warning('Image Booster: Celery broker unavailable, running job %s in a thread', job_id)
        threading.Thread(target=_run_in_thread, args=(str(job_id),), daemon=True).start()


# ── Boost Report ───────────────────────────────────────────────────────────

@shared_task(name='aibooster.tasks.run_listing_report')
def run_listing_report(report_id):
    services.run(report_id)


def _run_report_in_thread(report_id):
    try:
        services.run(report_id)
    finally:
        connection.close()


def dispatch_report(report_id):
    """Same contract as dispatch(): Celery if the broker is up, else a background thread."""
    try:
        run_listing_report.apply_async(args=[str(report_id)], retry=False)
    except Exception:
        logger.warning('Boost Report: Celery broker unavailable, running report %s in a thread', report_id)
        threading.Thread(target=_run_report_in_thread, args=(str(report_id),), daemon=True).start()

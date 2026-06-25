"""Celery tasks for the accounts app."""
import logging

from celery import shared_task

from accounts import currency

logger = logging.getLogger(__name__)


@shared_task(name='accounts.tasks.refresh_exchange_rates_task')
def refresh_exchange_rates_task():
    """Daily refresh of FX rates (USD base). Scheduled in CELERY_BEAT_SCHEDULE."""
    ok = currency.refresh_rates(force=True)
    logger.info("refresh_exchange_rates_task: success=%s", ok)
    return {'success': ok}

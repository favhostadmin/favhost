"""Fetch the latest FX rates (USD base) and cache them in a JSON file on disk.

Run on a schedule (Celery beat / cron) and on demand:
    python manage.py refresh_exchange_rates
    python manage.py refresh_exchange_rates --force
"""
from django.core.management.base import BaseCommand

from accounts import currency


class Command(BaseCommand):
    help = "Fetch latest exchange rates (USD base) and cache them."

    def add_arguments(self, parser):
        parser.add_argument(
            '--force', action='store_true',
            help='Refresh even if the cached rates are still fresh.',
        )

    def handle(self, *args, **options):
        ok = currency.refresh_rates(force=options.get('force', False))
        rates = currency.get_rates()
        sample = {k: rates.get(k) for k in ('USD', 'EUR', 'GBP', 'INR', 'JPY') if k in rates}
        if ok:
            self.stdout.write(self.style.SUCCESS(
                f"Exchange rates updated: {len(rates)} currencies. Sample (1 USD =): {sample}"
            ))
        else:
            self.stderr.write(self.style.WARNING(
                "Live fetch failed; last-known/static rates remain in effect. "
                f"Sample (1 USD =): {sample}"
            ))

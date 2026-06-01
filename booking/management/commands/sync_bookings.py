from django.core.management.base import BaseCommand
from booking.utils import sync_property_channel
from property.models import PropertyChannel
from kombu.exceptions import OperationalError

class Command(BaseCommand):
    help = "Trigger sync bookings from external channels via Celery"

    def add_arguments(self, parser):
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Run synchronization synchronously (without Celery) for debugging',
        )

    def handle(self, *args, **options):
        channels = PropertyChannel.objects.filter(is_connected=True)
        self.stdout.write(f"Found {channels.count()} channels to sync.")
        
        for channel in channels:
            if options['sync']:
                self.stdout.write(f"Syncing {channel} synchronously...")
                try:
                    sync_property_channel.apply(args=[channel.id], throw=True)
                    self.stdout.write(self.style.SUCCESS(f"Successfully synced {channel}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error syncing {channel}: {e}"))
                continue

            try:
                sync_property_channel.delay(channel.id)
                self.stdout.write(self.style.SUCCESS(
                    f"Triggered sync task for {channel}"
                ))
            except OperationalError as e:
                self.stdout.write(self.style.WARNING(
                    f"Broker connection refused ({e}). Syncing {channel} synchronously..."
                ))
                try:
                    sync_property_channel.apply(args=[channel.id], throw=True)
                    self.stdout.write(self.style.SUCCESS(f"Successfully synced {channel} (Synchronous)"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error syncing {channel}: {e}"))

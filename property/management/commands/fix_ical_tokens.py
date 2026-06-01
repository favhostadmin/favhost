import uuid
from django.core.management.base import BaseCommand
from property.models import Property

class Command(BaseCommand):
    help = 'Assigns a unique iCal token to every property that does not have one.'

    def handle(self, *args, **options):
        properties_to_update = Property.objects.all()
        updated_count = 0

        self.stdout.write(self.style.NOTICE(f'Found {properties_to_update.count()} properties to check...'))

        for prop in properties_to_update:
            prop.ical_token = uuid.uuid4()
            prop.save(update_fields=['ical_token'])
            updated_count += 1

        if updated_count > 0:
            self.stdout.write(self.style.SUCCESS(f'Successfully assigned new unique tokens to {updated_count} properties.'))
        else:
            self.stdout.write(self.style.SUCCESS('All properties already had unique tokens. No changes needed.'))
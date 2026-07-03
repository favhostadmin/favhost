from django.apps import AppConfig
from django.template import defaultfilters


class BookingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'booking'

    def ready(self):
        # Backfill Django's removed length_is filter for Jazzmin templates.
        if 'length_is' not in defaultfilters.register.filters:
            def length_is(value, arg):
                try:
                    return len(value) == int(arg)
                except (TypeError, ValueError):
                    return False

            defaultfilters.register.filters['length_is'] = length_is

        # Import utils to register Celery tasks when the app starts
        import booking.utils
        import booking.signals

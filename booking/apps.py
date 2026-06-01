from django.apps import AppConfig


class BookingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'booking'

    def ready(self):
        # Import utils to register Celery tasks when the app starts
        import booking.utils
        import booking.signals

"""Ensure the single platform-owner account exists for the /console/ panel.

Idempotent: run it as many times as you like. It creates the account defined by
``settings.PLATFORM_ADMIN_EMAIL`` (default bookaid@gmail.com) with the default
password if it's missing, and makes sure it is active + staff/admin flagged.

    python manage.py create_platform_admin
    python manage.py create_platform_admin --reset-password   # force the password

No new DB tables are involved, so this respects the team's "migrate only,
never makemigrations" rule.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create/repair the predefined platform-owner console account."

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset-password', action='store_true',
            help='Reset the password to PLATFORM_ADMIN_DEFAULT_PASSWORD even if the account exists.',
        )

    def handle(self, *args, **options):
        User = get_user_model()
        email = (getattr(settings, 'PLATFORM_ADMIN_EMAIL', '') or '').strip()
        password = getattr(settings, 'PLATFORM_ADMIN_DEFAULT_PASSWORD', 'bookaid123')
        if not email:
            self.stderr.write(self.style.ERROR('PLATFORM_ADMIN_EMAIL is not set.'))
            return

        # Match on username OR email. An account created earlier (e.g. through
        # normal signup or createsuperuser) can hold the owner address in only
        # one of the two columns; looking at email alone would miss it and then
        # crash on the username unique constraint.
        user = (
            User.objects.filter(email__iexact=email).first()
            or User.objects.filter(username__iexact=email).first()
        )
        created = False
        if user is None:
            user = User.objects.create_user(username=email, email=email, password=password)
            created = True

        # ``is_console_owner`` identifies the owner by the *email* column, so a
        # row found by username alone must have its email filled in or it would
        # be refused at the console login even though the account exists.
        if (user.email or '').strip().lower() != email.lower():
            clash = User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists()
            if clash:
                self.stderr.write(self.style.ERROR(
                    f'Cannot set email {email} on account "{user.username}" — another '
                    f'account already uses that address. Resolve the duplicate first.'))
                return
            user.email = email

        # Make sure it can actually get in.
        user.is_active = True
        if hasattr(user, 'is_staff'):
            user.is_staff = True
        if hasattr(user, 'is_admin'):
            user.is_admin = True
        if options.get('reset_password') or created:
            user.set_password(password)
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(
                f'Created platform-owner account {email} (password: {password}).'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Platform-owner account {email} verified/updated.'
                + (' Password reset.' if options.get('reset_password') else '')))
        self.stdout.write('Console login: /console/login/')

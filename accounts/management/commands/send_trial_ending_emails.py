"""
Send the one-time "your free trial ends in 7 days" email to trial users.

The trial is 90 days from signup (see billing/context_processors.py). This command
finds users whose trial ends within the next N days (default 7), who are still on
trial (not subscribed, not admin-comped), and who have not already been emailed —
then sends each one the reminder exactly once.

Run it once a day (cron / Task Scheduler / Celery beat). Examples
--------
# Normal daily run:
    python manage.py send_trial_ending_emails

# See who would be emailed without sending anything:
    python manage.py send_trial_ending_emails --dry-run

# Use a different lead time (e.g. 3 days before):
    python manage.py send_trial_ending_emails --days 3
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from accounts.models import MyUser, CoHost
from accounts.emails import send_trial_ending_email

TRIAL_DAYS = 90


def _is_premium(user):
    """Mirror billing/context_processors: comped or has an active Stripe subscription."""
    if user.is_subscription_free:
        return True
    try:
        return user.stripe_customer.subscription_status == 'active'
    except Exception:
        return False


def _price_display():
    """Price shown in the email — the admin-set platform price."""
    try:
        from billing.models import PlatformSetting
        return PlatformSetting.load().full_display
    except Exception:
        return getattr(settings, 'PREMIUM_PRICE_DISPLAY', '$9.99/month')


class Command(BaseCommand):
    help = "Send the one-time 'trial ends in N days' email to eligible trial users."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7,
                            help='Lead time in days before trial end (default: 7).')
        parser.add_argument('--dry-run', action='store_true',
                            help='List who would be emailed without sending or marking them.')

    def handle(self, *args, **opts):
        lead = opts['days']
        dry = opts['dry_run']
        now = timezone.now()

        # Each account now stores its own trial length (MyUser.trial_days), so we
        # can't use a single created_at window. Instead, scan users who haven't
        # been emailed yet and compute each one's trial_end individually. A user
        # is eligible when their trial ends within the next `lead` days and has
        # not already passed — this also covers short trials (e.g. 3 days), which
        # fall inside the 7-day lead window immediately.
        cohost_ids = CoHost.objects.values_list('co_host_id', flat=True)
        candidates = (MyUser.objects
                      .filter(trial_ending_email_sent=False,
                              is_subscription_free=False,
                              is_active=True)
                      .exclude(id__in=cohost_ids))

        price_display = _price_display()
        sent = 0
        skipped = 0

        for user in candidates:
            if not user.email:
                skipped += 1
                continue
            # Skip anyone who has already subscribed (active) — they're not trial users.
            if _is_premium(user):
                skipped += 1
                continue

            trial_days = user.trial_days or TRIAL_DAYS
            trial_end = user.created_at + timedelta(days=trial_days)
            days_left = (trial_end.date() - now.date()).days

            # Only email inside the lead window (not before, not after expiry).
            if days_left < 0 or days_left > lead:
                skipped += 1
                continue

            days_left_display = max(1, days_left)

            if dry:
                self.stdout.write(
                    f"[dry-run] would email {user.email} — trial ends {trial_end.date()} ({days_left_display} days)"
                )
                sent += 1
                continue

            send_trial_ending_email(user, trial_end, days_left_display, price_display)
            user.trial_ending_email_sent = True
            user.save(update_fields=['trial_ending_email_sent'])
            sent += 1
            self.stdout.write(f"Emailed {user.email} — trial ends {trial_end.date()} ({days_left_display} days)")

        verb = 'Would send' if dry else 'Sent'
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {sent} trial-ending email(s); skipped {skipped} (subscribed/no-email/outside window)."
        ))

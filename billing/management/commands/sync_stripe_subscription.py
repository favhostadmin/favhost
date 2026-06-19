"""
Backfill a user's subscription into the local DB straight from Stripe.

Use this when a payment exists in Stripe but the local database never got the
webhook (e.g. when testing on localhost, where Stripe can't reach your machine).

Examples
--------
# 1) See what's in your Stripe account (find the customer / subscription IDs):
    python manage.py sync_stripe_subscription --list

# 2) Backfill by Stripe customer id (most reliable):
    python manage.py sync_stripe_subscription --user you@example.com --customer cus_XXXX

# 3) Backfill by the email used on the Stripe checkout:
    python manage.py sync_stripe_subscription --user you@example.com --stripe-email payer@example.com
"""
import datetime

import stripe
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import MyUser
from billing.models import StripeCustomer


class Command(BaseCommand):
    help = "Backfill a user's subscription from Stripe into the local database."

    def add_arguments(self, parser):
        parser.add_argument('--user', help='Email of the LOCAL user who should own the subscription.')
        parser.add_argument('--customer', help='Stripe customer id (cus_...).')
        parser.add_argument('--stripe-email', help='Email used on the Stripe checkout (defaults to --user).')
        parser.add_argument('--list', action='store_true', help='List recent Stripe subscriptions and exit.')

    def handle(self, *args, **opts):
        if not settings.STRIPE_SECRET_KEY:
            raise CommandError("STRIPE_SECRET_KEY is not set in your environment / .env")
        stripe.api_key = settings.STRIPE_SECRET_KEY

        # ── List mode: just print what's in Stripe so you can find the IDs ──
        if opts['list']:
            self.stdout.write("Recent subscriptions in this Stripe account:\n")
            for sub in stripe.Subscription.list(limit=20, expand=['data.customer']).auto_paging_iter():
                cust = sub.customer
                email = getattr(cust, 'email', '') if not isinstance(cust, str) else ''
                cust_id = cust.id if not isinstance(cust, str) else cust
                self.stdout.write(f"  sub={sub.id}  customer={cust_id}  email={email}  status={sub.status}")
            return

        # ── Resolve the local user ──
        user_email = opts['user']
        if not user_email:
            raise CommandError("Provide --user <local user email>, or use --list to inspect Stripe.")
        user = MyUser.objects.filter(email__iexact=user_email).first()
        if not user:
            raise CommandError(f"No local user found with email {user_email}")

        # ── Resolve the Stripe customer ──
        customer_id = opts['customer']
        if not customer_id:
            search_email = opts['stripe_email'] or user_email
            customers = stripe.Customer.list(email=search_email, limit=10).data
            if not customers:
                raise CommandError(
                    f"No Stripe customer found for email {search_email}. "
                    f"Run with --list to find the right customer id, then pass --customer cus_..."
                )
            if len(customers) > 1:
                ids = ", ".join(c.id for c in customers)
                raise CommandError(f"Multiple Stripe customers for {search_email}: {ids}. Pass --customer to choose.")
            customer_id = customers[0].id

        # ── Find the most recent subscription for that customer ──
        subs = stripe.Subscription.list(customer=customer_id, status='all', limit=10).data
        if not subs:
            raise CommandError(f"No subscriptions found for customer {customer_id}")
        # Prefer an active one, else the newest.
        subscription = next((s for s in subs if s.status in ('active', 'trialing', 'past_due')), subs[0])

        # ── Pull the period end (handles Stripe flexible-billing layout) ──
        period_end = None
        period_end_ts = getattr(subscription, 'current_period_end', None)
        if not period_end_ts and getattr(subscription, 'items', None) and subscription.items.data:
            period_end_ts = getattr(subscription.items.data[0], 'current_period_end', None)
        if period_end_ts:
            period_end = datetime.datetime.fromtimestamp(period_end_ts, tz=datetime.timezone.utc)

        # ── Write into the local DB (same fields the webhook would set) ──
        sc, _ = StripeCustomer.objects.get_or_create(user=user)
        sc.stripe_customer_id = customer_id
        sc.stripe_subscription_id = subscription.id
        sc.subscription_status = subscription.status
        sc.cancel_at_period_end = bool(getattr(subscription, 'cancel_at_period_end', False))
        if period_end:
            sc.current_period_end = period_end
        sc.save()

        self.stdout.write(self.style.SUCCESS(
            f"Synced {user.email}: customer={customer_id} subscription={subscription.id} "
            f"status={subscription.status}"
        ))

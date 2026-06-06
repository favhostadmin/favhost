import stripe
import datetime
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import StripeCustomer

logger = logging.getLogger(__name__)

# Set the Stripe API key once at module load
stripe.api_key = settings.STRIPE_SECRET_KEY


# ─────────────────────────────────────────────────────────────
# PRICING PAGE
# ─────────────────────────────────────────────────────────────
@login_required
def pricing_page(request):
    """
    The upgrade/pricing page shown when user clicks 'Upgrade' on profile.
    Shows plan details and a Subscribe button that posts to Stripe Checkout.
    """
    # Check if user already has an active subscription
    try:
        stripe_customer = request.user.stripe_customer
        is_subscribed = stripe_customer.is_active
        subscription_status = stripe_customer.subscription_status
        period_end = stripe_customer.current_period_end
    except StripeCustomer.DoesNotExist:
        is_subscribed = False
        subscription_status = ''
        period_end = None

    context = {
        'is_subscribed': is_subscribed,
        'subscription_status': subscription_status,
        'period_end': period_end,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
    }
    return render(request, 'billing/pricing.html', context)


# ─────────────────────────────────────────────────────────────
# CREATE CHECKOUT SESSION → redirect to Stripe
# ─────────────────────────────────────────────────────────────
@login_required
@require_POST
def create_checkout_session(request):
    """
    Creates a Stripe Checkout Session and redirects the user to Stripe's
    hosted payment page. Card details are entered THERE, not here.
    """
    success_url = (
        request.build_absolute_uri(reverse('billing:checkout_success'))
        + '?session_id={CHECKOUT_SESSION_ID}'
    )
    cancel_url = request.build_absolute_uri(reverse('billing:checkout_cancel'))

    try:
        # Check if this user already has a Stripe customer ID
        customer_id = None
        try:
            sc = request.user.stripe_customer
            if sc.stripe_customer_id:
                customer_id = sc.stripe_customer_id
        except StripeCustomer.DoesNotExist:
            pass

        session_params = {
            'mode': 'subscription',
            'line_items': [{'price': settings.STRIPE_PRICE_ID, 'quantity': 1}],
            'client_reference_id': str(request.user.id),
            'success_url': success_url,
            'cancel_url': cancel_url,
        }

        # If user already has a Stripe customer, attach to that customer
        # Otherwise pass their email so Stripe pre-fills it
        if customer_id:
            session_params['customer'] = customer_id
        else:
            session_params['customer_email'] = request.user.email or ''

        session = stripe.checkout.Session.create(**session_params)

        # 303 prevents browser from re-posting on back navigation
        return redirect(session.url, code=303)

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating checkout: {e}")
        return render(request, 'billing/error.html', {'error': str(e)})


# ─────────────────────────────────────────────────────────────
# SUCCESS PAGE (after Stripe redirects back)
# ─────────────────────────────────────────────────────────────
@login_required
def checkout_success(request):
    """
    Stripe redirects here after a successful payment.
    NOTE: This page is NOT proof of payment — the webhook is.
    The webhook updates the database. This page just shows a message.
    """
    return render(request, 'billing/success.html')


# ─────────────────────────────────────────────────────────────
# CANCEL PAGE (user cancelled on Stripe's page)
# ─────────────────────────────────────────────────────────────
@login_required
def checkout_cancel(request):
    """User clicked 'Back' on Stripe's Checkout page. No charge made."""
    return render(request, 'billing/cancel.html')


# ─────────────────────────────────────────────────────────────
# CUSTOMER PORTAL (manage/cancel subscription)
# ─────────────────────────────────────────────────────────────
@login_required
@require_POST
def customer_portal(request):
    """
    Sends the user to Stripe's hosted Customer Portal where they can:
    - Update their card
    - Cancel their subscription
    - View billing history
    No card UI needed in your app — Stripe hosts it all.
    """
    try:
        sc = request.user.stripe_customer
        if not sc.stripe_customer_id:
            return redirect('billing:pricing')

        portal_session = stripe.billing_portal.Session.create(
            customer=sc.stripe_customer_id,
            return_url=request.build_absolute_uri(reverse('billing:pricing')),
        )
        return redirect(portal_session.url, code=303)

    except StripeCustomer.DoesNotExist:
        return redirect('billing:pricing')
    except stripe.error.StripeError as e:
        logger.error(f"Stripe portal error: {e}")
        return render(request, 'billing/error.html', {'error': str(e)})


# ─────────────────────────────────────────────────────────────
# STRIPE WEBHOOK (receives events from Stripe)
# ─────────────────────────────────────────────────────────────
@csrf_exempt
def stripe_webhook(request):
    """
    Stripe POSTs events here when things happen:
    - checkout.session.completed → first payment done → activate
    - invoice.paid              → monthly renewal succeeded → keep active
    - invoice.payment_failed    → renewal failed → mark past_due
    - customer.subscription.deleted → cancelled → mark canceled

    MUST be @csrf_exempt because the request comes from Stripe, not a browser.
    MUST verify the Stripe signature before trusting the payload.
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.warning("Stripe webhook: invalid payload")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        logger.warning("Stripe webhook: signature verification failed")
        return HttpResponse(status=400)

    # stripe-python 15.x uses typed objects — use attribute access, not dict access
    event_type = event.type
    obj = event.data.object

    logger.info(f"Stripe webhook received: {event_type}")

    try:
        if event_type == 'checkout.session.completed':
            _handle_checkout_completed(obj)
        elif event_type == 'invoice.paid':
            _handle_invoice_paid(obj)
        elif event_type == 'invoice.payment_failed':
            _handle_payment_failed(obj)
        elif event_type == 'customer.subscription.deleted':
            _handle_subscription_deleted(obj)
        elif event_type == 'customer.subscription.updated':
            _handle_subscription_updated(obj)
    except Exception as e:
        logger.error(f"Webhook handler error for {event_type}: {e}", exc_info=True)

    # Always return 200 — Stripe retries on any non-2xx response
    return HttpResponse(status=200)


# ─────────────────────────────────────────────────────────────
# WEBHOOK HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────

def _handle_checkout_completed(session):
    """First payment succeeded. Save customer + subscription IDs, mark active."""
    user_id = getattr(session, 'client_reference_id', None)
    customer_id = getattr(session, 'customer', None)
    subscription_id = getattr(session, 'subscription', None)

    if not user_id:
        logger.error("checkout.session.completed: missing client_reference_id")
        return

    from accounts.models import MyUser
    try:
        user = MyUser.objects.get(id=user_id)
    except MyUser.DoesNotExist:
        logger.error(f"checkout.session.completed: user {user_id} not found")
        return

    sc, created = StripeCustomer.objects.get_or_create(user=user)
    if customer_id:
        sc.stripe_customer_id = customer_id
    if subscription_id:
        sc.stripe_subscription_id = subscription_id
    sc.subscription_status = 'active'

    # Fetch current_period_end from Stripe subscription so it's available immediately
    if subscription_id:
        try:
            sub = stripe.Subscription.retrieve(subscription_id)
            period_end_ts = getattr(sub, 'current_period_end', None)
            if period_end_ts:
                sc.current_period_end = datetime.datetime.fromtimestamp(
                    period_end_ts, tz=datetime.timezone.utc
                )
        except Exception as e:
            logger.warning(f"Could not fetch subscription period_end: {e}")

    sc.save()
    logger.info(f"User {user.username} subscription activated")


def _handle_invoice_paid(invoice):
    """Monthly renewal succeeded. Keep active, update period end."""
    customer_id = getattr(invoice, 'customer', None)
    sc = StripeCustomer.objects.filter(stripe_customer_id=customer_id).first()
    if not sc:
        return
    sc.subscription_status = 'active'
    _update_period_end(sc, invoice)
    sc.save()
    logger.info(f"Invoice paid for customer {customer_id}")


def _handle_payment_failed(invoice):
    """Monthly renewal failed. Mark past_due — prompt user to update card."""
    customer_id = getattr(invoice, 'customer', None)
    sc = StripeCustomer.objects.filter(stripe_customer_id=customer_id).first()
    if not sc:
        return
    sc.subscription_status = 'past_due'
    sc.save()
    logger.info(f"Payment failed for customer {customer_id}")


def _handle_subscription_deleted(subscription):
    """Subscription was cancelled. Mark as canceled."""
    customer_id = getattr(subscription, 'customer', None)
    sc = StripeCustomer.objects.filter(stripe_customer_id=customer_id).first()
    if not sc:
        return
    sc.subscription_status = 'canceled'
    sc.save()
    logger.info(f"Subscription canceled for customer {customer_id}")


def _handle_subscription_updated(subscription):
    """Subscription was updated (e.g. resumed). Sync the status."""
    customer_id = getattr(subscription, 'customer', None)
    sc = StripeCustomer.objects.filter(stripe_customer_id=customer_id).first()
    if not sc:
        return
    sc.subscription_status = getattr(subscription, 'status', sc.subscription_status)
    sc.save()


def _update_period_end(sc, invoice):
    """Extract and store the billing period end timestamp."""
    try:
        lines = getattr(getattr(invoice, 'lines', None), 'data', []) or []
        if lines:
            period = getattr(lines[0], 'period', None)
            period_end = getattr(period, 'end', None) if period else None
            if period_end:
                sc.current_period_end = datetime.datetime.fromtimestamp(
                    period_end, tz=datetime.timezone.utc
                )
    except Exception as e:
        logger.warning(f"Could not update period end: {e}")


# ─────────────────────────────────────────────────────────────
# SUBSCRIPTION DETAIL + TRANSACTION HISTORY
# ─────────────────────────────────────────────────────────────
@login_required
def subscription_detail(request):
    """
    Fetches live data from Stripe and displays:
    - Current plan (name, price, interval, status, next billing date)
    - Payment method on file (card brand, last 4, expiry)
    - Full invoice / transaction history (date, amount, status, PDF link)
    Nothing is stored locally — all data is pulled from Stripe in real time.
    """
    sc = None
    plan = None
    invoices = []
    payment_method = None
    stripe_error = None

    try:
        sc = request.user.stripe_customer
    except StripeCustomer.DoesNotExist:
        pass

    if sc and sc.stripe_customer_id:
        try:
            # ── Current subscription ──────────────────────────────
            subscription = None
            if sc.stripe_subscription_id:
                subscription = stripe.Subscription.retrieve(
                    sc.stripe_subscription_id,
                    expand=['default_payment_method', 'items.data.price.product']
                )

            if subscription:
                # stripe-python 15.x: use attribute access, not dict/dict.get()
                item = subscription.items.data[0]
                price = item.price
                product = getattr(price, 'product', None)
                product_name = (
                    getattr(product, 'name', 'FavHost Premium')
                    if product and not isinstance(product, str)
                    else 'FavHost Premium'
                )
                period_start_ts = getattr(subscription, 'current_period_start', None)
                period_end_ts = getattr(subscription, 'current_period_end', None)
                plan = {
                    'name': product_name,
                    'amount': price.unit_amount / 100,
                    'currency': price.currency.upper(),
                    'interval': price.recurring.interval,
                    'status': subscription.status,
                    'cancel_at_period_end': subscription.cancel_at_period_end,
                    'period_start': datetime.datetime.fromtimestamp(
                        period_start_ts, tz=datetime.timezone.utc
                    ) if period_start_ts else None,
                    'period_end': datetime.datetime.fromtimestamp(
                        period_end_ts, tz=datetime.timezone.utc
                    ) if period_end_ts else None,
                }
                payment_method = getattr(subscription, 'default_payment_method', None)

            # ── Payment method fallback: customer default ─────────
            if not payment_method:
                customer = stripe.Customer.retrieve(
                    sc.stripe_customer_id,
                    expand=['invoice_settings.default_payment_method']
                )
                payment_method = getattr(
                    getattr(customer, 'invoice_settings', None),
                    'default_payment_method',
                    None
                )

            # ── Invoice / transaction history ─────────────────────
            raw_invoices = stripe.Invoice.list(
                customer=sc.stripe_customer_id,
                limit=24
            ).data

            for inv in raw_invoices:
                description = 'FavHost Premium'
                if getattr(inv, 'lines', None) and inv.lines.data:
                    description = inv.lines.data[0].description or description
                invoices.append({
                    'date': datetime.datetime.fromtimestamp(inv.created, tz=datetime.timezone.utc),
                    'description': description,
                    'amount': (inv.amount_paid or 0) / 100,
                    'currency': inv.currency.upper(),
                    'status': inv.status,
                    'pdf_url': getattr(inv, 'invoice_pdf', None),
                    'hosted_url': getattr(inv, 'hosted_invoice_url', None),
                    'number': getattr(inv, 'number', None) or '—',
                })

        except stripe.error.StripeError as e:
            logger.error(f"Stripe subscription detail error: {e}")
            stripe_error = str(e)

    context = {
        'sc': sc,
        'plan': plan,
        'invoices': invoices,
        'payment_method': payment_method,
        'stripe_error': stripe_error,
    }
    return render(request, 'billing/subscription.html', context)

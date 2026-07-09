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
from .emails import format_price

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
    from accounts.utils import get_effective_user
    user = get_effective_user(request.user)

    # Check if user already has an active subscription
    try:
        stripe_customer = user.stripe_customer
        is_subscribed = stripe_customer.is_active or user.is_subscription_free
        subscription_status = stripe_customer.subscription_status
        period_end = stripe_customer.current_period_end
    except StripeCustomer.DoesNotExist:
        is_subscribed = user.is_subscription_free
        subscription_status = ''
        period_end = None

    context = {
        'is_subscribed': is_subscribed,
        'subscription_status': subscription_status,
        'period_end': period_end,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
    }
    return render(request, 'frontend/billing/pricing.html', context)


# ─────────────────────────────────────────────────────────────
# CREATE CHECKOUT SESSION → redirect to Stripe
# ─────────────────────────────────────────────────────────────
@login_required
@require_POST
def create_checkout_session(request):
    """
    For returning customers with a saved card: creates the subscription
    directly via the Stripe API — no card form needed.

    For first-time subscribers (or if no saved card exists): falls back
    to the standard Stripe Checkout hosted page.
    """
    domain = settings.DOMAIN_URL.rstrip('/')
    success_url = f"{domain}{reverse('billing:checkout_success')}?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{domain}{reverse('billing:checkout_cancel')}"

    # When set (e.g. the "Resubscribe" button), always open the hosted Stripe
    # Checkout page so the customer sees their saved card and an explicit
    # Subscribe button — instead of the silent one-click saved-card path.
    prefer_checkout = request.POST.get('prefer_checkout') == '1'

    try:
        # Resolve existing Stripe customer, if any
        sc = None
        customer_id = None
        try:
            sc = request.user.stripe_customer
            if sc.stripe_customer_id:
                customer_id = sc.stripe_customer_id
        except StripeCustomer.DoesNotExist:
            pass

        # ── Returning customer: try to reuse saved payment method ──────────
        if customer_id and not prefer_checkout:
            try:
                customer = stripe.Customer.retrieve(
                    customer_id,
                    expand=['invoice_settings.default_payment_method']
                )
                pm = getattr(
                    getattr(customer, 'invoice_settings', None),
                    'default_payment_method',
                    None
                )
                # pm is an expanded object when the customer has a saved card
                if pm and not isinstance(pm, str) and getattr(pm, 'id', None):
                    subscription = stripe.Subscription.create(
                        customer=customer_id,
                        items=[{'price': settings.STRIPE_PRICE_ID}],
                        default_payment_method=pm.id,
                    )
                    # Optimistic DB update — webhooks will also confirm this
                    sc, _ = StripeCustomer.objects.get_or_create(user=request.user)
                    sc.stripe_customer_id = customer_id
                    sc.stripe_subscription_id = subscription.id
                    sc.subscription_status = getattr(subscription, 'status', 'active')
                    sc.cancel_at_period_end = False
                    period_end_ts = getattr(subscription, 'current_period_end', None)
                    if not period_end_ts and getattr(subscription, 'items', None) and subscription.items.data:
                        period_end_ts = getattr(subscription.items.data[0], 'current_period_end', None)
                    if period_end_ts:
                        sc.current_period_end = datetime.datetime.fromtimestamp(
                            period_end_ts, tz=datetime.timezone.utc
                        )
                    sc.save()
                    logger.info(f"Resubscribed user {request.user.username} using saved payment method")
                    return redirect(reverse('billing:checkout_success'))
            except Exception as e:
                logger.warning(f"Saved-card resubscribe failed for customer {customer_id}, falling back to Checkout: {e}")
                # Fall through to standard Checkout below

        # ── New customer or no saved card: standard Stripe Checkout ────────
        def _session_params(use_customer):
            params = {
                'mode': 'subscription',
                'line_items': [{'price': settings.STRIPE_PRICE_ID, 'quantity': 1}],
                'client_reference_id': str(request.user.id),
                'success_url': success_url,
                'cancel_url': cancel_url,
            }
            if use_customer and customer_id:
                params['customer'] = customer_id
            else:
                params['customer_email'] = request.user.email or ''
            return params

        try:
            session = stripe.checkout.Session.create(**_session_params(use_customer=True))
        except stripe.error.InvalidRequestError as e:
            # The stored customer belongs to a different Stripe account/mode
            # (e.g. the API keys were switched) — Stripe answers "No such
            # customer". Rather than dead-ending on the error page, drop the
            # stale ids and start a fresh customer so checkout still works.
            if customer_id and 'no such customer' in str(e).lower():
                logger.warning(
                    f"Stale Stripe customer {customer_id} for {request.user.username}; "
                    f"recreating a fresh customer. {e}"
                )
                if sc is not None:
                    sc.stripe_customer_id = ''
                    sc.stripe_subscription_id = ''
                    sc.save(update_fields=['stripe_customer_id', 'stripe_subscription_id'])
                customer_id = None
                session = stripe.checkout.Session.create(**_session_params(use_customer=False))
            else:
                raise

        return redirect(session.url, code=303)

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating checkout: {e}")
        return render(request, 'frontend/billing/error.html', {'error': str(e)})


# ─────────────────────────────────────────────────────────────
# SUCCESS PAGE (after Stripe redirects back)
# ─────────────────────────────────────────────────────────────
@login_required
def checkout_success(request):
    """
    Stripe redirects here after a successful payment.

    The webhook (checkout.session.completed) is the canonical source of truth,
    but it may be delayed or — in local dev / a misconfigured endpoint — never
    arrive, which would leave the paywall up even though payment succeeded. So
    we ALSO activate synchronously here by re-fetching the Checkout Session from
    Stripe (authenticated with our secret key) and confirming it was paid. This
    is idempotent with the webhook: whichever runs first flips the account to
    active, the other is a no-op.

    Suppress the subscription wall so the confirmation page is fully visible.
    """
    session_id = request.GET.get('session_id')
    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            # Trust only a genuinely paid/complete session, and only for the
            # account that initiated it.
            is_paid = getattr(session, 'payment_status', None) == 'paid' \
                or getattr(session, 'status', None) == 'complete'
            belongs_to_user = str(getattr(session, 'client_reference_id', '') or '') == str(request.user.id)
            if is_paid and belongs_to_user:
                _handle_checkout_completed(session)
        except Exception as e:
            logger.warning(f"Could not sync checkout session {session_id}: {e}")

    return render(request, 'frontend/billing/success.html', {'hide_subscription_wall': True})


# ─────────────────────────────────────────────────────────────
# CANCEL PAGE (user cancelled on Stripe's page)
# ─────────────────────────────────────────────────────────────
@login_required
def checkout_cancel(request):
    """User clicked 'Back' on Stripe's Checkout page. No charge made."""
    return render(request, 'frontend/billing/cancel.html', {'hide_subscription_wall': True})


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
            return_url=f"{settings.DOMAIN_URL.rstrip('/')}{reverse('billing:pricing')}",
        )
        return redirect(portal_session.url, code=303)

    except StripeCustomer.DoesNotExist:
        return redirect('billing:pricing')
    except stripe.error.StripeError as e:
        logger.error(f"Stripe portal error: {e}")
        return render(request, 'frontend/billing/error.html', {'error': str(e)})


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
    sc.cancel_at_period_end = False

    # Fetch full subscription so period end (and plan/card details for the
    # confirmation email) are available immediately.
    sub = None
    if subscription_id:
        try:
            sub = stripe.Subscription.retrieve(
                subscription_id,
                expand=['default_payment_method', 'items.data.price'],
            )
            period_end_ts = getattr(sub, 'current_period_end', None)
            if not period_end_ts and getattr(sub, 'items', None) and sub.items.data:
                period_end_ts = getattr(sub.items.data[0], 'current_period_end', None)
            if period_end_ts:
                sc.current_period_end = datetime.datetime.fromtimestamp(
                    period_end_ts, tz=datetime.timezone.utc
                )
        except Exception as e:
            logger.warning(f"Could not fetch subscription period_end: {e}")

    # Persist activation FIRST. The card is already charged in Stripe, so a
    # later failure (e.g. SMTP down while sending the confirmation email) must
    # never leave a paying customer locked out behind the paywall.
    sc.save()
    logger.info(f"User {user.username} subscription activated")

    # One-time "subscription confirmed" email — best-effort, first subscription
    # only. Wrapped so an email failure can't undo the activation above.
    if not sc.confirmation_email_sent:
        try:
            _send_first_subscription_email(user, sc, sub)
            sc.confirmation_email_sent = True
            sc.save(update_fields=['confirmation_email_sent'])
        except Exception as e:
            logger.warning(
                f"Could not send first-subscription confirmation email for {user.username}: {e}"
            )


def _send_first_subscription_email(user, sc, sub):
    """Gathers plan + payment details and sends the one-time confirmation email."""
    from .emails import send_subscription_confirmation_email

    plan_name = 'Premium'
    amount = 0.0
    currency = 'USD'
    interval = 'month'
    start_date = sc.created_at
    next_payment_date = sc.current_period_end
    card_brand = None
    card_last4 = None

    try:
        if sub is not None:
            item = sub.items.data[0]
            price = item.price
            if getattr(price, 'unit_amount', None) is not None:
                amount = price.unit_amount / 100
            currency = getattr(price, 'currency', 'usd') or 'usd'
            recurring = getattr(price, 'recurring', None)
            if recurring is not None:
                interval = getattr(recurring, 'interval', 'month') or 'month'

            start_ts = getattr(sub, 'current_period_start', None) or getattr(item, 'current_period_start', None)
            if start_ts:
                start_date = datetime.datetime.fromtimestamp(start_ts, tz=datetime.timezone.utc)

            # Payment method: prefer the subscription's, fall back to the customer's default card.
            pm = getattr(sub, 'default_payment_method', None)
            if (not pm or isinstance(pm, str)) and sc.stripe_customer_id:
                customer = stripe.Customer.retrieve(
                    sc.stripe_customer_id,
                    expand=['invoice_settings.default_payment_method'],
                )
                pm = getattr(getattr(customer, 'invoice_settings', None), 'default_payment_method', None)
            card = getattr(pm, 'card', None) if pm and not isinstance(pm, str) else None
            if card is not None:
                card_brand = getattr(card, 'brand', None)
                card_last4 = getattr(card, 'last4', None)
    except Exception as e:
        logger.warning(f"Could not read subscription details for confirmation email: {e}")

    send_subscription_confirmation_email(
        email=user.email,
        first_name=user.first_name or 'there',
        plan_name=plan_name,
        amount=amount,
        currency=currency,
        interval=interval,
        start_date=start_date,
        next_payment_date=next_payment_date,
        card_brand=card_brand,
        card_last4=card_last4,
    )


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
    """Subscription was cancelled. Mark as canceled and notify the customer."""
    customer_id = getattr(subscription, 'customer', None)
    sc = StripeCustomer.objects.filter(stripe_customer_id=customer_id).first()
    if not sc:
        return

    # Only email on the actual transition to canceled — guards against Stripe
    # webhook retries delivering the same event more than once. A fresh
    # cancellation after a resubscribe will send again (status won't be 'canceled').
    was_already_canceled = sc.subscription_status == 'canceled'

    sc.subscription_status = 'canceled'
    sc.save()
    logger.info(f"Subscription canceled for customer {customer_id}")

    if not was_already_canceled:
        try:
            period_end_ts = getattr(subscription, 'current_period_end', None)
            access_until = None
            if period_end_ts:
                access_until = datetime.datetime.fromtimestamp(
                    period_end_ts, tz=datetime.timezone.utc
                )
            # Only mention a future date if access genuinely extends past now.
            if access_until and access_until <= datetime.datetime.now(datetime.timezone.utc):
                access_until = None

            from .emails import send_subscription_cancelled_email
            send_subscription_cancelled_email(
                email=sc.user.email,
                first_name=sc.user.first_name or 'there',
                access_until=access_until,
            )
        except Exception as e:
            logger.warning(f"Could not send cancellation email for customer {customer_id}: {e}")


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
    from accounts.utils import get_effective_user
    user = get_effective_user(request.user)

    sc = None
    plan = None
    invoices = []
    payment_method = None
    stripe_error = None

    try:
        sc = user.stripe_customer
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
                # Stripe flexible billing mode places period dates on the subscription items
                period_start_ts = getattr(subscription, 'current_period_start', None) or getattr(item, 'current_period_start', None)
                period_end_ts = getattr(subscription, 'current_period_end', None) or getattr(item, 'current_period_end', None)
                
                _interval_label_map = {
                    'day': 'Daily',
                    'week': 'Weekly',
                    'month': 'Monthly',
                    'year': 'Yearly',
                }
                raw_interval = price.recurring.interval
                interval_label = _interval_label_map.get(raw_interval, raw_interval.title() if raw_interval else '')
                
                plan = {
                    'name': product_name,
                    'amount': price.unit_amount / 100,
                    'currency': price.currency.upper(),
                    'amount_display': format_price(price.unit_amount / 100, price.currency),
                    'interval': raw_interval,
                    'interval_label': interval_label,
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
                    'amount_display': format_price((inv.amount_paid or 0) / 100, inv.currency),
                    'status': inv.status,
                    'pdf_url': getattr(inv, 'invoice_pdf', None),
                    'hosted_url': getattr(inv, 'hosted_invoice_url', None),
                    'number': getattr(inv, 'number', None) or '—',
                })

        except stripe.error.StripeError as e:
            logger.error(f"Stripe subscription detail error: {e}")
            stripe_error = str(e)

    context = {
        'user': user,
        'sc': sc,
        'plan': plan,
        'invoices': invoices,
        'payment_method': payment_method,
        'stripe_error': stripe_error,
    }
    return render(request, 'frontend/billing/subscription.html', context)

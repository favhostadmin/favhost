"""One-time Stripe payments for AI Studio (Photo Enhancer: per photo, Listing Optimize: per report).

Flow: the page asks for a checkout -> we store a pending Order and create a Stripe Checkout Session ->
the visitor pays on Stripe -> Stripe sends them back to the page (and, separately, calls the webhook).
Both the return trip and the webhook call fulfill(), which is idempotent, so whichever arrives first
unlocks the content and the other is a no-op.
"""
import logging

import stripe
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import BoosterLead, ImageJob, ListingReport, Order

logger = logging.getLogger(__name__)

PRICE_CACHE_SECONDS = 3600
SYMBOLS = {'usd': '$', 'eur': '€', 'gbp': '£', 'inr': '₹', 'aud': 'A$', 'cad': 'C$'}


class PaymentError(Exception):
    """Raised with a message that is safe to show to the visitor."""


def _product_id(kind):
    return settings.AI_PHOTO_PRODUCT_ID if kind == Order.KIND_PHOTOS else settings.AI_REPORT_PRODUCT_ID


def money(cents, currency='usd'):
    """12345 -> '$123.45', 50 -> '$0.50'."""
    symbol = SYMBOLS.get((currency or 'usd').lower(), (currency or '').upper() + ' ')
    return f'{symbol}{cents / 100:,.2f}'


def get_price(kind):
    """The product's default price as {'id', 'amount', 'currency'}. Cached; raises PaymentError."""
    cache_key = f'aibooster:price:{kind}'
    price = cache.get(cache_key)
    if price:
        return price
    if not settings.STRIPE_SECRET_KEY:
        raise PaymentError('Payments are not set up yet. Please try again later.')
    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        product = stripe.Product.retrieve(_product_id(kind))
        price_id = product.default_price
        if not price_id:
            raise PaymentError('This product has no price yet.')
        obj = stripe.Price.retrieve(price_id)
        if obj.unit_amount is None:
            raise PaymentError('This product has no fixed price.')
        price = {'id': obj.id, 'amount': int(obj.unit_amount), 'currency': obj.currency}
    except PaymentError:
        raise
    except stripe.error.StripeError:
        logger.exception('AI Studio: could not read the Stripe price for %s', kind)
        raise PaymentError('We couldn’t reach our payment provider. Please try again in a moment.')
    cache.set(cache_key, price, PRICE_CACHE_SECONDS)
    return price


def price_info(kind):
    """For templates and JS; None if the price can't be read (the page then hides prices)."""
    try:
        p = get_price(kind)
    except PaymentError:
        return None
    return {'cents': p['amount'], 'currency': p['currency'], 'display': money(p['amount'], p['currency'])}


def create_checkout(request, order, success_url, cancel_url):
    """Create the Stripe Checkout Session for a saved Order; returns the hosted payment URL."""
    price = get_price(order.kind)
    order.unit_amount = price['amount']
    order.amount_total = price['amount'] * order.quantity
    order.currency = price['currency']
    params = dict(
        mode='payment',
        line_items=[{'price': price['id'], 'quantity': order.quantity}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(order.id),
        metadata={'ai_order_id': str(order.id), 'ai_kind': order.kind},
        payment_intent_data={'metadata': {'ai_order_id': str(order.id), 'ai_kind': order.kind}},
    )
    if request.user.is_authenticated and getattr(request.user, 'email', ''):
        params['customer_email'] = request.user.email
    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(**params)
    except stripe.error.StripeError:
        logger.exception('AI Studio: could not create a checkout session for order %s', order.id)
        raise PaymentError('We couldn’t start the payment. Please try again in a moment.')
    order.stripe_session_id = session.id
    order.save()
    return session.url


# ── fulfilment ──────────────────────────────────────────────────────────────

def _fulfill_photos(order):
    from .tasks import dispatch  # imported here: tasks imports pipeline, which imports models
    jobs = list(ImageJob.objects.select_for_update().filter(pk__in=order.job_ids))
    release = []
    for job in jobs:
        job.is_paid = True
        if job.status == ImageJob.STATUS_HELD:
            job.status = ImageJob.STATUS_PENDING   # the locked photos are enhanced now
            release.append(job.id)
        job.save(update_fields=['is_paid', 'status'])
    # Queue only after the transaction commits, so a fast worker sees the paid flag.
    transaction.on_commit(lambda: [dispatch(job_id) for job_id in release])


def _fulfill_report(order):
    if order.report_id:
        ListingReport.objects.filter(pk=order.report_id).update(is_paid=True)


def fulfill(order_id, session=None):
    """Mark an order paid and unlock what it bought. Safe to call any number of times."""
    with transaction.atomic():
        try:
            order = Order.objects.select_for_update().get(pk=order_id)
        except (Order.DoesNotExist, ValueError):
            logger.warning('AI Studio: payment for unknown order %s', order_id)
            return None
        if order.status == Order.STATUS_PAID:
            return order
        order.status = Order.STATUS_PAID
        order.paid_at = timezone.now()
        if session is not None:
            details = getattr(session, 'customer_details', None)
            order.customer_email = (getattr(details, 'email', '') or '')[:254]
            order.customer_name = (getattr(details, 'name', '') or '')[:200]
            total = getattr(session, 'amount_total', None)
            if total is not None:
                order.amount_total = int(total)
        order.save()
        if order.kind == Order.KIND_PHOTOS:
            _fulfill_photos(order)
        else:
            _fulfill_report(order)
        if order.customer_email:
            BoosterLead.objects.create(
                name=order.customer_name or order.customer_email.split('@')[0], email=order.customer_email,
                feature=BoosterLead.FEATURE_IMAGE if order.kind == Order.KIND_PHOTOS else BoosterLead.FEATURE_REPORT,
            )
    return order


def confirm_session(session_id):
    """Called when the visitor lands back on the page: ask Stripe, don't trust the URL. Returns the
    paid Order, or None if the payment isn't complete."""
    if not session_id:
        return None
    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError:
        logger.exception('AI Studio: could not verify checkout session')
        return None
    order_id = (session.metadata or {}).get('ai_order_id') if session.metadata else None
    if not order_id or session.payment_status != 'paid':
        return None
    return fulfill(order_id, session)


def handle_webhook_session(session):
    """checkout.session.completed from the shared Stripe webhook. True if it was one of ours."""
    metadata = getattr(session, 'metadata', None) or {}
    order_id = metadata.get('ai_order_id') if hasattr(metadata, 'get') else None
    if not order_id:
        return False
    if getattr(session, 'payment_status', '') == 'paid':
        fulfill(order_id, session)
    return True

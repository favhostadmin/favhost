"""Email helpers for the billing app."""
import os
import logging
from email.mime.image import MIMEImage

from django.conf import settings
from django.urls import reverse
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.contrib.staticfiles import finders

logger = logging.getLogger(__name__)

# Common currency symbols; falls back to the upper-case code for anything else.
_CURRENCY_SYMBOLS = {
    'USD': '$',
    'EUR': '€',
    'GBP': '£',
    'INR': '₹',
    'AUD': 'A$',
    'CAD': 'C$',
}

_INTERVAL_LABELS = {
    'day': 'day',
    'week': 'week',
    'month': 'month',
    'year': 'year',
}


def format_price(amount, currency):
    """Turn (9.99, 'USD') into '$9.99' (or '9.99 SEK' for unknown codes)."""
    currency = (currency or 'USD').upper()
    symbol = _CURRENCY_SYMBOLS.get(currency)
    # Show no trailing .00 cents only if it's a whole number — keep 9.99 as-is.
    amount_str = f"{amount:.2f}"
    if symbol:
        return f"{symbol}{amount_str}"
    return f"{amount_str} {currency}"


def _abs_url(path):
    """Build an absolute URL from a path using DOMAIN_URL (no request in webhooks)."""
    domain = getattr(settings, 'DOMAIN_URL', 'https://favhost.com').rstrip('/')
    return f"{domain}{path}"


def send_subscription_confirmation_email(
    *, email, first_name, plan_name, amount, currency, interval,
    start_date, next_payment_date, card_brand=None, card_last4=None,
):
    """
    Sends the one-time "subscription confirmed" email (HTML + plain text, inline logo).

    Dates may be datetime objects or already-formatted strings; amount is a float
    (e.g. 9.99) and currency a 3-letter code (e.g. 'USD').
    """
    try:
        def _fmt_date(d):
            if not d:
                return ''
            try:
                return d.strftime('%B %d, %Y')
            except AttributeError:
                return str(d)

        price_amount = format_price(amount, currency)
        interval_label = _INTERVAL_LABELS.get((interval or 'month').lower(), interval or 'month')
        start_str = _fmt_date(start_date)
        next_str = _fmt_date(next_payment_date)

        dashboard_url = _abs_url(reverse('dashboard'))
        manage_url = _abs_url(reverse('billing:subscription'))
        terms_url = _abs_url(reverse('terms'))
        privacy_url = _abs_url(reverse('privacy'))
        contact_url = _abs_url(reverse('contact'))

        context = {
            'first_name': first_name or 'there',
            'logo_url': 'cid:logo',
            'plan_name': plan_name or 'Premium',
            'price_amount': price_amount,
            'interval_label': interval_label,
            'start_date': start_str,
            'next_payment_date': next_str,
            'card_brand': (card_brand or '').title(),
            'card_last4': card_last4 or '',
            'dashboard_url': dashboard_url,
            'manage_url': manage_url,
            'terms_url': terms_url,
            'privacy_url': privacy_url,
            'contact_url': contact_url,
        }

        html_body = render_to_string('frontend/emails/subscription_confirmation.html', context)

        card_line = ''
        if card_last4:
            card_line = f"Payment method: {context['card_brand']} •••• {card_last4}\n"

        plain_body = (
            f"Hi {context['first_name']},\n\n"
            "Welcome to Premium — your payment is confirmed. You keep full access to the "
            "entire Favhost platform, exactly as before.\n\n"
            f"Plan: {context['plan_name']}\n"
            f"Billing: {price_amount} / {interval_label}\n"
            f"Start date: {start_str}\n"
            f"{card_line}"
            f"Next payment: {next_str}\n\n"
            f"Your subscription renews automatically — we'll charge {price_amount} on "
            f"{next_str}. Change or cancel any time before then: {manage_url}\n\n"
            f"Dashboard: {dashboard_url}\n\n"
            "Questions about your billing? support@favhost.com\n\n"
            "Team Favhost"
        )

        support_email = getattr(settings, 'SUPPORT_EMAIL', 'support@favhost.com')
        email_msg = EmailMultiAlternatives(
            subject='Your Favhost subscription is confirmed',
            body=plain_body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@favhost.com'),
            to=[email],
            reply_to=[support_email],
            headers={'List-Unsubscribe': f'<mailto:{support_email}?subject=Unsubscribe>'},
        )
        email_msg.attach_alternative(html_body, 'text/html')
        email_msg.mixed_subtype = 'related'

        # Attach the logo inline (same asset used by the OTP / welcome emails)
        logo_path = finders.find('img/login/favhost_new_logo.png')
        if logo_path and os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', '<logo>')
                # Mark as inline so clients render it in the header, not as an attachment.
                img.add_header('Content-Disposition', 'inline', filename='favhost_logo.png')
                img.add_header('X-Attachment-Id', 'logo')
                email_msg.attach(img)

        email_msg.send(fail_silently=True)
    except Exception as e:
        logger.warning(f"Could not send subscription confirmation email to {email}: {e}")


def send_subscription_cancelled_email(*, email, first_name, access_until=None):
    """
    Sends the "subscription cancelled" email (HTML + plain text, inline logo).

    access_until: optional datetime/string for when paid access ends. If given,
    the email says access continues until then; otherwise it says access has ended.
    """
    try:
        def _fmt_date(d):
            if not d:
                return ''
            try:
                return d.strftime('%B %d, %Y')
            except AttributeError:
                return str(d)

        until_str = _fmt_date(access_until)
        if until_str:
            access_line = f"You'll keep access until {until_str}, then your subscription ends."
            plain_access = f"You'll keep access until {until_str}, then your subscription ends."
        else:
            access_line = "Your access to the Favhost platform has now ended."
            plain_access = "Your access to the Favhost platform has now ended."

        pricing_url = _abs_url(reverse('billing:pricing'))
        terms_url = _abs_url(reverse('terms'))
        privacy_url = _abs_url(reverse('privacy'))
        contact_url = _abs_url(reverse('contact'))

        context = {
            'first_name': first_name or 'there',
            'logo_url': 'cid:logo',
            'access_line': access_line,
            'pricing_url': pricing_url,
            'terms_url': terms_url,
            'privacy_url': privacy_url,
            'contact_url': contact_url,
        }

        html_body = render_to_string('frontend/emails/subscription_cancelled.html', context)

        plain_body = (
            f"Hi {context['first_name']},\n\n"
            "We've cancelled your Favhost Premium subscription as requested. We're sorry to "
            "see you go — your account and data are kept safe.\n\n"
            f"{plain_access} To keep full access to the Favhost platform, you can resubscribe "
            "anytime and everything stays exactly as you left it.\n\n"
            f"Resubscribe: {pricing_url}\n\n"
            "Cancelled by mistake, or have feedback? We'd love to hear from you at "
            "support@favhost.com\n\n"
            "Team Favhost"
        )

        support_email = getattr(settings, 'SUPPORT_EMAIL', 'support@favhost.com')
        email_msg = EmailMultiAlternatives(
            subject='Your Favhost subscription has been cancelled',
            body=plain_body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@favhost.com'),
            to=[email],
            reply_to=[support_email],
            headers={'List-Unsubscribe': f'<mailto:{support_email}?subject=Unsubscribe>'},
        )
        email_msg.attach_alternative(html_body, 'text/html')
        email_msg.mixed_subtype = 'related'

        # Attach the logo inline (same asset used by the OTP / welcome emails)
        logo_path = finders.find('img/login/favhost_new_logo.png')
        if logo_path and os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', '<logo>')
                img.add_header('Content-Disposition', 'inline', filename='favhost_logo.png')
                img.add_header('X-Attachment-Id', 'logo')
                email_msg.attach(img)

        email_msg.send(fail_silently=True)
    except Exception as e:
        logger.warning(f"Could not send subscription cancelled email to {email}: {e}")

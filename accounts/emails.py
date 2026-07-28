"""Email helpers for the accounts app (non-OTP transactional emails)."""
import os
import logging
from email.mime.image import MIMEImage

from django.conf import settings
from django.urls import reverse
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.contrib.staticfiles import finders

logger = logging.getLogger(__name__)


def _abs_url(path):
    """Build an absolute URL from a path using DOMAIN_URL (no request in cron jobs)."""
    domain = getattr(settings, 'DOMAIN_URL', 'https://favhost.com').rstrip('/')
    return f"{domain}{path}"


def _fmt_date(d):
    if not d:
        return ''
    try:
        return d.strftime('%B %d, %Y')
    except AttributeError:
        return str(d)


def send_trial_ending_email(user, trial_end, days_left, price_display='$9.99/month'):
    """
    Sends the one-time "your trial ends in N days" email (HTML + plain text, inline logo).

    `trial_end` is a datetime/date; `days_left` an int; `price_display` a ready string.
    """
    try:
        first_name = (user.first_name or 'there')
        trial_end_str = _fmt_date(trial_end)

        pricing_url = _abs_url(reverse('billing:pricing'))
        terms_url = _abs_url(reverse('terms'))
        privacy_url = _abs_url(reverse('privacy'))
        contact_url = _abs_url(reverse('contact'))

        context = {
            'first_name': first_name,
            'logo_url': 'cid:logo',
            'days_left': days_left,
            'trial_end_date': trial_end_str,
            'price_display': price_display,
            'pricing_url': pricing_url,
            'terms_url': terms_url,
            'privacy_url': privacy_url,
            'contact_url': contact_url,
        }

        html_body = render_to_string('frontend/emails/trial_ending.html', context)

        day_word = 'day' if days_left == 1 else 'days'
        plain_body = (
            f"Hi {first_name},\n\n"
            f"Your Favhost free trial ends on {trial_end_str} — {days_left} {day_word} left.\n\n"
            "Subscribe to Premium before then to keep your full access, with no interruption. "
            "You keep every feature you use today, exactly as it is.\n\n"
            f"When your trial ends, access to the platform pauses until you subscribe. "
            f"Upgrade now and nothing changes.\n\n"
            f"Upgrade to Premium ({price_display} - cancel anytime): {pricing_url}\n\n"
            "Questions? support@favhost.com\n\n"
            "Team Favhost"
        )

        support_email = getattr(settings, 'SUPPORT_EMAIL', 'support@favhost.com')
        email_msg = EmailMultiAlternatives(
            subject='Your Favhost trial ends soon',
            body=plain_body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@favhost.com'),
            to=[user.email],
            reply_to=[support_email],
            # List-Unsubscribe improves Gmail inbox placement for promotional mail.
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

        # fail_silently=False so SMTP problems reach the except below instead of
        # being reported as a successful send.
        email_msg.send(fail_silently=False)
        logger.info("Trial-ending email sent to %s (%s days left)", user.email, days_left)
    except Exception as e:
        logger.warning("Could not send trial-ending email to %s: %s", getattr(user, 'email', '?'), e)

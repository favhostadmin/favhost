import os
from email.mime.image import MIMEImage
from datetime import timedelta
import logging
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.contrib.staticfiles import finders
from celery import shared_task
from .models import Booking

logger = logging.getLogger(__name__)


def _attach_inline_images(email, booking):
    """Attach the logo, property thumbnail, contact icons and host avatar as
    inline (cid:) images shared by both the check-in and check-out emails."""
    # Logo
    logo_path = finders.find('img/login/favhost_new_logo.png')
    if logo_path and os.path.exists(logo_path):
        with open(logo_path, 'rb') as f:
            img = MIMEImage(f.read())
            img.add_header('Content-ID', '<logo>')
            email.attach(img)

    # Property thumbnail (primary image -> any image -> placeholder)
    prop_img_obj = booking.property.images.filter(is_primary=True).first() or \
                   booking.property.images.first()
    img_path = None
    if prop_img_obj and prop_img_obj.image:
        img_path = prop_img_obj.image.path
    if not img_path or not os.path.exists(img_path):
        img_path = finders.find('img/property/placeholder-image.png')
    if img_path and os.path.exists(img_path):
        try:
            with open(img_path, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', '<property_image>')
                email.attach(img)
        except Exception:
            pass

    # Contact icons
    for icon_path_rel, icon_cid in [
        ('img/email/location.png', 'location_icon'),
        ('img/email/phone.png', 'phone_icon'),
        ('img/email/email.png', 'email_icon'),
    ]:
        icon_path = finders.find(icon_path_rel)
        if icon_path and os.path.exists(icon_path):
            with open(icon_path, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', f'<{icon_cid}>')
                email.attach(img)

    # Host avatar (profile picture -> default icon)
    host_user = booking.property.created_by
    host_avatar_path = None
    if host_user and host_user.profile_picture:
        try:
            host_avatar_path = host_user.profile_picture.path
        except ValueError:
            pass
    if not host_avatar_path or not os.path.exists(host_avatar_path):
        host_avatar_path = finders.find('img/common/default_user_icon_1.png')
    if host_avatar_path and os.path.exists(host_avatar_path):
        with open(host_avatar_path, 'rb') as f:
            img = MIMEImage(f.read())
            img.add_header('Content-ID', '<host_avatar>')
            email.attach(img)


def _send_instruction_email(booking, kind):
    """Build and send a single check-in or check-out instruction email.

    ``kind`` is 'check_in' or 'check_out'. Returns True on success.
    """
    if not booking.email:
        logger.warning(f"No email found for booking {booking.booking_id}. Skipping.")
        return False

    docs = booking.property.documents.filter(document_type=kind)
    context = {
        'booking': booking,
        'property': booking.property,
        'documents': docs,
        'logo_url': 'cid:logo',
        'location_icon_url': 'cid:location_icon',
        'phone_icon_url': 'cid:phone_icon',
        'email_icon_url': 'cid:email_icon',
        'host_avatar_url': 'cid:host_avatar',
        'property_image_url': 'cid:property_image',
        'base_url': settings.BASE_URL,
        'check_in_time': booking.check_in_time or booking.property.check_in_time,
        'check_out_time': booking.check_out_time or booking.property.check_out_time,
    }

    if kind == 'check_in':
        template = 'frontend/emails/check_in.html'
        subject = f"Check-in Instructions for {booking.property.title}"
    else:
        template = 'frontend/emails/check_out.html'
        subject = f"Check-out Instructions for {booking.property.title}"

    html_content = render_to_string(template, context)
    text_content = strip_tags(html_content)

    email = EmailMultiAlternatives(
        subject, text_content, settings.DEFAULT_FROM_EMAIL, [booking.email]
    )
    email.attach_alternative(html_content, "text/html")
    email.mixed_subtype = 'related'
    _attach_inline_images(email, booking)
    email.send()
    return True


def _owner_allows(booking, field):
    """Whether the property owner's account-level master switch permits this
    email type. Missing owner is treated as allowed (per-property flag governs)."""
    owner = booking.property.created_by
    if owner is None:
        return True
    return bool(getattr(owner, field, True))


@shared_task
def send_daily_booking_emails():
    """Send check-in / check-out instruction emails at each property's *local*
    midnight, so a hotel in India is emailed at India midnight, one in the USA
    at US midnight, etc.

    This task is scheduled hourly. On each run it looks at bookings whose
    check-in / check-out date is near "now" (a small UTC window), and for each
    one sends only if it is currently the midnight hour (00:00-00:59) in that
    property's own timezone and the relevant date matches that local date.
    The per-booking *_email_sent flags guarantee a single send.
    """
    now_utc = timezone.now()
    utc_today = now_utc.date()
    # Local midnight for any timezone falls on a UTC date within +/-1 day.
    window = [utc_today - timedelta(days=1), utc_today, utc_today + timedelta(days=1)]

    sent_checkins = 0
    sent_checkouts = 0

    # 1. Check-ins
    checkins = Booking.objects.filter(
        check_in_date__in=window,
        checkin_email_sent=False,
        status='confirmed',
        property__status='Active',
        property__email_guest_checkin=True,
    ).select_related('property', 'property__created_by', 'channel')

    for booking in checkins:
        try:
            if not _owner_allows(booking, 'email_guest_checkin'):
                continue
            local_now = now_utc.astimezone(booking.property.get_timezone())
            if local_now.hour != 0 or booking.check_in_date != local_now.date():
                continue
            if _send_instruction_email(booking, 'check_in'):
                booking.checkin_email_sent = True
                booking.save(update_fields=['checkin_email_sent'])
                sent_checkins += 1
                logger.info(
                    f"Check-in email sent to {booking.email} for booking {booking.booking_id}"
                )
        except Exception as e:
            logger.error(f"Failed to send check-in email for booking {booking.booking_id}: {str(e)}")

    # 2. Check-outs
    checkouts = Booking.objects.filter(
        check_out_date__in=window,
        checkout_email_sent=False,
        status='confirmed',
        property__status='Active',
        property__email_guest_checkout=True,
    ).select_related('property', 'property__created_by', 'channel')

    for booking in checkouts:
        try:
            if not _owner_allows(booking, 'email_guest_checkout'):
                continue
            local_now = now_utc.astimezone(booking.property.get_timezone())
            if local_now.hour != 0 or booking.check_out_date != local_now.date():
                continue
            if _send_instruction_email(booking, 'check_out'):
                booking.checkout_email_sent = True
                booking.save(update_fields=['checkout_email_sent'])
                sent_checkouts += 1
                logger.info(
                    f"Check-out email sent to {booking.email} for booking {booking.booking_id}"
                )
        except Exception as e:
            logger.error(f"Failed to send check-out email for booking {booking.booking_id}: {str(e)}")

    return f"Sent {sent_checkins} check-in and {sent_checkouts} check-out emails."

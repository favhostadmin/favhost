import os
from email.mime.image import MIMEImage
from datetime import timedelta
from urllib.parse import quote_plus
import logging
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.core.mail.message import SafeMIMEMultipart
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.contrib.staticfiles import finders
from django.urls import reverse
from celery import shared_task
from accounts import currency
from property.tokens import sign_document_token
from property.policies import policy_path
from .models import Booking

logger = logging.getLogger(__name__)


#: Skip attaching host documents beyond this combined size so the message is not
#: rejected by the receiving mail server. The email still links to them.
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024


class InstructionEmail(EmailMultiAlternatives):
    """Email that keeps inline (cid:) images inline while still delivering the
    host's check-in / check-out documents as real, openable attachments.

    Builds ``multipart/mixed[ multipart/related[ alternative, images ], docs ]``.
    Putting the images in their own ``related`` part is what stops mail clients
    from listing the logo and icons as attachments, and stops the documents from
    being swallowed as inline parts (which is why they could not be opened).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inline_images = []

    def attach_inline(self, mime_image):
        self.inline_images.append(mime_image)

    def _create_message(self, msg):
        msg = self._create_alternatives(msg)
        if self.inline_images:
            related = SafeMIMEMultipart(_subtype='related', encoding=self.encoding)
            related.attach(msg)
            for img in self.inline_images:
                related.attach(img)
            msg = related
        return self._create_attachments(msg)


def _attach_documents(email, docs):
    """Attach the host's instruction documents as regular file attachments.

    Returns the number of documents attached. Unreadable files are skipped and
    logged; the email body still links to every document either way.
    """
    attached = 0
    total = 0
    for doc in docs:
        if not doc.document:
            continue
        try:
            with doc.document.open('rb') as f:
                content = f.read()
        except (ValueError, FileNotFoundError, OSError) as exc:
            logger.warning(f"Could not read document {doc.pk} ({doc.name}): {exc}")
            continue

        if total + len(content) > MAX_ATTACHMENT_BYTES:
            logger.warning(
                f"Skipping document {doc.pk} ({doc.name}): attachment size limit reached."
            )
            continue

        filename = doc.name or os.path.basename(doc.document.name)
        if not os.path.splitext(filename)[1]:
            # Without an extension clients cannot tell what to open the file with.
            filename += os.path.splitext(doc.document.name)[1]

        email.attach(filename, content, doc.file_type or None)
        total += len(content)
        attached += 1
    return attached


def _attach_inline_images(email, booking):
    """Attach the logo, property thumbnail, contact icons and host avatar as
    inline (cid:) images shared by both the check-in and check-out emails."""
    # Logo
    logo_path = finders.find('img/login/favhost_new_logo.png')
    if logo_path and os.path.exists(logo_path):
        with open(logo_path, 'rb') as f:
            img = MIMEImage(f.read())
            img.add_header('Content-ID', '<logo>')
            img.add_header('Content-Disposition', 'inline', filename='logo.png')
            email.attach_inline(img)

    # Property thumbnail (primary image -> any image -> placeholder)
    prop_img_obj = booking.property.images.filter(is_primary=True).first() or \
                   booking.property.images.first()
    prop_img_bytes = None
    if prop_img_obj and prop_img_obj.image:
        try:
            with prop_img_obj.image.open('rb') as f:
                prop_img_bytes = f.read()
        except (ValueError, FileNotFoundError, OSError):
            pass
    if prop_img_bytes is None:
        placeholder_path = finders.find('img/property/placeholder-image.png')
        if placeholder_path and os.path.exists(placeholder_path):
            with open(placeholder_path, 'rb') as f:
                prop_img_bytes = f.read()
    if prop_img_bytes is not None:
        img = MIMEImage(prop_img_bytes)
        img.add_header('Content-ID', '<property_image>')
        img.add_header('Content-Disposition', 'inline', filename='property.png')
        email.attach_inline(img)

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
                img.add_header('Content-Disposition', 'inline', filename=f'{icon_cid}.png')
                email.attach_inline(img)

    # Host avatar (profile picture -> default icon)
    host_user = booking.property.created_by
    host_avatar_bytes = None
    if host_user and host_user.profile_picture:
        try:
            with host_user.profile_picture.open('rb') as f:
                host_avatar_bytes = f.read()
        except (ValueError, FileNotFoundError, OSError):
            pass
    if host_avatar_bytes is None:
        default_icon_path = finders.find('img/common/default_user_icon_1.png')
        if default_icon_path and os.path.exists(default_icon_path):
            with open(default_icon_path, 'rb') as f:
                host_avatar_bytes = f.read()
    if host_avatar_bytes is not None:
        img = MIMEImage(host_avatar_bytes)
        img.add_header('Content-ID', '<host_avatar>')
        img.add_header('Content-Disposition', 'inline', filename='host_avatar.png')
        email.attach_inline(img)


def _policy_url(prop, kind):
    """Absolute URL of a policy page, or '' when the host left that policy blank."""
    path = policy_path(prop, kind)
    return f"{settings.BASE_URL}{path}" if path else ''


def _full_address(prop):
    """The property's full postal address on one line, skipping blank parts."""
    parts = [prop.street_address, prop.city, prop.state, prop.zip, prop.country]
    return ', '.join(str(p).strip() for p in parts if p and str(p).strip())


def _map_url(prop):
    """A Google Maps link for the property, or '' if there is no address to map."""
    address = _full_address(prop)
    if not address:
        return ''
    return 'https://www.google.com/maps/search/?api=1&query=' + quote_plus(address)


def _send_instruction_email(booking, kind):
    """Build and send a single check-in or check-out instruction email.

    ``kind`` is 'check_in' or 'check_out'. Returns True on success.
    """
    if not booking.email:
        logger.warning(f"No email found for booking {booking.booking_id}. Skipping.")
        return False

    prop = booking.property
    host = prop.created_by
    docs = list(prop.documents.filter(document_type=kind))
    # A permanent signed link, not `document.url`: on a real server media sits in
    # a private S3 bucket whose presigned URLs expire in an hour, long before the
    # guest opens an email sent at local midnight. Resolving the token re-signs
    # at click time. (Absolute, since `.url` may already be a full S3 URL and
    # must never be concatenated onto BASE_URL.)
    for doc in docs:
        doc.open_url = settings.BASE_URL + reverse(
            'property:open-document', kwargs={'token': sign_document_token(doc.pk)}
        )

    # Price breakdown — mirrors the Reservation "Payment details" page exactly
    # (booking.views.payment_details) so the guest sees the same figures.
    nights = booking.total_nights
    subtotal = (booking.price_per_night or 0) * nights
    total_price = subtotal + (booking.cleaning_fee or 0) + (booking.deposit_fee or 0) \
        + (booking.taxes or 0) + (booking.other_fees or 0)
    monthly_payment = (booking.price_per_night or 0) * 30 if nights >= 30 else 0

    listing_url = f"{settings.BASE_URL}{prop.get_absolute_url()}"

    context = {
        'booking': booking,
        'property': prop,
        'documents': docs,
        'host': host,
        # Address + map
        'full_address': _full_address(prop),
        'map_url': _map_url(prop),
        # Pricing (stored USD; rendered by {% money %} in the host's currency)
        'nights': nights,
        'subtotal': subtotal,
        'monthly_payment': monthly_payment,
        'total_price': total_price,
        # Standalone public policy pages (no login required for guests). Each is
        # '' when the host left that policy blank, so the email hides the row
        # rather than linking to a page that would 404.
        'listing_url': listing_url,
        'house_rules_url': _policy_url(prop, 'house-rules'),
        'cancellation_policy_url': _policy_url(prop, 'cancellation-policy'),
        'rental_contract_url': _policy_url(prop, 'rental-contract'),
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

    # No request/cookie in an email, so amounts render in the host's own currency
    # — the same default the public listing page falls back to.
    context.update(currency.display_context(
        currency.resolve_display_currency(None, getattr(host, 'currency', None))
    ))

    if kind == 'check_in':
        template = 'frontend/emails/check_in.html'
        subject = f"Check-in Instructions for {booking.property.title}"
    else:
        template = 'frontend/emails/check_out.html'
        subject = f"Check-out Instructions for {booking.property.title}"

    html_content = render_to_string(template, context)
    text_content = strip_tags(html_content)

    email = InstructionEmail(
        subject, text_content, settings.DEFAULT_FROM_EMAIL, [booking.email]
    )
    email.attach_alternative(html_content, "text/html")
    _attach_inline_images(email, booking)
    _attach_documents(email, docs)
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

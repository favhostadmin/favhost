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

@shared_task
def send_daily_booking_emails():
    """
    Task to send check-in and check-out emails daily at 12:01 AM.
    """
    today = timezone.now().date()
    tomorrow = today + timedelta(days=1)

    # 1. Process Check-ins
    checkins = Booking.objects.filter(
        check_in_date=tomorrow,
        checkin_email_sent=False,
        status='confirmed',
        property__status='Active',
        property__email_guest=True
    ).select_related('property', 'channel')

    for booking in checkins:
        try:
            if not booking.email:
                logger.warning(f"No email found for booking {booking.booking_id}. Skipping.")
                continue

            # Fetch property-specific check-in documents
            docs = booking.property.documents.filter(document_type='check_in')
            
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
            html_content = render_to_string('frontend/emails/check_in.html', context)
            text_content = strip_tags(html_content)
            
            subject = f"Check-in Instructions for {booking.property.title}"
            email = EmailMultiAlternatives(
                subject, text_content, settings.DEFAULT_FROM_EMAIL, [booking.email]
            )
            email.attach_alternative(html_content, "text/html")
            email.mixed_subtype = 'related'

            # Attach Logo
            logo_path = finders.find('img/login/favhost_new_logo.png')
            if logo_path and os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    img = MIMEImage(f.read())
                    img.add_header('Content-ID', '<logo>')
                    email.attach(img)

            # Attach Property Thumbnail
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
                except Exception: pass

            # Attach Icons (Location, Phone, Email)
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

            # Attach Host Avatar
            host_user = booking.property.created_by
            host_avatar_path = None
            if host_user.profile_picture:
                try: host_avatar_path = host_user.profile_picture.path
                except ValueError: pass
            
            if not host_avatar_path or not os.path.exists(host_avatar_path):
                host_avatar_path = finders.find('img/common/default_user_icon_1.png')

            if host_avatar_path and os.path.exists(host_avatar_path):
                with open(host_avatar_path, 'rb') as f:
                    img = MIMEImage(f.read())
                    img.add_header('Content-ID', '<host_avatar>')
                    email.attach(img)

            email.send()

            booking.checkin_email_sent = True
            booking.save(update_fields=['checkin_email_sent'])
            logger.info(f"Check-in email sent successfully to {booking.email} for booking {booking.booking_id}")
        except Exception as e:
            logger.error(f"Failed to send check-in email for booking {booking.booking_id}: {str(e)}")

    # 2. Process Check-outs
    checkouts = Booking.objects.filter(
        check_out_date=tomorrow,
        checkout_email_sent=False,
        status='confirmed',
        property__status='Active',
        property__email_guest=True
    ).select_related('property', 'channel')

    for booking in checkouts:
        try:
            if not booking.email:
                logger.warning(f"No email found for booking {booking.booking_id}. Skipping.")
                continue

            # Fetch property-specific check-out documents
            docs = booking.property.documents.filter(document_type='check_out')

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
            html_content = render_to_string('frontend/emails/check_out.html', context)
            text_content = strip_tags(html_content)

            subject = f"Check-out Instructions for {booking.property.title}"
            email = EmailMultiAlternatives(
                subject, text_content, settings.DEFAULT_FROM_EMAIL, [booking.email]
            )
            email.attach_alternative(html_content, "text/html")
            email.mixed_subtype = 'related'

            # Attach Logo
            logo_path = finders.find('img/login/favhost_new_logo.png')
            if logo_path and os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    img = MIMEImage(f.read())
                    img.add_header('Content-ID', '<logo>')
                    email.attach(img)

            # Attach Property Thumbnail
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
                except Exception: pass

            # Attach Icons (Location, Phone, Email)
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

            # Attach Host Avatar
            host_user = booking.property.created_by
            host_avatar_path = None
            if host_user.profile_picture:
                try: host_avatar_path = host_user.profile_picture.path
                except ValueError: pass
            
            if not host_avatar_path or not os.path.exists(host_avatar_path):
                host_avatar_path = finders.find('img/common/default_user_icon_1.png')

            if host_avatar_path and os.path.exists(host_avatar_path):
                with open(host_avatar_path, 'rb') as f:
                    img = MIMEImage(f.read())
                    img.add_header('Content-ID', '<host_avatar>')
                    email.attach(img)

            email.send()

            booking.checkout_email_sent = True
            booking.save(update_fields=['checkout_email_sent'])
            logger.info(f"Check-out email sent successfully to {booking.email} for booking {booking.booking_id}")
        except Exception as e:
            logger.error(f"Failed to send check-out email for booking {booking.booking_id}: {str(e)}")

    return f"Processed {checkins.count()} check-ins and {checkouts.count()} check-outs."
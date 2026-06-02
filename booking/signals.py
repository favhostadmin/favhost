import os
from email.mime.image import MIMEImage
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.db import transaction
from django.contrib.staticfiles import finders
from .models import Enquiry

@receiver(post_save, sender=Enquiry)
def send_enquiry_notification_to_host(sender, instance, created, **kwargs):
    """Sends an email notification to the host when a new inquiry is created."""
    if created:
        # The host is the user who created the property associated with the inquiry
        host_email = instance.property.created_by.email
        subject = f"New Inquiry for {instance.property.title} from {instance.first_name}"
        
        context = {
            'enquiry': instance,
            'logo_url': 'cid:logo',
            'property_image_url': 'cid:property_image',
        }
        
        # Render the HTML template
        html_content = render_to_string('frontend/emails/guest_inquiry.html', context)
        # Create a plain-text version for email clients that don't support HTML
        text_content = strip_tags(html_content)
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[host_email],
        )
        email.attach_alternative(html_content, "text/html")
        email.mixed_subtype = 'related'  # Required for CID embedding

        # 1. Attach FavHost Logo
        logo_path = finders.find('img/login/favhost_new_logo.png')
        if logo_path and os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', '<logo>')
                email.attach(img)

        # 2. Attach Property Image
        prop_img_obj = instance.property.images.filter(is_primary=True).first() or \
                       instance.property.images.first()
        
        img_path = None
        if prop_img_obj and prop_img_obj.image:
            img_path = prop_img_obj.image.path
        
        # Fallback to placeholder if media file is missing
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
        
        # Use on_commit to ensure the email is only sent if the database transaction succeeds
        transaction.on_commit(lambda: email.send(fail_silently=False))
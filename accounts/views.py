import os
import random
import string
from email.mime.image import MIMEImage
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth import login as auth_login
from django.urls import reverse_lazy
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.staticfiles import finders
from .models import MyUser, UserDocument, CoHost
from .utils import get_effective_user


# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────
class CustomLoginView(LoginView):
    template_name = 'frontend/auth/login.html'
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Default to login mode; ?mode=signup shows signup view
        context['show_signup'] = self.request.GET.get('mode') == 'signup'
        return context

    def form_valid(self, form):
        self.request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        return super().form_valid(form)

    def get_success_url(self):
        next_url = self.request.GET.get('next') or self.request.POST.get('next')
        if next_url:
            return next_url
        return reverse_lazy('dashboard')

    def form_invalid(self, form):
        for error in form.non_field_errors():
            messages.error(self.request, error)
        return super().form_invalid(form)


# ─────────────────────────────────────────────
# SIGNUP / REGISTER
# ─────────────────────────────────────────────
def _generate_otp():
    return ''.join(random.choices(string.digits, k=4))


def _send_otp_email(email, first_name, otp, subject, template_name, is_forgot=False, is_resend=False):
    """Sends HTML email with inline attached logo."""
    try:
        html_body = render_to_string(template_name, {
            'first_name': first_name,
            'otp_code': otp,
            'logo_url': 'cid:logo',
        })
        
        new_prefix = "new " if is_resend else ""
        if is_forgot:
            plain_body = f'Dear {first_name},\n\nYour {new_prefix}password reset code is: {otp}\n\nThis code will expire in 15 minutes.\n\nBest regards,\nTeam Favhost\nsupport@favhost.com'
        else:
            plain_body = f'Dear {first_name},\n\nYour {new_prefix}FavHost verification code is: {otp}\n\nThis code will expire in 15 minutes.\n\nBest regards,\nTeam Favhost\nsupport@favhost.com'
            
        email_msg = EmailMultiAlternatives(
            subject=subject,
            body=plain_body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@favhost.com'),
            to=[email],
        )
        email_msg.attach_alternative(html_body, 'text/html')
        email_msg.mixed_subtype = 'related'
        
        # Attach logo inline
        logo_path = finders.find('img/login/favhost_new_logo.png')
        if logo_path and os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', '<logo>')
                email_msg.attach(img)
                
        email_msg.send(fail_silently=True)
    except Exception:
        pass


@require_http_methods(["GET", "POST"])
def register_view(request):
    """Handles signup form submission from login.html (signup panel)."""
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')

        errors = {}

        if not first_name:
            errors['first_name'] = 'First name is required.'
        if not last_name:
            errors['last_name'] = 'Last name is required.'
        if not email:
            errors['email'] = 'Email is required.'
        elif MyUser.objects.filter(email__iexact=email).exists():
            errors['email'] = 'An account with this email already exists.'
        elif MyUser.objects.filter(username__iexact=email).exists():
            errors['email'] = 'An account with this email already exists.'
        if not password1:
            errors['password1'] = 'Password is required.'
        elif len(password1) < 8:
            errors['password1'] = 'Password must be at least 8 characters.'
        elif password1 != password2:
            errors['password2'] = 'Passwords do not match.'

        if errors:
            for field, msg in errors.items():
                messages.error(request, msg)
            return render(request, 'frontend/auth/login.html', {
                'show_signup': True,
                'signup_data': {'first_name': first_name, 'last_name': last_name, 'email': email},
            })

        # Generate OTP and store in session
        otp = _generate_otp()
        request.session['signup_otp'] = otp
        request.session['signup_data'] = {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'password': password1,
        }

        # Send OTP email (HTML format matching email template)
        _send_otp_email(
            email=email,
            first_name=first_name,
            otp=otp,
            subject='Favhost verification code',
            template_name='frontend/emails/signup_otp.html'
        )

        return render(request, 'frontend/auth/login.html', {
            'show_signup': True,
            'show_otp_modal': True,
            'otp_email': email,
        })

    return redirect('login')


@require_http_methods(["GET", "POST"])
def verify_otp_view(request):
    """Verifies the OTP entered in the signup OTP modal."""
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code', '').strip()
        email = request.POST.get('email', '').strip()

        stored_otp = request.session.get('signup_otp')
        signup_data = request.session.get('signup_data', {})

        if not stored_otp or not signup_data:
            messages.error(request, 'Session expired. Please sign up again.')
            return redirect('login')

        if otp_code != stored_otp:
            messages.error(request, 'Invalid verification code. Please try again.')
            return render(request, 'frontend/auth/login.html', {
                'show_signup': True,
                'show_otp_modal': True,
                'otp_email': email,
            })

        # Create the user
        try:
            user = MyUser.objects.create_user(
                username=signup_data['email'],
                email=signup_data['email'],
                password=signup_data['password'],
            )
            user.first_name = signup_data.get('first_name', '')
            user.last_name = signup_data.get('last_name', '')
            user.save()

            # Clear session data
            del request.session['signup_otp']
            del request.session['signup_data']

            # Log user in
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            auth_login(request, user)
            messages.success(request, f'Welcome to FavHost, {user.first_name}!')
            return redirect('dashboard')

        except Exception as e:
            messages.error(request, 'Account creation failed. Please try again.')
            return redirect('login')

    return redirect('login')


@require_POST
def resend_otp_view(request):
    """Resends the signup OTP to the user's email (AJAX)."""
    email = request.POST.get('email', '').strip()
    signup_data = request.session.get('signup_data', {})

    if not signup_data or signup_data.get('email') != email:
        return JsonResponse({'success': False, 'error': 'Invalid session.'})

    otp = _generate_otp()
    request.session['signup_otp'] = otp

    signup_data_session = request.session.get('signup_data', {})
    fn = signup_data_session.get('first_name', 'User')
    _send_otp_email(
        email=email,
        first_name=fn,
        otp=otp,
        subject='Favhost verification code',
        template_name='frontend/emails/signup_otp.html',
        is_resend=True
    )

    return JsonResponse({'success': True})


# ─────────────────────────────────────────────
# FORGOT PASSWORD
# ─────────────────────────────────────────────
@require_http_methods(["GET", "POST"])
def forgot_password_view(request):
    """Multi-step forgot password: email → OTP → new password."""
    if request.method == 'GET':
        return render(request, 'frontend/auth/forgot_password.html', {'active_step': 'email'})

    step = request.POST.get('step', 'email')

    # ── STEP 1: Email ──────────────────────────────────
    if step == 'email':
        email = request.POST.get('email', '').strip()

        if not email:
            return render(request, 'frontend/auth/forgot_password.html', {
                'active_step': 'email',
                'email_error': 'Email is required.',
                'submitted_email': email,
            })

        # Always show success message to avoid email enumeration
        otp = _generate_otp()
        request.session['forgot_otp'] = otp
        request.session['forgot_email'] = email

        try:
            user = MyUser.objects.get(email=email)
            fn = user.first_name if user.first_name else user.email
            _send_otp_email(
                email=email,
                first_name=fn,
                otp=otp,
                subject='Reset password - Favhost',
                template_name='frontend/emails/forgot_password_otp.html',
                is_forgot=True
            )
        except MyUser.DoesNotExist:
            pass

        return render(request, 'frontend/auth/forgot_password.html', {
            'active_step': 'otp',
            'otp_email': email,
        })

    # ── STEP 2: Verify OTP ─────────────────────────────
    elif step == 'otp':
        email = request.POST.get('email', '').strip()
        otp_code = request.POST.get('otp_code', '').strip()
        stored_otp = request.session.get('forgot_otp')

        if not stored_otp or otp_code != stored_otp:
            return render(request, 'frontend/auth/forgot_password.html', {
                'active_step': 'otp',
                'otp_email': email,
                'otp_error': 'Invalid code. Please try again.',
            })

        # Mark OTP as verified in session
        request.session['forgot_otp_verified'] = True
        request.session['forgot_email'] = email

        return render(request, 'frontend/auth/forgot_password.html', {
            'active_step': 'reset',
            'otp_email': email,
            'verified_otp': otp_code,
        })

    # ── STEP 3: New Password ───────────────────────────
    elif step == 'reset':
        email = request.POST.get('email', '').strip()
        new_password1 = request.POST.get('new_password1', '')
        new_password2 = request.POST.get('new_password2', '')
        otp_code = request.POST.get('otp_code', '').strip()

        # Verify session token
        if not request.session.get('forgot_otp_verified') or request.session.get('forgot_email') != email:
            messages.error(request, 'Session expired. Please start over.')
            return redirect('forgot_password')

        if not new_password1 or len(new_password1) < 8:
            return render(request, 'frontend/auth/forgot_password.html', {
                'active_step': 'reset',
                'otp_email': email,
                'verified_otp': otp_code,
                'new_password_error': 'Password must be at least 8 characters.',
            })

        if new_password1 != new_password2:
            return render(request, 'frontend/auth/forgot_password.html', {
                'active_step': 'reset',
                'otp_email': email,
                'verified_otp': otp_code,
                'confirm_password_error': 'Passwords do not match.',
            })

        try:
            user = MyUser.objects.get(email=email)
            user.set_password(new_password1)
            user.save()

            # Clear session
            for key in ('forgot_otp', 'forgot_email', 'forgot_otp_verified'):
                request.session.pop(key, None)

            messages.success(request, 'Password reset successfully! Please log in.')
            return redirect('login')

        except MyUser.DoesNotExist:
            messages.error(request, 'No account found with this email.')
            return redirect('forgot_password')

    return redirect('forgot_password')


@require_POST
def forgot_resend_otp_view(request):
    """Resends the forgot-password OTP (AJAX)."""
    email = request.POST.get('email', '').strip()
    stored_email = request.session.get('forgot_email', '')

    if email != stored_email:
        return JsonResponse({'success': False, 'error': 'Session mismatch.'})

    otp = _generate_otp()
    request.session['forgot_otp'] = otp

    user = MyUser.objects.filter(email=email).first()
    fn = user.first_name if user and user.first_name else email
    _send_otp_email(
        email=email,
        first_name=fn,
        otp=otp,
        subject='Reset password - Favhost',
        template_name='frontend/emails/forgot_password_otp.html',
        is_forgot=True,
        is_resend=True
    )

    return JsonResponse({'success': True})


# ─────────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────────
@login_required
def profile_view(request):
    # Co-hosts do not have their own profile page
    if CoHost.objects.filter(co_host=request.user).exists():
        messages.error(request, 'Profile page is not available for co-hosts.')
        return redirect('dashboard')

    user = get_effective_user(request.user)
    permission_docs = user.documents.filter(doc_type='permission')
    govt_id_docs = user.documents.filter(doc_type='govt_id')

    now = timezone.now()
    trial_start = user.created_at
    trial_end = trial_start + timedelta(days=90)
    trial_days_left = (trial_end - now).days
    if trial_days_left < 0:
        trial_days_left = 0

    try:
        stripe_customer = user.stripe_customer
        subscription_status = stripe_customer.subscription_status
        is_premium = stripe_customer.is_active
    except Exception:
        stripe_customer = None
        subscription_status = ''
        is_premium = False

    # Fetch last payment info from Stripe for premium users
    last_payment_date = None
    last_payment_amount = None
    last_payment_currency = None
    next_payment_date = None  # fetched live from Stripe subscription
    next_payment_amount = None  # fetched live from Stripe subscription
    billing_interval = 'Monthly'  # default; updated from Stripe if available
    if is_premium and stripe_customer and stripe_customer.stripe_customer_id:
        try:
            import stripe as stripe_lib
            import datetime
            from django.conf import settings as django_settings
            stripe_lib.api_key = django_settings.STRIPE_SECRET_KEY

            _interval_map = {
                'month': 'Monthly',
                'year': 'Yearly',
                'week': 'Weekly',
                'day': 'Daily',
            }

            # ── Last payment: most recent invoice with an actual charge ──────
            # Don't filter by status='paid' — a brand-new invoice may still be
            # 'open' for a few seconds after resubscription while Stripe processes it.
            try:
                recent_invoices = stripe_lib.Invoice.list(
                    customer=stripe_customer.stripe_customer_id,
                    limit=5,
                ).data
                for inv in recent_invoices:
                    if (inv.amount_paid or 0) > 0:
                        last_payment_date = datetime.datetime.fromtimestamp(
                            inv.created, tz=datetime.timezone.utc
                        )
                        last_payment_amount = inv.amount_paid / 100
                        last_payment_currency = (getattr(inv, 'currency', 'usd') or 'usd').upper()
                        break
            except Exception:
                pass

            # ── Active subscription ───────────────────────────────────────────
            # Retrieve by stored ID first, but skip it if it's already cancelled
            # (happens after resubscription when the old ID is still in the DB).
            sub = None
            if stripe_customer.stripe_subscription_id:
                try:
                    fetched = stripe_lib.Subscription.retrieve(
                        stripe_customer.stripe_subscription_id,
                        expand=['items.data.price'],
                    )
                    if getattr(fetched, 'status', 'canceled') != 'canceled':
                        sub = fetched
                except Exception:
                    pass

            # Fallback: find the current active subscription for this customer
            if not sub:
                try:
                    subs = stripe_lib.Subscription.list(
                        customer=stripe_customer.stripe_customer_id,
                        status='active',
                        limit=1,
                        expand=['data.items.data.price'],
                    ).data
                    if subs:
                        sub = subs[0]
                        # Always sync the subscription ID so future loads are fast
                        if sub.id != stripe_customer.stripe_subscription_id:
                            stripe_customer.stripe_subscription_id = sub.id
                            stripe_customer.save(update_fields=['stripe_subscription_id'])
                except Exception:
                    pass

            if sub:
                # Billing interval
                try:
                    raw_interval = sub.items.data[0].price.recurring.interval
                    billing_interval = _interval_map.get(raw_interval, raw_interval.capitalize())
                except Exception:
                    pass

                # Next payment amount — from subscription price
                try:
                    unit_amount = sub.items.data[0].price.unit_amount
                    if unit_amount is not None:
                        next_payment_amount = unit_amount / 100
                except Exception:
                    pass

                # Next payment date — in flexible billing it's on items.data[0]
                try:
                    # Try top-level first (classic billing)
                    period_end_ts = getattr(sub, 'current_period_end', None)
                    # Fallback: flexible billing mode stores it on the subscription item
                    if not period_end_ts:
                        try:
                            period_end_ts = sub.items.data[0].current_period_end
                        except Exception:
                            pass
                    # Last fallback: billing_cycle_anchor (start of current cycle)
                    if not period_end_ts:
                        period_end_ts = getattr(sub, 'billing_cycle_anchor', None)
                    if period_end_ts:
                        next_payment_date = datetime.datetime.fromtimestamp(
                            period_end_ts, tz=datetime.timezone.utc
                        )
                        # Persist to DB if missing
                        if not stripe_customer.current_period_end:
                            stripe_customer.current_period_end = next_payment_date
                            stripe_customer.save(update_fields=['current_period_end'])
                except Exception:
                    pass
        except Exception:
            pass  # Silently fall back — Stripe unavailable

    context = {
        'user': user,
        'permission_docs': permission_docs,
        'govt_id_docs': govt_id_docs,
        'permission_count': permission_docs.count(),
        'govt_id_count': govt_id_docs.count(),
        'trial_start': trial_start,
        'trial_end': trial_end,
        'trial_days_left': trial_days_left,
        'stripe_customer': stripe_customer,
        'subscription_status': subscription_status,
        'is_premium': is_premium,
        'last_payment_date': last_payment_date,
        'last_payment_amount': last_payment_amount,
        'last_payment_currency': last_payment_currency,
        'next_payment_date': next_payment_date,
        'next_payment_amount': next_payment_amount,
        'billing_interval': billing_interval,
    }
    return render(request, 'frontend/auth/profile.html', context)


@login_required
def profile_edit_view(request):
    # Co-hosts do not have access to profile editing
    if CoHost.objects.filter(co_host=request.user).exists():
        messages.error(request, 'Profile editing is not available for co-hosts.')
        return redirect('dashboard')

    user = get_effective_user(request.user)
    if request.method == 'POST':
        # Retrieve text fields
        user.first_name = request.POST.get('first_name', '').strip()
        user.last_name = request.POST.get('last_name', '').strip()
        user.email = request.POST.get('email', '').strip()

        # Phone code + phone number
        phone_code = request.POST.get('phone_code', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        if phone_code and phone_number:
            if phone_number.startswith('+'):
                user.phone = phone_number
            else:
                user.phone = f"{phone_code} {phone_number}".strip()
        else:
            user.phone = phone_number or user.phone

        user.country = request.POST.get('country', '').strip()
        user.state = request.POST.get('state', '').strip()
        user.currency = request.POST.get('currency', 'USD').strip()
        user.language = request.POST.get('language', 'English').strip()
        user.about_me = request.POST.get('about_me', '').strip()

        # Social URLs
        user.instagram_url = request.POST.get('instagram_url', '').strip()
        user.facebook_url = request.POST.get('facebook_url', '').strip()
        user.twitter_url = request.POST.get('twitter_url', '').strip()
        user.youtube_url = request.POST.get('youtube_url', '').strip()
        user.linkedin_url = request.POST.get('linkedin_url', '').strip()
        user.whatsapp_number = request.POST.get('whatsapp_number', '').strip()

        # Handle Profile Picture
        if 'profile_picture' in request.FILES:
            user.profile_picture = request.FILES['profile_picture']

        user.save()

        # Handle Government ID Card
        if 'govt_id_document' in request.FILES:
            # Delete old government ID documents
            old_govt_ids = user.documents.filter(doc_type='govt_id')
            for doc in old_govt_ids:
                if doc.document:
                    doc.document.delete(save=False)
                doc.delete()
            # Save new one
            file_obj = request.FILES['govt_id_document']
            UserDocument.objects.create(
                user=user,
                document=file_obj,
                doc_type='govt_id',
                name=file_obj.name
            )

        # Handle Local Authority Permission Documents (multiple)
        if 'permission_documents' in request.FILES:
            files = request.FILES.getlist('permission_documents')
            for file_obj in files:
                UserDocument.objects.create(
                    user=user,
                    document=file_obj,
                    doc_type='permission',
                    name=file_obj.name
                )

        messages.success(request, 'Profile updated successfully!')
        return redirect('profile')

    permission_docs = user.documents.filter(doc_type='permission')
    govt_id_docs = user.documents.filter(doc_type='govt_id')

    # Parse phone number into code and number
    phone_code = '+1'
    phone_number = ''
    if user.phone:
        phone = user.phone.strip()
        if phone.startswith('+'):
            # Try space-separated: "+1 2248176919" → code "+1", number "2248176919"
            parts = phone.split(' ', 1)
            if len(parts) == 2:
                phone_code = parts[0]
                phone_number = parts[1]
            else:
                # No space: "+1(224)8176919" → try to separate code from rest
                import re
                m = re.match(r'^(\+\d{1,4})(.*)$', phone)
                if m:
                    phone_code = m.group(1)
                    phone_number = m.group(2)
                else:
                    phone_number = phone
        else:
            phone_number = phone

    context = {
        'user': user,
        'permission_docs': permission_docs,
        'govt_id_docs': govt_id_docs,
        'permission_count': permission_docs.count(),
        'govt_id_count': govt_id_docs.count(),
        'phone_code': phone_code,
        'phone_number': phone_number,
    }
    return render(request, 'frontend/auth/profile_edit.html', context)


@login_required
@require_http_methods(["POST", "DELETE"])
def delete_document_view(request, doc_id):
    user = get_effective_user(request.user)
    doc = get_object_or_404(UserDocument, id=doc_id, user=user)
    try:
        if doc.document:
            doc.document.delete(save=False)
        doc.delete()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


SOCIAL_FIELDS = {
    'instagram': 'instagram_url',
    'facebook': 'facebook_url',
    'youtube': 'youtube_url',
    'twitter': 'twitter_url',
    'linkedin': 'linkedin_url',
    'whatsapp': 'whatsapp_number',
}

@login_required
@require_POST
def update_social_url(request):
    platform = request.POST.get('platform', '').strip()
    url = request.POST.get('url', '').strip()
    field = SOCIAL_FIELDS.get(platform)
    if not field:
        return JsonResponse({'status': 'error', 'message': 'Invalid platform'}, status=400)
    user = get_effective_user(request.user)
    setattr(user, field, url)
    user.save(update_fields=[field])
    return JsonResponse({'status': 'success', 'platform': platform, 'url': url})


# ─────────────────────────────────────────────
# CO-HOST MANAGEMENT
# ─────────────────────────────────────────────
@login_required
def manage_cohost_view(request):
    """List, add, edit, and delete co-hosts for the host.

    If the current user is a co-host, all operations act on behalf
    of the host (get_effective_user). This gives every co-host the
    same management powers as the host.
    """
    effective_host = get_effective_user(request.user)

    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'add':
            email = request.POST.get('cohostEmail', '').strip().lower()
            password = request.POST.get('cohostPassword', '').strip()
            full_name = request.POST.get('cohostFullname', '').strip()
            phone = request.POST.get('cohostPhone', '').strip()
            name_parts = full_name.split(' ', 1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ''

            if not email or not password:
                messages.error(request, 'Email and password are required.')
                return redirect('manage_cohost')

            # Check if this email is already a co-host of this host
            if CoHost.objects.filter(host=effective_host, co_host__email__iexact=email).exists():
                messages.error(request, 'This email is already a co-host. Please use a different email.')
                return redirect('manage_cohost')

            co_host_user, created = MyUser.objects.get_or_create(
                email=email,
                defaults={
                    'username': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'phone': phone,
                    'is_active': True,
                }
            )
            co_host_user.set_password(password)
            co_host_user.first_name = first_name
            co_host_user.last_name = last_name
            co_host_user.phone = phone
            co_host_user.is_active = True
            co_host_user.save()

            CoHost.objects.get_or_create(
                host=effective_host,
                co_host=co_host_user,
                defaults={'display_password': password}
            )
            if not created:
                CoHost.objects.filter(host=effective_host, co_host=co_host_user).update(display_password=password)

            messages.success(request, f'Co-host {email} added successfully.')
            return redirect('manage_cohost')

        elif action == 'edit':
            cohost_id = request.POST.get('cohost_id', '').strip()
            email = request.POST.get('cohostEmail', '').strip().lower()
            password = request.POST.get('cohostPassword', '').strip()
            full_name = request.POST.get('cohostFullname', '').strip()
            phone = request.POST.get('cohostPhone', '').strip()

            cohost_rel = get_object_or_404(CoHost, id=cohost_id, host=effective_host)
            co_host_user = cohost_rel.co_host

            name_parts = full_name.split(' ', 1)
            co_host_user.first_name = name_parts[0]
            co_host_user.last_name = name_parts[1] if len(name_parts) > 1 else ''
            co_host_user.phone = phone
            if email:
                co_host_user.email = email
                co_host_user.username = email
            if password:
                co_host_user.set_password(password)
                cohost_rel.display_password = password
            co_host_user.save()
            cohost_rel.save()

            messages.success(request, 'Co-host updated successfully.')
            return redirect('manage_cohost')

        elif action == 'delete':
            cohost_id = request.POST.get('cohost_id', '').strip()
            cohost_rel = get_object_or_404(CoHost, id=cohost_id, host=effective_host)
            co_host_user = cohost_rel.co_host
            email = co_host_user.email
            cohost_rel.delete()
            co_host_user.delete()
            messages.success(request, f'Co-host {email} removed and account deleted.')
            return redirect('manage_cohost')

    cohosts = CoHost.objects.filter(host=effective_host).select_related('co_host')
    cohost_limit_reached = cohosts.count() >= 5
    context = {
        'cohosts': cohosts,
        'current_user': request.user,
        'cohost_limit_reached': cohost_limit_reached,
    }
    return render(request, 'frontend/auth/manage_co-host.html', context)


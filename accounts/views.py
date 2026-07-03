import os
import json
import random
import string
import logging
from email.mime.image import MIMEImage
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth import login as auth_login
from django.urls import reverse_lazy, reverse
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.staticfiles import finders
from .models import MyUser, UserDocument, CoHost
from .utils import get_effective_user

logger = logging.getLogger(__name__)

# Firebase Admin SDK (lazy-initialized)
_firebase_app = None

def _get_firebase_app():
    """Initialize and return the Firebase Admin app (lazy, singleton)."""
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    private_key = settings.FIREBASE_ADMIN_PRIVATE_KEY
    client_email = settings.FIREBASE_ADMIN_CLIENT_EMAIL
    project_id = settings.FIREBASE_PROJECT_ID

    if not all([private_key, client_email, project_id]):
        return None

    import firebase_admin
    from firebase_admin import credentials
    cred = credentials.Certificate({
        "type": "service_account",
        "project_id": project_id,
        "private_key": private_key.replace('\\n', '\n'),
        "client_email": client_email,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    })
    _firebase_app = firebase_admin.initialize_app(cred)
    return _firebase_app


@csrf_exempt
@require_POST
def firebase_auth_view(request):
    """
    Receive a Firebase ID token from the frontend, verify it,
    then log in or create the user.
    """
    try:
        app = _get_firebase_app()
        if not app:
            return JsonResponse({'error': 'Firebase not configured on server. Add credentials to .env'}, status=501)

        data = json.loads(request.body)
        id_token = data.get('idToken')
        if not id_token:
            return JsonResponse({'error': 'Missing idToken'}, status=400)

        from firebase_admin import auth as firebase_auth
        decoded = firebase_auth.verify_id_token(id_token)
    except Exception as e:
        return JsonResponse({'error': f'Token verification failed: {e}'}, status=403)

    firebase_uid = decoded.get('uid', '')
    email = decoded.get('email', '')
    name = decoded.get('name', '') or decoded.get('display_name', '')

    if not email:
        return JsonResponse({'error': 'No email from Google account'}, status=400)

    parts = name.split(' ', 1)
    first_name = parts[0] if parts else ''
    last_name = parts[1] if len(parts) > 1 else ''

    user = MyUser.objects.filter(email=email).first()
    if not user:
        user = MyUser.objects.create_user(
            username=email,
            email=email,
        )
        user.first_name = first_name
        user.last_name = last_name
        user.is_active = True
        user.save()

        # First-time Google sign-up — send the welcome email
        _send_welcome_email(
            email=user.email,
            first_name=user.first_name or 'there',
            request=request,
        )

    user.backend = 'accounts.backends.EmailOrUsernameBackend'
    auth_login(request, user)

    return JsonResponse({'success': True, 'redirect': str(reverse_lazy('frontdesk:index'))})


@csrf_exempt
@require_POST
def google_auth_view(request):
    """
    Receive a Google Identity Services ID token (the `credential` returned by the
    GIS button) and verify it directly with Google, then log in or create the user.

    This replaces the Firebase popup/redirect flow for "Continue with Google",
    which fails on iOS ("missing initial state") because WebKit partitions the
    third-party sessionStorage Firebase needs across the firebaseapp.com redirect.
    GIS returns the ID token straight to a JS callback — no cross-domain storage.
    """
    client_id = getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')
    if not client_id:
        return JsonResponse({'error': 'Google sign-in is not configured on the server.'}, status=501)

    try:
        data = json.loads(request.body)
        credential = data.get('credential')
        if not credential:
            return JsonResponse({'error': 'Missing credential'}, status=400)

        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests
        # Verifies signature, expiry, issuer and that the audience == our client_id.
        info = google_id_token.verify_oauth2_token(
            credential, google_requests.Request(), client_id
        )
    except Exception as e:
        return JsonResponse({'error': f'Token verification failed: {e}'}, status=403)

    email = (info.get('email') or '').strip()
    if not email or not info.get('email_verified', False):
        return JsonResponse({'error': 'No verified email from Google account'}, status=400)

    first_name = info.get('given_name', '')
    last_name = info.get('family_name', '')
    if not first_name and info.get('name'):
        parts = info['name'].split(' ', 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ''

    user = MyUser.objects.filter(email__iexact=email).first()
    if not user:
        user = MyUser.objects.create_user(username=email, email=email)
        user.first_name = first_name
        user.last_name = last_name
        user.is_active = True
        user.save()

        # First-time Google sign-up — send the welcome email
        _send_welcome_email(
            email=user.email,
            first_name=user.first_name or 'there',
            request=request,
        )

    user.backend = 'accounts.backends.EmailOrUsernameBackend'
    auth_login(request, user)

    return JsonResponse({'success': True, 'redirect': str(reverse_lazy('frontdesk:index'))})


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
        # Pass Firebase config to template for Google sign-in
        context['firebase_api_key'] = settings.FIREBASE_API_KEY
        context['firebase_auth_domain'] = settings.FIREBASE_AUTH_DOMAIN
        context['firebase_project_id'] = settings.FIREBASE_PROJECT_ID
        context['firebase_storage_bucket'] = settings.FIREBASE_STORAGE_BUCKET
        context['firebase_messaging_sender_id'] = settings.FIREBASE_MESSAGING_SENDER_ID
        context['firebase_app_id'] = settings.FIREBASE_APP_ID
        context['firebase_measurement_id'] = settings.FIREBASE_MEASUREMENT_ID
        context['firebase_configured'] = bool(settings.FIREBASE_API_KEY)
        # Google Identity Services (preferred for "Continue with Google")
        context['google_client_id'] = settings.GOOGLE_OAUTH_CLIENT_ID
        context['google_configured'] = bool(settings.GOOGLE_OAUTH_CLIENT_ID)
        return context

    def form_valid(self, form):
        self.request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        return super().form_valid(form)

    def get_success_url(self):
        next_url = self.request.GET.get('next') or self.request.POST.get('next')
        if next_url:
            return next_url
        return reverse_lazy('frontdesk:index')

    def form_invalid(self, form):
        for error in form.non_field_errors():
            messages.error(self.request, error)
        return super().form_invalid(form)


# ─────────────────────────────────────────────
# SIGNUP / REGISTER
# ─────────────────────────────────────────────
def _generate_otp():
    return ''.join(random.choices(string.digits, k=4))


# OTP security: codes expire and allow only a few verification attempts.
OTP_EXPIRY_SECONDS = 15 * 60   # matches the "expires in 15 minutes" copy in emails/UI
OTP_MAX_ATTEMPTS = 5           # wrong guesses allowed before a new code is required


def _store_otp(request, key, otp):
    """Save an OTP in the session with a fresh timestamp and a zeroed attempt counter."""
    request.session[key] = otp
    request.session[f'{key}_created'] = timezone.now().timestamp()
    request.session[f'{key}_attempts'] = 0


def _clear_otp(request, key):
    """Remove an OTP and its expiry/attempt metadata from the session."""
    for suffix in ('', '_created', '_attempts'):
        request.session.pop(f'{key}{suffix}', None)


def _check_otp(request, key, submitted):
    """
    Validate a submitted OTP against the session.

    Returns (ok, error_message). A wrong-but-still-valid code increments the
    attempt counter; an expired or exhausted code is cleared so the user must
    request a new one. error_message is None when ok is True.
    """
    stored = request.session.get(key)
    created = request.session.get(f'{key}_created')

    if not stored or not created:
        return False, 'Your code has expired. Please request a new one.'

    # Expiry check
    if (timezone.now().timestamp() - created) > OTP_EXPIRY_SECONDS:
        _clear_otp(request, key)
        return False, 'Your code has expired. Please request a new one.'

    # Attempt-limit check (before comparing, in case a prior request hit the cap)
    attempts = request.session.get(f'{key}_attempts', 0)
    if attempts >= OTP_MAX_ATTEMPTS:
        _clear_otp(request, key)
        return False, 'Too many incorrect attempts. Please request a new code.'

    # Value check
    if submitted != stored:
        attempts += 1
        request.session[f'{key}_attempts'] = attempts
        remaining = OTP_MAX_ATTEMPTS - attempts
        if remaining <= 0:
            _clear_otp(request, key)
            return False, 'Too many incorrect attempts. Please request a new code.'
        plural = '' if remaining == 1 else 's'
        return False, f'Invalid code. {remaining} attempt{plural} remaining.'

    return True, None


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
            reply_to=[getattr(settings, 'SUPPORT_EMAIL', 'support@favhost.com')],
        )
        email_msg.attach_alternative(html_body, 'text/html')
        email_msg.mixed_subtype = 'related'

        # Attach logo inline
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
    except Exception:
        logger.exception("Failed to send OTP email to %s", email)


def _send_welcome_email(email, first_name, request=None):
    """Sends the HTML welcome email (with inline logo) to a newly signed-up user."""
    try:
        # Build absolute URLs so the buttons work from inside the email client.
        if request is not None:
            dashboard_url = request.build_absolute_uri(reverse('dashboard'))
            pricing_url = request.build_absolute_uri(reverse('billing:pricing'))
            terms_url = request.build_absolute_uri(reverse('terms'))
            privacy_url = request.build_absolute_uri(reverse('privacy'))
            contact_url = request.build_absolute_uri(reverse('contact'))
        else:
            dashboard_url = 'https://favhost.com/dashboard/'
            pricing_url = 'https://favhost.com/upgrade/'
            terms_url = 'https://favhost.com/terms/'
            privacy_url = 'https://favhost.com/privacy-policy/'
            contact_url = 'https://favhost.com/contact/'

        tutorials_url = getattr(settings, 'TUTORIALS_URL', 'https://www.youtube.com/@YOUR_CHANNEL')

        html_body = render_to_string('frontend/emails/welcome.html', {
            'first_name': first_name,
            'logo_url': 'cid:logo',
            'dashboard_url': dashboard_url,
            'pricing_url': pricing_url,
            'terms_url': terms_url,
            'privacy_url': privacy_url,
            'contact_url': contact_url,
            'tutorials_url': tutorials_url,
        })

        plain_body = (
            f'Dear {first_name},\n\n'
            'Welcome to Favhost! Your account is ready.\n\n'
            'Your 90-day free trial has started — every feature is unlocked from day one '
            'with no limits. After the trial ends, simply subscribe to keep your full access '
            'and continue without interruption.\n\n'
            f'Go to your dashboard: {dashboard_url}\n'
            f'Watch our video tutorials: {tutorials_url}\n'
            f'View our plans: {pricing_url}\n\n'
            'Need help getting started? Reach us anytime at support@favhost.com\n\n'
            'Best regards,\nTeam Favhost\nsupport@favhost.com'
        )

        support_email = getattr(settings, 'SUPPORT_EMAIL', 'support@favhost.com')
        email_msg = EmailMultiAlternatives(
            subject='Welcome to Favhost',
            body=plain_body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@favhost.com'),
            to=[email],
            reply_to=[support_email],
            headers={'List-Unsubscribe': f'<mailto:{support_email}?subject=Unsubscribe>'},
        )
        email_msg.attach_alternative(html_body, 'text/html')
        email_msg.mixed_subtype = 'related'

        # Attach logo inline (same asset used by the OTP emails)
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
    except Exception:
        logger.exception("Failed to send welcome email to %s", email)


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
        _store_otp(request, 'signup_otp', otp)
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

        signup_data = request.session.get('signup_data', {})

        if not request.session.get('signup_otp') or not signup_data:
            messages.error(request, 'Session expired. Please sign up again.')
            return redirect('login')

        ok, otp_error = _check_otp(request, 'signup_otp', otp_code)
        if not ok:
            messages.error(request, otp_error)
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
            _clear_otp(request, 'signup_otp')
            del request.session['signup_data']

            # Send the welcome email to the freshly created user
            _send_welcome_email(
                email=user.email,
                first_name=user.first_name or 'there',
                request=request,
            )

            # Log user in
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            auth_login(request, user)
            messages.success(request, f'Welcome to FavHost, {user.first_name}!')
            return redirect('frontdesk:index')

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
    _store_otp(request, 'signup_otp', otp)

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
        _store_otp(request, 'forgot_otp', otp)
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

        ok, otp_error = _check_otp(request, 'forgot_otp', otp_code)
        if not ok:
            return render(request, 'frontend/auth/forgot_password.html', {
                'active_step': 'otp',
                'otp_email': email,
                'otp_error': otp_error,
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
            _clear_otp(request, 'forgot_otp')
            for key in ('forgot_email', 'forgot_otp_verified'):
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
    _store_otp(request, 'forgot_otp', otp)

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

    # Free-access users skip all subscription requirements
    if user.is_subscription_free:
        is_premium = True

    # Fetch last payment info from Stripe for premium users
    last_payment_date = None
    last_payment_amount = None
    last_payment_currency = None
    next_payment_date = None  # fetched live from Stripe subscription
    next_payment_amount = None  # fetched live from Stripe subscription
    billing_interval = 'Monthly'  # default; updated from Stripe if available
    subscription_cancelled = False  # True when they subscribed before but have no active sub now
    if stripe_customer and stripe_customer.stripe_customer_id:
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
                # Live Stripe confirms an active subscription — heal the DB status.
                is_premium = True
                if stripe_customer.subscription_status != 'active':
                    stripe_customer.subscription_status = 'active'
                    stripe_customer.save(update_fields=['subscription_status'])
                    subscription_status = 'active'

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

                # ── Last payment fallback ─────────────────────────────────────
                # If no paid invoice was found above, derive the last payment from
                # the active subscription's current period start (when the current
                # billing cycle — i.e. the most recent charge — began).
                if not last_payment_date:
                    try:
                        period_start_ts = getattr(sub, 'current_period_start', None)
                        if not period_start_ts:
                            try:
                                period_start_ts = sub.items.data[0].current_period_start
                            except Exception:
                                pass
                        if not period_start_ts:
                            period_start_ts = getattr(sub, 'billing_cycle_anchor', None)
                        if period_start_ts:
                            last_payment_date = datetime.datetime.fromtimestamp(
                                period_start_ts, tz=datetime.timezone.utc
                            )
                            if last_payment_amount is None and next_payment_amount is not None:
                                last_payment_amount = next_payment_amount
                                last_payment_currency = last_payment_currency or 'USD'
                    except Exception:
                        pass

            elif not user.is_subscription_free and (
                stripe_customer.stripe_subscription_id
                or subscription_status in ('active', 'canceled', 'past_due')
            ):
                # They had a subscription but Stripe shows none active → cancelled.
                # Fall back to trial access for any remaining trial days.
                subscription_cancelled = True
                is_premium = False
                if stripe_customer.subscription_status != 'canceled':
                    stripe_customer.subscription_status = 'canceled'
                    stripe_customer.save(update_fields=['subscription_status'])
                subscription_status = 'canceled'
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
        'subscription_cancelled': subscription_cancelled,
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

            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, 'Please enter a valid email address.')
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
                try:
                    validate_email(email)
                except ValidationError:
                    messages.error(request, 'Please enter a valid email address.')
                    return redirect('manage_cohost')

            if email and email != (co_host_user.email or '').lower():
                # Don't collide with another account's email/username (unique).
                if MyUser.objects.exclude(pk=co_host_user.pk).filter(
                    Q(email__iexact=email) | Q(username__iexact=email)
                ).exists():
                    messages.error(request, 'That email is already in use by another account. Please choose a different email.')
                    return redirect('manage_cohost')
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


import random
import string
from django.shortcuts import render, redirect
from django.contrib.auth.views import LoginView
from django.contrib.auth import login as auth_login
from django.urls import reverse_lazy
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.mail import send_mail
from django.views.decorators.http import require_POST, require_http_methods
from .models import MyUser


# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────
class CustomLoginView(LoginView):
    template_name = 'frontend/auth/login.html'
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Default to login mode
        context['show_signup'] = False
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


@require_http_methods(["GET", "POST"])
def register_view(request):
    """Handles signup form submission from login.html (signup panel)."""
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')

        errors = {}

        if not first_name:
            errors['first_name'] = 'First name is required.'
        if not last_name:
            errors['last_name'] = 'Last name is required.'
        if not email:
            errors['email'] = 'Email is required.'
        elif MyUser.objects.filter(email=email).exists():
            errors['email'] = 'An account with this email already exists.'
        elif MyUser.objects.filter(username=email).exists():
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

        # Send OTP email
        try:
            send_mail(
                subject='FavHost - Verify Your Account',
                message=f'Your verification code is: {otp}\n\nThis code will expire in 15 minutes.',
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@favhost.com'),
                recipient_list=[email],
                fail_silently=True,
            )
        except Exception:
            pass

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

    try:
        send_mail(
            subject='FavHost - Verify Your Account (Resend)',
            message=f'Your new verification code is: {otp}\n\nThis code will expire in 15 minutes.',
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@favhost.com'),
            recipient_list=[email],
            fail_silently=True,
        )
    except Exception:
        pass

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
            send_mail(
                subject='FavHost - Reset Your Password',
                message=f'Your password reset code is: {otp}\n\nThis code will expire in 15 minutes.',
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@favhost.com'),
                recipient_list=[email],
                fail_silently=True,
            )
        except MyUser.DoesNotExist:
            pass
        except Exception:
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

    try:
        send_mail(
            subject='FavHost - Reset Your Password (Resend)',
            message=f'Your new password reset code is: {otp}\n\nThis code will expire in 15 minutes.',
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@favhost.com'),
            recipient_list=[email],
            fail_silently=True,
        )
    except Exception:
        pass

    return JsonResponse({'success': True})


# ─────────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────────
@login_required
def profile_view(request):
    return render(request, 'frontend/auth/profile.html', {'user': request.user})

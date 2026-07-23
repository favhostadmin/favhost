"""Access control for the hidden platform-owner console.

The console is locked to exactly ONE predefined account
(``settings.PLATFORM_ADMIN_EMAIL``). Being ``is_staff`` / ``is_admin`` in the
main app is NOT enough — only that single email may enter. This keeps the
owner console separate from Django's own ``/admin/`` and from any host who
happens to have staff flags.
"""
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse


def admin_email():
    return (getattr(settings, 'PLATFORM_ADMIN_EMAIL', '') or '').strip().lower()


def is_platform_admin(user):
    """True only for the single predefined owner account (and only if active)."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    email = (getattr(user, 'email', '') or '').strip().lower()
    return bool(email) and email == admin_email()


def get_platform_admin():
    """Return the owner account row, or None if it doesn't exist yet."""
    User = get_user_model()
    return User.objects.filter(email__iexact=admin_email()).first()


def admin_required(view_func):
    """Gate a console view to the platform owner.

    - Anonymous visitors are sent to the console login page.
    - A logged-in NON-owner (e.g. an ordinary host) gets a plain 404 so the
      console's existence is never confirmed to them.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            login_url = reverse('controlpanel:login')
            return redirect(f'{login_url}?next={request.path}')
        if not is_platform_admin(user):
            raise Http404()
        return view_func(request, *args, **kwargs)
    return _wrapped

"""Access control for the hidden platform-owner console.

Two kinds of account may enter the console:

``owner``
    The single predefined account (``settings.PLATFORM_ADMIN_EMAIL``). It is the
    immutable root of the console — it cannot be revoked, blocked or deleted
    from the UI, and it always exists independently of any database row.

``co-admin``
    A delegate the owner (or another co-admin) creates from
    ``/console/co-admins/``, stored as an ``accounts.CoAdmin`` row. This mirrors
    the host-side co-host relationship one level up: a dependent sub-account
    that the creator can revoke at any moment, at which point the underlying
    user row is deleted and the email is free to sign up as a normal host.

Being ``is_staff`` / ``is_admin`` in the main app is still NOT enough — only the
owner and current co-admins may enter. This keeps the console separate from
Django's own ``/admin/`` and from any host who happens to have staff flags.

The owner can reach everything. A co-admin reaches only the sections granted to
them (``CoAdmin.permissions``, keys defined in ``controlpanel.permissions``) —
so someone hired for SEO can be given Properties alone and sees nothing else.
Two sections are never grantable and stay owner-only: ``co_admins`` (whoever can
appoint co-admins could otherwise grant themselves everything) and ``settings``
(platform pricing).

Enforcement lives in the ``section_required`` / ``owner_required`` decorators on
every view. The sidebar hides links a viewer cannot use, but that is cosmetic —
typing the URL directly hits the same check and 404s.
"""
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

from .permissions import GRANTABLE, SECTION_URLS


def admin_email():
    return (getattr(settings, 'PLATFORM_ADMIN_EMAIL', '') or '').strip().lower()


def is_console_owner(user):
    """True only for the single predefined owner account (and only if active)."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    email = (getattr(user, 'email', '') or '').strip().lower()
    return bool(email) and email == admin_email()


def is_co_admin(user):
    """True for an active account that currently holds a ``CoAdmin`` row.

    The row is the whole grant: revoking it (or deleting the account) removes
    console access immediately, on the very next request.
    """
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if is_console_owner(user):
        return False
    from accounts.models import CoAdmin
    return CoAdmin.objects.filter(user_id=user.pk).exists()


def is_platform_admin(user):
    """True for anyone allowed into the console: the owner or a live co-admin."""
    return is_console_owner(user) or is_co_admin(user)


def console_role(user):
    """``'owner'``, ``'coadmin'`` or ``None`` — for badges and role-aware UI."""
    if is_console_owner(user):
        return 'owner'
    if is_co_admin(user):
        return 'coadmin'
    return None


def allowed_sections(user):
    """Section keys this viewer may open.

    Owner → every grantable section. Co-admin → their stored grants, filtered
    through ``GRANTABLE`` so a key that was removed from the registry (or was
    never legitimate) can never widen access. Anyone else → nothing.
    """
    if is_console_owner(user):
        return set(GRANTABLE)
    if not is_co_admin(user):
        return set()
    from accounts.models import CoAdmin
    rel = CoAdmin.objects.filter(user_id=user.pk).only('permissions').first()
    stored = (rel.permissions if rel and isinstance(rel.permissions, list) else [])
    return {key for key in stored if key in GRANTABLE}


def has_section(user, section):
    """True if ``user`` may open ``section``.

    Owner-only sections are not in ``GRANTABLE``, so they resolve to False for
    every co-admin without needing a special case here.
    """
    return section in allowed_sections(user)


def console_home_url(user):
    """First page this viewer can actually open.

    A co-admin granted only Payments must not be dropped on the dashboard and
    shown a 404 the moment they log in.
    """
    allowed = allowed_sections(user)
    for key, url_name in SECTION_URLS.items():
        if key in allowed:
            return reverse(url_name)
    # Granted nothing yet — the owner still needs somewhere to land them.
    return reverse('controlpanel:no_access')


def co_admin_user_ids():
    """PKs of every current co-admin, for excluding them from host listings."""
    from accounts.models import CoAdmin
    return set(CoAdmin.objects.values_list('user_id', flat=True))


def get_platform_admin():
    """Return the owner account row, or None if it doesn't exist yet."""
    User = get_user_model()
    return User.objects.filter(email__iexact=admin_email()).first()


def admin_required(view_func):
    """Gate a console view to the owner or a current co-admin.

    - Anonymous visitors are sent to the console login page.
    - A logged-in NON-member (e.g. an ordinary host, or someone whose co-admin
      role was just revoked) gets a plain 404 so the console's existence is
      never confirmed to them.
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


def section_required(section):
    """Gate a console view to holders of one section grant.

    This is the real permission boundary — the hidden nav link is only a
    courtesy. A co-admin who types ``/console/payments/`` without the grant
    gets the same 404 as a stranger, which also avoids confirming that the
    section exists.
    """
    def _decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                login_url = reverse('controlpanel:login')
                return redirect(f'{login_url}?next={request.path}')
            if not is_platform_admin(user) or not has_section(user, section):
                raise Http404()
            return view_func(request, *args, **kwargs)
        return _wrapped
    return _decorator


def owner_required(view_func):
    """Gate a console view to the owner alone.

    Used by the two never-grantable sections: Platform Settings and the
    Co-admins page itself.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            login_url = reverse('controlpanel:login')
            return redirect(f'{login_url}?next={request.path}')
        if not is_console_owner(user):
            raise Http404()
        return view_func(request, *args, **kwargs)
    return _wrapped

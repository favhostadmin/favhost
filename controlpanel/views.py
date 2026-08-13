"""Views for the hidden platform-owner console (mounted at /console/).

Security model
--------------
Every view except the login page carries one of three gates (see
``controlpanel.access``):

``@section_required('<key>')``
    The data sections. The owner holds them all; a co-admin holds only what was
    granted on the Co-admins page, so an ungranted section 404s even if the URL
    is typed directly.
``@owner_required``
    Platform Settings and the Co-admins page — never grantable.
``@admin_required``
    Any console member, used for role-neutral pages (logout, no-access).

Host business data (listings, bookings, prices) is presented read-only — the
console oversees and manages *accounts*, but never edits a host's own data. The
mutating actions are strictly account-level: block/unblock, comp free access,
adjust trial length, delete account, edit platform pricing, and appoint/revoke
co-admins.
"""
import json
import uuid
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from accounts.models import MyUser, CoHost, CoAdmin
from property.models import Property
from booking.models import Booking, Payment, Enquiry
from billing.models import StripeCustomer, PlatformSetting

from . import analytics, geo
from .access import (
    admin_required, owner_required, section_required, is_platform_admin,
    admin_email, console_home_url,
)
from .permissions import SECTIONS, SECTION_LABELS, clean_permissions

BACKEND = 'accounts.backends.EmailOrUsernameBackend'


# ── auth ────────────────────────────────────────────────────────────────────

@never_cache
def login_view(request):
    """Console login. Only the owner account and live co-admins are accepted.

    A co-admin whose role has just been revoked fails here exactly like any
    stranger — the ``CoAdmin`` row is the entire grant, so removing it locks
    them out on the next attempt (and their account is deleted with it).

    ``never_cache`` stops the browser (or bfcache/back-button) from re-serving a
    stale copy of this page, so the form always carries a CSRF token matching the
    current cookie — avoiding spurious 403s after logging in on another tab.
    """
    if is_platform_admin(request.user):
        return redirect(console_home_url(request.user))

    next_url = request.GET.get('next') or request.POST.get('next') or ''
    if request.method == 'POST':
        identifier = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        user = authenticate(request, username=identifier, password=password)
        if user is not None and is_platform_admin(user):
            auth_login(request, user, backend=BACKEND)
            request.session.set_expiry(settings.SESSION_COOKIE_AGE)
            if next_url and next_url.startswith('/console'):
                return redirect(next_url)
            # Land on the first section they hold — a co-admin granted only
            # Payments must not be dropped on a dashboard they cannot open.
            return redirect(console_home_url(user))
        # Deliberately generic — never reveal whether the email exists or that
        # this is the owner-only gate.
        messages.error(request, 'Invalid credentials or insufficient access.')

    return render(request, 'controlpanel/login.html', {'next': next_url})


@admin_required
def logout_view(request):
    auth_logout(request)
    return redirect('controlpanel:login')


@admin_required
def no_access(request):
    """Landing page for a co-admin who holds no section grants yet.

    Without this they would log in successfully and immediately hit a 404,
    which reads as "the console is broken" rather than "you have not been given
    anything yet".
    """
    return render(request, 'controlpanel/no_access.html', {'owner_email': admin_email()})


# ── dashboard ────────────────────────────────────────────────────────────────

def _parse_day(value):
    try:
        return datetime.strptime((value or '').strip(), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


@admin_required
@section_required('dashboard')
def dashboard(request):
    """The owner overview.

    The window is given one of two ways: a preset (?range=7|28|90) or exact
    dates (?from=&to=). Anything unparseable silently falls back to the 28-day
    preset rather than erroring — a bad URL should never leave the owner
    staring at a stack trace.
    """
    start = _parse_day(request.GET.get('from'))
    end = _parse_day(request.GET.get('to'))
    if not (start and end):
        start = end = None

    try:
        days = int(request.GET.get('range') or 28)
    except (TypeError, ValueError):
        days = 28

    ctx = analytics.dashboard_context()
    ctx['traffic'] = analytics.traffic_context(days, start=start, end=end)
    ctx['today'] = timezone.localdate()
    ctx['traffic_json'] = json.dumps({
        'labels': ctx['traffic']['labels'],
        'prevLabels': ctx['traffic']['prev_labels'],
        'metrics': ctx['traffic']['metrics'],
        'days': ctx['traffic']['days'],
    })
    ctx['active_nav'] = 'dashboard'
    return render(request, 'controlpanel/dashboard.html', ctx)


# ── users / hosts ────────────────────────────────────────────────────────────

def _paginate(request, qs, per_page=25):
    paginator = Paginator(qs, per_page)
    return paginator.get_page(request.GET.get('page'))


# How the list may be ordered. Anything not in here falls back to 'recent', so
# a hand-edited ?sort= can never blow up the page or leak an arbitrary field
# into order_by().
USER_SORTS = {
    'recent':   ('-created_at', 'Newest first'),
    'oldest':   ('created_at', 'Oldest first'),
    'name':     ('first_name', 'Name A–Z'),
    'listings': ('-n_props', 'Most listings'),
    'active':   ('-last_login', 'Recently active'),
}


def _country_groups(rows):
    """Split already-country-ordered rows into one block per country.

    Built from the rows of the *current page* so that a header can never
    promise hosts that are actually on the next page. A country whose hosts
    straddle a page boundary simply gets its header again on the next page.
    """
    groups = []
    for r in rows:
        # Group on the stored value, not the display name — comparing the
        # rendered label instead put every country-less host in a block of
        # its own, since '' never equals 'No country set'.
        key = (r['location']['country'] or '').lower()
        if not groups or groups[-1]['key'] != key:
            groups.append({
                'key': key,
                'name': r['location']['country'] or 'No country set',
                'code': r['location']['code'],
                'unknown': not key,
                'rows': [],
            })
        groups[-1]['rows'].append(r)
    return groups


@section_required('users')
def users_list(request):
    q = (request.GET.get('q') or '').strip()
    status = request.GET.get('status') or ''
    sub = request.GET.get('sub') or ''
    attention = request.GET.get('attention') or ''
    country = (request.GET.get('country') or '').strip()
    sort = request.GET.get('sort') if request.GET.get('sort') in USER_SORTS else 'recent'
    grouped = request.GET.get('group', 'country') != 'none'

    base = analytics.hosts_queryset()
    qs = base.annotate(
        n_props=Count('properties_created', distinct=True),
        n_cohosts=Count('host_cohosts', distinct=True),
    ).order_by(USER_SORTS[sort][0])

    if q:
        qs = qs.filter(
            Q(username__icontains=q) | Q(email__icontains=q) |
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(phone__icontains=q) | Q(country__icontains=q) | Q(city__icontains=q)
        )
    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'blocked':
        qs = qs.filter(is_active=False)
    if country:
        qs = qs.filter(country__iexact=country)

    smap = analytics.stripe_map()
    now = timezone.now()
    dormant_cutoff = now - timedelta(days=45)

    rows = []
    for u in qs:
        state = analytics.classify_subscription(u, smap.get(u.id), now)
        if sub and state != sub:
            continue
        # Lightweight risk signals shared with the dashboard attention queue.
        end = analytics.trial_end_for(u)
        trial_soon = state == 'trialing' and end and 0 <= (end.date() - now.date()).days <= 7
        dormant = u.is_active and (u.last_login is None or u.last_login < dormant_cutoff)
        needs_attention = bool(
            not u.is_active or state in ('past_due', 'expired') or trial_soon
            or u.n_props == 0 or dormant
        )
        if attention and not needs_attention:
            continue
        rows.append({
            'user': u,
            'sub_state': state,
            'sub_label': analytics.SUBSCRIPTION_LABELS.get(state, state),
            'n_props': u.n_props,
            'n_cohosts': u.n_cohosts,
            'last_login': u.last_login,
            'dormant': dormant,
            'needs_attention': needs_attention,
            'trial_soon': trial_soon,
            'location': geo.location_cell(u),
        })

    # Counts describe the rows the filters actually produced, so the strip and
    # the table can never tell the owner two different stories.
    summary = {
        'total': len(rows),
        'paying': sum(1 for r in rows if r['sub_state'] == 'active'),
        'trialing': sum(1 for r in rows if r['sub_state'] == 'trialing'),
        'attention': sum(1 for r in rows if r['needs_attention']),
        'countries': len({(r['location']['country'] or '').lower() for r in rows if r['location']['country']}),
    }

    # How many hosts each country holds across the WHOLE filtered set, so a
    # group header can state the real total even when the page shows a slice.
    per_country = Counter((r['location']['country'] or '').lower() for r in rows)

    if grouped:
        # Country-major, chosen sort within each country. Python's sort is
        # stable, so the queryset's ordering survives inside every group, and
        # hosts with no country recorded collect at the end rather than sorting
        # to the top under an empty heading.
        rows.sort(key=lambda r: (
            not r['location']['country'], (r['location']['country'] or '').lower()
        ))

    page = _paginate(request, rows, 25)
    groups = _country_groups(list(page)) if grouped else []
    for g in groups:
        g['total'] = per_country[g['key']]
        g['partial'] = g['total'] != len(g['rows'])

    return render(request, 'controlpanel/users.html', {
        'active_nav': 'users',
        'page_obj': page,
        'groups': groups,
        'grouped': grouped,
        'q': q, 'status': status, 'sub': sub, 'attention': attention,
        'country': country, 'sort': sort,
        'sort_label': USER_SORTS[sort][1],
        'sort_options': [(k, v[1]) for k, v in USER_SORTS.items()],
        'sub_labels': analytics.SUBSCRIPTION_LABELS,
        'countries': geo.countries_in_use(base),
        'summary': summary,
        'has_filters': bool(q or status or sub or attention or country),
        'total_count': len(rows),
    })


@section_required('users')
def user_detail(request, pk):
    user = get_object_or_404(analytics.hosts_queryset(), pk=pk)
    now = timezone.now()

    properties = Property.objects.filter(created_by=user).order_by('-created_at')
    bookings = Booking.objects.filter(property__created_by=user).select_related('property', 'channel')
    revenue = bookings.aggregate(t=Sum('price'))['t'] or Decimal('0')
    collected = Payment.objects.filter(
        booking__property__created_by=user, is_paid=True
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    stripe = StripeCustomer.objects.filter(user=user).first()
    state = analytics.classify_subscription(user, stripe, now)
    trial_end = analytics.trial_end_for(user)
    health = analytics.host_health(user, stripe, now)

    my_cohosts = CoHost.objects.filter(host=user).select_related('co_host')
    hosted_by = CoHost.objects.filter(co_host=user).select_related('host')

    return render(request, 'controlpanel/user_detail.html', {
        'active_nav': 'users',
        'u': user,
        'properties': properties,
        'n_properties': properties.count(),
        'recent_bookings': bookings.order_by('-created_at')[:12],
        'n_bookings': bookings.count(),
        'revenue': revenue,
        'collected': collected,
        'stripe': stripe,
        'sub_state': state,
        'sub_label': analytics.SUBSCRIPTION_LABELS.get(state, state),
        'trial_end': trial_end,
        'trial_days_left': (trial_end.date() - now.date()).days if trial_end else None,
        'health': health,
        'my_cohosts': my_cohosts,
        'hosted_by': hosted_by,
        'documents': user.documents.all(),
        'is_owner_account': is_platform_admin(user),
    })


@section_required('users')
@require_POST
def user_action(request, pk):
    user = get_object_or_404(MyUser, pk=pk)
    action = request.POST.get('action')

    # Absolute guardrail: console accounts (the owner and any co-admin) can
    # never be acted upon from the Hosts pages. Co-admins are already excluded
    # from every host listing; this is the belt-and-braces check behind it, and
    # it keeps the only way to revoke a co-admin the Co-admins page, where
    # removal also deletes the login.
    if is_platform_admin(user):
        messages.error(request, 'Console accounts cannot be modified here. Use the Co-admins page.')
        return redirect('controlpanel:user_detail', pk=pk)

    if action == 'block':
        user.is_active = False
        user.save(update_fields=['is_active'])
        messages.success(request, f'{user.username} has been blocked and can no longer sign in.')
    elif action == 'unblock':
        user.is_active = True
        user.save(update_fields=['is_active'])
        messages.success(request, f'{user.username} has been unblocked.')
    elif action == 'grant_free':
        user.is_subscription_free = True
        user.save(update_fields=['is_subscription_free'])
        messages.success(request, f'{user.username} now has free (comped) access.')
    elif action == 'revoke_free':
        user.is_subscription_free = False
        user.save(update_fields=['is_subscription_free'])
        messages.success(request, f'Comped free access removed for {user.username}.')
    elif action == 'set_trial':
        raw = (request.POST.get('trial_days') or '').strip()
        try:
            days = max(0, int(raw))
        except (TypeError, ValueError):
            messages.error(request, 'Enter a valid number of trial days.')
            return redirect('controlpanel:user_detail', pk=pk)
        user.trial_days = days
        user.save(update_fields=['trial_days'])
        messages.success(request, f"{user.username}'s trial length is now {days} days.")
    elif action == 'delete':
        confirm = (request.POST.get('confirm_username') or '').strip()
        if confirm != user.username:
            messages.error(request, 'Account deletion aborted: the confirmation text did not match the username.')
            return redirect('controlpanel:user_detail', pk=pk)
        uname = user.username
        user.delete()
        messages.success(request, f'Account "{uname}" and all its data were permanently deleted.')
        return redirect('controlpanel:users')
    else:
        messages.error(request, 'Unknown action.')

    return redirect('controlpanel:user_detail', pk=pk)


# ── properties ───────────────────────────────────────────────────────────────

@section_required('properties')
def properties_list(request):
    q = (request.GET.get('q') or '').strip()
    status = request.GET.get('status') or ''
    qs = Property.objects.select_related('created_by').annotate(
        n_bookings=Count('booking', distinct=True),
    ).order_by('-created_at')
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(nick_name__icontains=q) |
            Q(city__icontains=q) | Q(country__icontains=q) |
            Q(created_by__username__icontains=q) | Q(created_by__email__icontains=q)
        )
    if status in ('Active', 'Inactive'):
        qs = qs.filter(status=status)
    page = _paginate(request, qs, 25)
    return render(request, 'controlpanel/properties.html', {
        'active_nav': 'properties', 'page_obj': page, 'q': q, 'status': status,
        'total_count': qs.count(),
    })


@section_required('properties')
def property_detail(request, pk):
    """A listing and everything about it — including ALL of its bookings.

    The bookings table is paginated and status-filterable here rather than
    living on a separate page, so a listing's reservations are read where the
    listing is.
    """
    prop = get_object_or_404(Property.objects.select_related('created_by'), pk=pk)

    all_bookings = Booking.objects.filter(property=prop).select_related('channel').order_by('-created_at')
    n_bookings = all_bookings.count()

    # Money booked excludes cancellations, matching the dashboard's definition.
    revenue = all_bookings.exclude(status='cancelled').aggregate(t=Sum('price'))['t'] or Decimal('0')
    n_cancelled = all_bookings.filter(status='cancelled').count()

    status = request.GET.get('status') or ''
    shown = all_bookings.filter(status=status) if status in dict(Booking.STATUS_CHOICES) else all_bookings

    return render(request, 'controlpanel/property_detail.html', {
        'active_nav': 'properties',
        'p': prop,
        'page_obj': _paginate(request, shown, 15),
        'n_bookings': n_bookings,
        'n_shown': shown.count(),
        'n_cancelled': n_cancelled,
        'status': status,
        'status_choices': Booking.STATUS_CHOICES,
        'revenue': revenue,
        'enquiries': Enquiry.objects.filter(property=prop).order_by('-created_at')[:10],
        'images': prop.images.all() if hasattr(prop, 'images') else [],
    })


# ── bookings ─────────────────────────────────────────────────────────────────

@section_required('bookings')
def bookings_list(request):
    """Bookings, optionally narrowed to one listing (?property_id=…).

    Reached from a property rather than from its own nav entry, so the sidebar
    keeps Properties highlighted. The unfiltered URL still works for anything
    that links to it (the dashboard's "View all", for one).
    """
    q = (request.GET.get('q') or '').strip()
    status = request.GET.get('status') or ''
    property_id = (request.GET.get('property_id') or '').strip()

    qs = Booking.objects.select_related('property', 'property__created_by', 'channel').order_by('-created_at')

    current_property = None
    if property_id:
        # Parse before querying — a non-UUID string reaching a UUID pk lookup
        # raises, and a hand-edited URL must not 500.
        try:
            pk = uuid.UUID(property_id)
        except (ValueError, AttributeError, TypeError):
            pk = None

        current_property = (
            Property.objects.filter(pk=pk).select_related('created_by').first() if pk else None
        )
        if current_property:
            qs = qs.filter(property=current_property)
        else:
            # An unknown id must not silently show every booking as if it were
            # that listing's — show nothing and say so.
            qs = qs.none()

    if q:
        qs = qs.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q) |
            Q(property__title__icontains=q) | Q(booking_id__icontains=q)
        )
    if status in dict(Booking.STATUS_CHOICES):
        qs = qs.filter(status=status)

    page = _paginate(request, qs, 30)
    return render(request, 'controlpanel/bookings.html', {
        'active_nav': 'properties', 'page_obj': page, 'q': q, 'status': status,
        'status_choices': Booking.STATUS_CHOICES, 'total_count': qs.count(),
        'property_id': property_id, 'current_property': current_property,
    })


@section_required('bookings')
def booking_detail(request, pk):
    booking = get_object_or_404(
        Booking.objects.select_related('property', 'property__created_by', 'channel'), pk=pk
    )
    payments = booking.payments.all().order_by('-payment_date')
    return render(request, 'controlpanel/booking_detail.html', {
        'active_nav': 'bookings', 'b': booking, 'payments': payments,
        'paid': payments.filter(is_paid=True).aggregate(t=Sum('amount'))['t'] or Decimal('0'),
    })


# ── enquiries ────────────────────────────────────────────────────────────────

@section_required('enquiries')
def enquiries_list(request):
    q = (request.GET.get('q') or '').strip()
    qs = Enquiry.objects.select_related('property', 'property__created_by').order_by('-created_at')
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(email__icontains=q) | Q(property__title__icontains=q)
        )
    page = _paginate(request, qs, 30)
    return render(request, 'controlpanel/enquiries.html', {
        'active_nav': 'enquiries', 'page_obj': page, 'q': q, 'total_count': qs.count(),
    })


# ── subscriptions ────────────────────────────────────────────────────────────

@section_required('subscriptions')
def subscriptions_list(request):
    now = timezone.now()
    smap = analytics.stripe_map()
    filt = request.GET.get('state') or ''
    rows = []
    for u in analytics.hosts_queryset().order_by('-created_at'):
        sc = smap.get(u.id)
        state = analytics.classify_subscription(u, sc, now)
        if filt and state != filt:
            continue
        rows.append({
            'user': u, 'stripe': sc, 'state': state,
            'label': analytics.SUBSCRIPTION_LABELS.get(state, state),
            'trial_end': analytics.trial_end_for(u),
        })
    setting = PlatformSetting.load()
    active = sum(1 for r in rows if r['state'] == 'active') if not filt else \
        sum(1 for u in analytics.hosts_queryset() if analytics.classify_subscription(u, smap.get(u.id), now) == 'active')
    page = _paginate(request, rows, 30)
    return render(request, 'controlpanel/subscriptions.html', {
        'active_nav': 'subscriptions', 'page_obj': page, 'state': filt,
        'sub_labels': analytics.SUBSCRIPTION_LABELS, 'total_count': len(rows),
        'mrr': (setting.subscription_price or Decimal('0')) * active,
        'setting': setting,
    })


# ── payments / finance ───────────────────────────────────────────────────────

@section_required('payments')
def payments_list(request):
    status = request.GET.get('status') or ''
    qs = Payment.objects.select_related('booking', 'booking__property').order_by('-payment_date', '-id')
    if status == 'paid':
        qs = qs.filter(is_paid=True)
    elif status == 'unpaid':
        qs = qs.filter(is_paid=False)
    totals = {
        'paid': Payment.objects.filter(is_paid=True).aggregate(t=Sum('amount'))['t'] or Decimal('0'),
        'unpaid': Payment.objects.filter(is_paid=False).aggregate(t=Sum('amount'))['t'] or Decimal('0'),
    }
    page = _paginate(request, qs, 40)
    return render(request, 'controlpanel/payments.html', {
        'active_nav': 'payments', 'page_obj': page, 'status': status,
        'totals': totals, 'total_count': qs.count(),
    })


# ── platform settings (pricing / trial) ──────────────────────────────────────

@owner_required
def platform_settings(request):
    setting = PlatformSetting.load()
    if request.method == 'POST':
        def _dec(name, current):
            raw = (request.POST.get(name) or '').strip()
            try:
                return Decimal(raw)
            except (InvalidOperation, TypeError):
                return current
        setting.subscription_price = _dec('subscription_price', setting.subscription_price)
        setting.subscription_price_yearly = _dec('subscription_price_yearly', setting.subscription_price_yearly)
        setting.subscription_currency = (request.POST.get('subscription_currency') or setting.subscription_currency).strip()[:10]
        setting.subscription_interval = (request.POST.get('subscription_interval') or setting.subscription_interval).strip()[:20]
        setting.subscription_interval_yearly = (request.POST.get('subscription_interval_yearly') or setting.subscription_interval_yearly).strip()[:20]
        try:
            setting.free_trial_days = max(0, int(request.POST.get('free_trial_days') or setting.free_trial_days))
        except (TypeError, ValueError):
            pass
        setting.save()
        messages.success(request, 'Platform settings saved. (Stripe prices must be updated separately in the Stripe dashboard.)')
        return redirect('controlpanel:settings')
    return render(request, 'controlpanel/settings.html', {
        'active_nav': 'settings', 'setting': setting,
        'admin_email': settings.PLATFORM_ADMIN_EMAIL,
        'coadmin_count': CoAdmin.objects.count(),
    })


# ── co-admins (console delegates) ────────────────────────────────────────────

@owner_required
def co_admins(request):
    """Appoint, edit and revoke platform co-admins.

    Structured to match the host-side ``manage_cohost_view``: one page holding
    the list plus add / edit / delete actions, the plain password kept only for
    display so the appointer can hand it over, and — crucially — **revoking
    deletes the user account**, which frees the email so that person can sign
    up as an ordinary host afterwards.

    Guards, in order of importance:

    * the owner account can never be turned into, or removed as, a co-admin;
    * a co-admin can never edit or revoke themselves (only the owner or a peer
      can), so nobody can lock the console into an unrecoverable state by
      accident;
    * an email that already belongs to a host or a co-host is refused — those
      are somebody else's accounts and must not be silently repurposed.
    """
    me = request.user

    def _guard(rel):
        """Reject acting on the owner or on your own row. Returns an error or None."""
        if rel.user_id == me.pk:
            return 'You cannot modify your own co-admin access.'
        if (rel.user.email or '').strip().lower() == admin_email():
            return 'The platform owner account cannot be modified here.'
        return None

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'add':
            email = (request.POST.get('email') or '').strip().lower()
            password = (request.POST.get('password') or '').strip()
            full_name = (request.POST.get('full_name') or '').strip()
            phone = (request.POST.get('phone') or '').strip()

            if not email or not password:
                messages.error(request, 'Email and password are required.')
                return redirect('controlpanel:co_admins')
            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, 'Please enter a valid email address.')
                return redirect('controlpanel:co_admins')
            if email == admin_email():
                messages.error(request, 'That is the platform owner account — it already has full access.')
                return redirect('controlpanel:co_admins')

            existing = MyUser.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).first()
            if existing:
                if CoAdmin.objects.filter(user=existing).exists():
                    messages.error(request, 'This email is already a co-admin.')
                else:
                    messages.error(
                        request,
                        'That email already belongs to an existing account on the platform. '
                        'Use an email that is not registered yet.',
                    )
                return redirect('controlpanel:co_admins')

            parts = full_name.split(' ', 1)
            user = MyUser.objects.create_user(username=email, email=email, password=password)
            user.first_name = parts[0] if parts else ''
            user.last_name = parts[1] if len(parts) > 1 else ''
            user.phone = phone
            user.is_active = True
            user.save()

            perms = clean_permissions(request.POST.getlist('permissions'))
            CoAdmin.objects.create(
                user=user, display_password=password, created_by=me, permissions=perms,
            )
            if perms:
                granted = ', '.join(SECTION_LABELS[p] for p in perms)
                messages.success(request, f'Co-admin {email} added with access to {granted}.')
            else:
                messages.success(
                    request,
                    f'Co-admin {email} added with no sections yet — they can sign in but will '
                    f'see nothing until you grant access.',
                )
            return redirect('controlpanel:co_admins')

        elif action == 'edit':
            rel = get_object_or_404(CoAdmin.objects.select_related('user'), pk=request.POST.get('coadmin_id') or 0)
            error = _guard(rel)
            if error:
                messages.error(request, error)
                return redirect('controlpanel:co_admins')

            user = rel.user
            email = (request.POST.get('email') or '').strip().lower()
            password = (request.POST.get('password') or '').strip()
            full_name = (request.POST.get('full_name') or '').strip()

            parts = full_name.split(' ', 1)
            user.first_name = parts[0] if parts else ''
            user.last_name = parts[1] if len(parts) > 1 else ''
            user.phone = (request.POST.get('phone') or '').strip()

            if email and email != (user.email or '').lower():
                try:
                    validate_email(email)
                except ValidationError:
                    messages.error(request, 'Please enter a valid email address.')
                    return redirect('controlpanel:co_admins')
                if email == admin_email() or MyUser.objects.exclude(pk=user.pk).filter(
                    Q(email__iexact=email) | Q(username__iexact=email)
                ).exists():
                    messages.error(request, 'That email is already in use by another account.')
                    return redirect('controlpanel:co_admins')
                user.email = email
                user.username = email
            if password:
                user.set_password(password)
                rel.display_password = password
            rel.permissions = clean_permissions(request.POST.getlist('permissions'))
            user.save()
            rel.save()

            messages.success(request, 'Co-admin updated successfully.')
            return redirect('controlpanel:co_admins')

        elif action == 'delete':
            rel = get_object_or_404(CoAdmin.objects.select_related('user'), pk=request.POST.get('coadmin_id') or 0)
            error = _guard(rel)
            if error:
                messages.error(request, error)
                return redirect('controlpanel:co_admins')

            user = rel.user
            email = user.email
            rel.delete()
            # Delete the account itself, exactly like removing a co-host: the
            # email becomes available again so they can register as a host.
            user.delete()
            messages.success(request, f'Co-admin {email} removed and account deleted.')
            return redirect('controlpanel:co_admins')

    rows = []
    for rel in CoAdmin.objects.select_related('user', 'created_by'):
        granted = clean_permissions(rel.permissions)
        rows.append({
            'rel': rel,
            'user': rel.user,
            # Labels for the table, and the raw keys for the edit modal so it
            # can re-check the right boxes.
            'granted_labels': [SECTION_LABELS[k] for k in granted],
            'granted_keys': ','.join(granted),
            'n_granted': len(granted),
        })

    return render(request, 'controlpanel/co_admins.html', {
        'active_nav': 'co_admins',
        'rows': rows,
        'sections': SECTIONS,
        'owner_email': admin_email(),
        'total_count': len(rows),
    })

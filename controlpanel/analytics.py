"""Aggregation helpers for the owner console.

All monetary values are read straight from the DB, which stores the canonical
USD base (see accounts/currency.py). The console therefore reports everything in
USD — the platform owner's single source of truth — regardless of each host's
own display currency.
"""
from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from accounts.models import MyUser, CoHost, CoAdmin
from property.models import Property
from booking.models import Booking, Payment, Enquiry
from billing.models import StripeCustomer, PlatformSetting


# ── small utilities ─────────────────────────────────────────────────────────

def _month_start(d):
    return date(d.year, d.month, 1)


def _add_month(d):
    return date(d.year + (d.month // 12), (d.month % 12) + 1, 1)


def last_n_months(n=12):
    """Return an ordered list of {key,label,year,month} for the last n months."""
    today = timezone.now().date()
    cur = _month_start(today)
    months = []
    for _ in range(n):
        months.append(cur)
        # step back one month
        if cur.month == 1:
            cur = date(cur.year - 1, 12, 1)
        else:
            cur = date(cur.year, cur.month - 1, 1)
    months.reverse()
    out = []
    for m in months:
        out.append({
            'key': f'{m.year}-{m.month:02d}',
            'label': m.strftime('%b %Y'),
            'year': m.year,
            'month': m.month,
        })
    return out


def monthly_counts(qs, date_field, n=12):
    """Count rows in ``qs`` per calendar month for the last n months."""
    months = last_n_months(n)
    buckets = OrderedDict((m['key'], 0) for m in months)
    earliest = date(months[0]['year'], months[0]['month'], 1)
    rows = qs.filter(**{f'{date_field}__date__gte': earliest}).values_list(date_field, flat=True)
    for dt in rows:
        if not dt:
            continue
        d = timezone.localtime(dt).date() if timezone.is_aware(dt) else (dt.date() if hasattr(dt, 'date') else dt)
        key = f'{d.year}-{d.month:02d}'
        if key in buckets:
            buckets[key] += 1
    return {
        'labels': [m['label'] for m in months],
        'values': [buckets[m['key']] for m in months],
    }


def monthly_sum(qs, date_field, value_field, n=12):
    """Sum ``value_field`` in ``qs`` per calendar month for the last n months."""
    months = last_n_months(n)
    buckets = OrderedDict((m['key'], Decimal('0')) for m in months)
    earliest = date(months[0]['year'], months[0]['month'], 1)
    rows = qs.filter(**{f'{date_field}__date__gte': earliest}).values_list(date_field, value_field)
    for dt, val in rows:
        if not dt:
            continue
        d = timezone.localtime(dt).date() if timezone.is_aware(dt) else (dt.date() if hasattr(dt, 'date') else dt)
        key = f'{d.year}-{d.month:02d}'
        if key in buckets:
            buckets[key] += (val or Decimal('0'))
    return {
        'labels': [m['label'] for m in months],
        'values': [float(buckets[m['key']]) for m in months],
    }


# ── subscription classification ─────────────────────────────────────────────

SUBSCRIPTION_LABELS = OrderedDict([
    ('active', 'Active (paid)'),
    ('trialing', 'On free trial'),
    ('past_due', 'Past due'),
    ('free', 'Free (comped)'),
    ('canceled', 'Cancelled'),
    ('expired', 'Trial expired'),
])

SUBSCRIPTION_COLORS = {
    'active': '#16a34a',
    'trialing': '#e05c2a',
    'past_due': '#f59e0b',
    'free': '#6366f1',
    'canceled': '#9ca3af',
    'expired': '#ef4444',
}


def trial_end_for(user):
    try:
        return user.created_at + timedelta(days=int(user.trial_days or 0))
    except Exception:
        return None


def classify_subscription(user, stripe=None, now=None):
    """Return a single subscription-state key for a user.

    ``stripe`` is that user's StripeCustomer (or None). Passing it in lets the
    caller prefetch a map and avoid per-row queries.
    """
    now = now or timezone.now()
    if getattr(user, 'is_subscription_free', False):
        return 'free'
    status = (getattr(stripe, 'subscription_status', '') or '').strip().lower() if stripe else ''
    if status == 'active':
        return 'active'
    if status == 'past_due':
        return 'past_due'
    if status in ('canceled', 'cancelled'):
        return 'canceled'
    # No live paid subscription — fall back to the free-trial window.
    end = trial_end_for(user)
    if end and now <= end:
        return 'trialing'
    return 'expired'


def stripe_map():
    return {sc.user_id: sc for sc in StripeCustomer.objects.all()}


def host_health(user, stripe=None, now=None):
    """Owner-relevant health snapshot for one host: engagement, tenure,
    estimated lifetime value to the platform, and risk flags."""
    now = now or timezone.now()
    state = classify_subscription(user, stripe, now)
    end = trial_end_for(user)

    last_login = user.last_login
    days_since_login = (now.date() - last_login.date()).days if last_login else None
    dormant = user.is_active and (last_login is None or days_since_login is not None and days_since_login > 45)

    n_listings = Property.objects.filter(created_by=user).count()

    # Estimated value to the platform: months subscribed × monthly price.
    setting = PlatformSetting.load()
    price = setting.subscription_price or Decimal('0')
    ltv = Decimal('0')
    months_subscribed = 0
    if stripe and stripe.created_at:
        months_subscribed = max(0, (now.year - stripe.created_at.year) * 12 + (now.month - stripe.created_at.month))
        if state in ('active', 'past_due'):
            ltv = price * (months_subscribed + 1)

    flags = []
    if not user.is_active:
        flags.append(('Blocked', 'red'))
    if state == 'past_due':
        flags.append(('Payment past due', 'amber'))
    if state == 'trialing' and end:
        days_left = (end.date() - now.date()).days
        if 0 <= days_left <= 7:
            flags.append((f'Trial ends in {days_left}d', 'amber'))
    if state == 'expired':
        flags.append(('Trial expired, not converted', 'red'))
    if n_listings == 0:
        flags.append(('No listings (onboarding stalled)', 'amber'))
    if dormant:
        flags.append(('Dormant (no recent login)', 'gray'))

    return {
        'state': state,
        'state_label': SUBSCRIPTION_LABELS.get(state, state),
        'last_login': last_login,
        'days_since_login': days_since_login,
        'dormant': dormant,
        'n_listings': n_listings,
        'trial_end': end,
        'months_subscribed': months_subscribed,
        'subscriber_since': stripe.created_at if stripe else None,
        'ltv': ltv,
        'flags': flags,
    }


# ── host querysets ───────────────────────────────────────────────────────────

def hosts_queryset():
    """Primary host accounts only.

    Excludes (a) the platform-owner account, (b) **co-hosts**, and
    (c) **platform co-admins**. Co-hosts and co-admins are both dependent
    sub-accounts someone else creates and can delete; they don't own the
    account or carry their own subscription, so they must never be counted or
    listed as standalone accounts. Co-hosts surface only nested under their
    host on the host's detail page; co-admins only on the Co-admins page.
    """
    owner_email = (getattr(settings, 'PLATFORM_ADMIN_EMAIL', '') or '').strip()
    qs = MyUser.objects.exclude(id__in=CoHost.objects.values('co_host_id')) \
                       .exclude(id__in=CoAdmin.objects.values('user_id'))
    if owner_email:
        qs = qs.exclude(email__iexact=owner_email)
    return qs


def cohost_user_ids():
    return set(CoHost.objects.values_list('co_host_id', flat=True))


# ── the big dashboard payload ───────────────────────────────────────────────

def dashboard_context():
    now = timezone.now()
    today = now.date()
    month_start = _month_start(today)
    prev_month_start = date(month_start.year - 1, 12, 1) if month_start.month == 1 \
        else date(month_start.year, month_start.month - 1, 1)

    hosts = hosts_queryset()
    total_users = hosts.count()
    blocked_users = hosts.filter(is_active=False).count()
    active_users = total_users - blocked_users
    new_users_this_month = hosts.filter(created_at__date__gte=month_start).count()
    new_users_prev_month = hosts.filter(
        created_at__date__gte=prev_month_start, created_at__date__lt=month_start
    ).count()

    props = Property.objects.all()
    total_props = props.count()
    active_props = props.filter(status='Active').count()

    bookings = Booking.objects.all()
    total_bookings = bookings.count()
    bookings_this_month = bookings.filter(created_at__date__gte=month_start).count()
    confirmed_bookings = bookings.filter(status='confirmed').count()
    cancelled_bookings = bookings.filter(status='cancelled').count()

    gross_booking_value = bookings.aggregate(t=Sum('price'))['t'] or Decimal('0')
    collected = Payment.objects.filter(is_paid=True).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    outstanding = Payment.objects.filter(is_paid=False).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    enquiries = Enquiry.objects.all()
    total_enquiries = enquiries.count()
    open_enquiries = enquiries.filter(is_archive=False, is_booked=False).count()

    # ── one pass over all hosts: classify subscription, build the attention
    #    queue, and gather engagement/activation signals ────────────────────
    smap = stripe_map()
    listing_counts = dict(
        Property.objects.values_list('created_by').annotate(n=Count('id'))
    )
    sub_counts = OrderedDict((k, 0) for k in SUBSCRIPTION_LABELS)
    dormant_cutoff = now - timedelta(days=45)

    att_trials_ending, att_past_due, att_no_listing, att_dormant, att_blocked = [], [], [], [], []
    activated = 0

    hosts_list = list(hosts)
    for u in hosts_list:
        sc = smap.get(u.id)
        state = classify_subscription(u, sc, now)
        sub_counts[state] += 1
        n_listings = listing_counts.get(u.id, 0)
        if n_listings > 0:
            activated += 1

        # Attention queue — the accounts an owner should act on today.
        end = trial_end_for(u)
        if state == 'trialing' and end:
            days_left = (end.date() - now.date()).days
            if 0 <= days_left <= 7:
                att_trials_ending.append({'user': u, 'days_left': days_left})
        if state == 'past_due':
            att_past_due.append({'user': u})
        if not u.is_active:
            att_blocked.append({'user': u})
        elif n_listings == 0:
            att_no_listing.append({'user': u, 'days_since_join': (now.date() - u.created_at.date()).days})
        elif (not u.last_login) or (u.last_login < dormant_cutoff):
            att_dormant.append({'user': u, 'last_login': u.last_login})

    att_trials_ending.sort(key=lambda r: r['days_left'])

    setting = PlatformSetting.load()
    monthly_price = setting.subscription_price or Decimal('0')
    mrr = Decimal(sub_counts['active']) * monthly_price

    # SaaS movement metrics (approximate, from the data we hold — no Stripe API)
    new_paid_this_month = StripeCustomer.objects.filter(
        subscription_status='active', created_at__date__gte=month_start
    ).count()
    churned_this_month = StripeCustomer.objects.filter(
        subscription_status__in=['canceled', 'cancelled'], updated_at__date__gte=month_start
    ).count()
    decided = sub_counts['active'] + sub_counts['expired'] + sub_counts['canceled']
    trial_conversion = round(sub_counts['active'] / decided * 100) if decided else None
    activation_rate = round(activated / total_users * 100) if total_users else None
    attention_total = (len(att_trials_ending) + len(att_past_due) +
                       len(att_no_listing) + len(att_dormant) + len(att_blocked))

    # top hosts by gross booking value
    top_hosts_raw = (
        bookings.values('property__created_by')
        .annotate(revenue=Sum('price'), n=Count('id'))
        .order_by('-revenue')[:8]
    )
    owner_ids = [r['property__created_by'] for r in top_hosts_raw if r['property__created_by']]
    owner_lookup = {u.id: u for u in MyUser.objects.filter(id__in=owner_ids)}
    top_hosts = []
    for r in top_hosts_raw:
        u = owner_lookup.get(r['property__created_by'])
        if not u:
            continue
        top_hosts.append({
            'user': u,
            'name': u.get_full_name() or u.username,
            'revenue': float(r['revenue'] or 0),
            'bookings': r['n'],
        })

    # bookings by channel
    channel_rows = (
        bookings.values('channel__name').annotate(n=Count('id')).order_by('-n')
    )
    channel_labels, channel_values = [], []
    for r in channel_rows:
        channel_labels.append(r['channel__name'] or 'Direct / Unspecified')
        channel_values.append(r['n'])

    # property type distribution
    ptype_rows = props.values('property_type').annotate(n=Count('id')).order_by('-n')
    ptype_map = {'entire_place': 'Entire place', 'private_room': 'Private room',
                 'shared_room': 'Shared room', '': 'Unspecified', None: 'Unspecified'}
    ptype_labels = [ptype_map.get(r['property_type'], r['property_type'] or 'Unspecified') for r in ptype_rows]
    ptype_values = [r['n'] for r in ptype_rows]

    # booking status distribution
    bstatus_rows = bookings.values('status').annotate(n=Count('id')).order_by('-n')
    bstatus_map = dict(Booking.STATUS_CHOICES)
    bstatus_labels = [bstatus_map.get(r['status'], r['status']) for r in bstatus_rows]
    bstatus_values = [r['n'] for r in bstatus_rows]

    def pct_change(cur, prev):
        if not prev:
            return None
        return round((cur - prev) / prev * 100)

    return {
        'kpis': {
            # ── The platform's own business (what the owner earns) ──
            'mrr': float(mrr),
            'arr': float(mrr * 12),
            'active_subscriptions': sub_counts['active'],
            'trialing': sub_counts['trialing'],
            'new_paid_this_month': new_paid_this_month,
            'churned_this_month': churned_this_month,
            'trial_conversion': trial_conversion,
            'activation_rate': activation_rate,
            # ── Growth ──
            'total_users': total_users,
            'active_users': active_users,
            'blocked_users': blocked_users,
            'new_users_this_month': new_users_this_month,
            'new_users_growth': pct_change(new_users_this_month, new_users_prev_month),
            # ── Platform scale / host activity (their money, our engagement signal) ──
            'total_props': total_props,
            'active_props': active_props,
            'total_bookings': total_bookings,
            'bookings_this_month': bookings_this_month,
            'confirmed_bookings': confirmed_bookings,
            'cancelled_bookings': cancelled_bookings,
            'gross_booking_value': float(gross_booking_value),
            'collected': float(collected),
            'outstanding': float(outstanding),
            'total_enquiries': total_enquiries,
            'open_enquiries': open_enquiries,
        },
        'attention': {
            'total': attention_total,
            'trials_ending': att_trials_ending,
            'past_due': att_past_due,
            'no_listing': att_no_listing,
            'dormant': att_dormant,
            'blocked': att_blocked,
        },
        'monthly_price_display': setting.amount_display,
        'charts': {
            'signups': monthly_counts(hosts, 'created_at', 12),
            'bookings': monthly_counts(bookings, 'created_at', 12),
            'revenue': monthly_sum(bookings, 'created_at', 'price', 12),
            'payments': monthly_sum(Payment.objects.filter(is_paid=True), 'payment_date', 'amount', 12),
            'subscriptions': {
                'labels': [SUBSCRIPTION_LABELS[k] for k in sub_counts],
                'values': [sub_counts[k] for k in sub_counts],
                'colors': [SUBSCRIPTION_COLORS[k] for k in sub_counts],
            },
            'channels': {'labels': channel_labels, 'values': channel_values},
            'property_types': {'labels': ptype_labels, 'values': ptype_values},
            'booking_status': {'labels': bstatus_labels, 'values': bstatus_values},
        },
        'top_hosts': top_hosts,
        'recent_users': list(hosts.order_by('-created_at')[:8]),
        'recent_bookings': list(
            bookings.select_related('property', 'property__created_by', 'channel').order_by('-created_at')[:8]
        ),
        'recent_enquiries': list(
            enquiries.select_related('property', 'property__created_by').order_by('-created_at')[:8]
        ),
    }

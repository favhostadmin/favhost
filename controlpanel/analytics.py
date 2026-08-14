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
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from accounts.models import MyUser, CoHost, CoAdmin
from property.models import Property
from booking.models import Booking, Payment, Enquiry
from billing.models import StripeCustomer, PlatformSetting

from .models import PageView


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


# ── daily series (the traffic / audience report) ─────────────────────────────

def _local_date(dt):
    """Normalise a datetime (or date) coming out of the ORM to a local date."""
    if not dt:
        return None
    if timezone.is_aware(dt):
        return timezone.localtime(dt).date()
    return dt.date() if hasattr(dt, 'date') else dt


def daily_buckets(qs, date_field, start, end, value_field=None):
    """Count rows (or sum ``value_field``) per calendar day across [start, end].

    Returns a list of one number per day, gaps included as zeroes — a report
    that silently skips quiet days misreads as "no data" rather than "none".
    """
    span = (end - start).days + 1
    zero = Decimal('0') if value_field else 0
    buckets = OrderedDict((start + timedelta(days=i), zero) for i in range(span))

    fields = [date_field] + ([value_field] if value_field else [])
    rows = qs.filter(**{
        f'{date_field}__date__gte': start,
        f'{date_field}__date__lte': end,
    }).values_list(*fields)

    for row in rows:
        day = _local_date(row[0])
        if day not in buckets:
            continue
        buckets[day] += (row[1] or Decimal('0')) if value_field else 1

    if value_field:
        return [float(v) for v in buckets.values()]
    return list(buckets.values())


def daily_distinct(qs, date_field, distinct_field, start, end):
    """Per-day count of DISTINCT ``distinct_field`` — unique visitors, not hits."""
    span = (end - start).days + 1
    buckets = OrderedDict((start + timedelta(days=i), 0) for i in range(span))
    rows = (
        qs.filter(**{f'{date_field}__date__gte': start, f'{date_field}__date__lte': end})
        .annotate(_day=TruncDate(date_field))
        .values('_day')
        .annotate(n=Count(distinct_field, distinct=True))
        .values_list('_day', 'n')
    )
    for day, n in rows:
        if day in buckets:
            buckets[day] = n
    return list(buckets.values())


def distinct_over(qs, date_field, distinct_field, start, end):
    """One count of DISTINCT values across the whole window.

    Not the same as summing the per-day distincts: a person who visits on five
    days counts once here and five times there. This is the true "unique
    people" figure, which only works because the visitor id is stable.
    """
    return (
        qs.filter(**{f'{date_field}__date__gte': start, f'{date_field}__date__lte': end})
        .values(distinct_field).distinct().count()
    )


def _delta_pct(current, previous):
    """Percent change, or None when there is no baseline to compare against."""
    if not previous:
        return None
    return round((current - previous) / previous * 100)


def _friendly_page(path, titles):
    """Turn a raw path into something an owner can read at a glance."""
    if path in titles:
        return titles[path], 'Listing page'
    parts = [p for p in path.split('/') if p]
    if not parts:
        return 'Home page', path
    if parts[0] == 'property' and len(parts) >= 2:
        if parts[1] == 'listing':
            return 'Host storefront', path
        if parts[1] == 'listing-details':
            return 'Listing page', path
        if parts[1] == 'request-book':
            return 'Booking request', path
    return path, ''


def _listing_titles_for(paths):
    """Map listing-detail paths to their property titles in one query."""
    wanted = {}
    for p in paths:
        parts = [x for x in p.split('/') if x]
        if len(parts) >= 4 and parts[0] == 'property' and parts[1] == 'listing-details':
            wanted[p] = parts[3]
    if not wanted:
        return {}
    found = dict(Property.objects.filter(slug__in=set(wanted.values())).values_list('slug', 'title'))
    return {path: found[slug] for path, slug in wanted.items() if slug in found}


MAX_RANGE_DAYS = 366


def traffic_context(days=28, start=None, end=None):
    """A Google-Analytics-style daily report over the metrics we actually hold.

    Every metric is a real first-party count from our own tables — visitors,
    page views, trials started, hosts converting to paid. Each carries a
    day-by-day series for the selected window plus the immediately preceding
    window of equal length, so the UI can draw the period-over-period
    comparison GA leads with.

    The charted pair is deliberately the platform's OWN funnel (trials → paid)
    rather than the hosts' booking activity; enquiries and bookings are still
    computed here for the visitor→booking funnel card below the chart.
    """
    today = timezone.localdate()
    custom = bool(start and end)

    if custom:
        # Tolerate a range typed backwards, and never report a future window.
        if start > end:
            start, end = end, start
        end = min(end, today)
        if start > end:
            start = end
        days = (end - start).days + 1
        if days > MAX_RANGE_DAYS:
            start = end - timedelta(days=MAX_RANGE_DAYS - 1)
            days = MAX_RANGE_DAYS
    else:
        days = days if days in (7, 28, 90) else 28
        end = today
        start = end - timedelta(days=days - 1)

    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    bookings = Booking.objects.all()
    enquiries = Enquiry.objects.all()
    views = PageView.objects.all()

    # The two SaaS-side series the tiles chart: a host signing up starts a free
    # trial (comped accounts never were on one, so they are excluded), and a
    # host converting shows up as their StripeCustomer row going active.
    hosts = hosts_queryset()
    trials = hosts.filter(is_subscription_free=False)
    paid = StripeCustomer.objects.filter(subscription_status='active', user__in=hosts)

    def add(metrics, key, label, hint, fmt, current, previous, total=None, prev_total=None):
        # Most metrics total by adding the daily bars up; visitors can't, so it
        # passes its own window-wide distinct count in.
        total = sum(current) if total is None else total
        prev_total = sum(previous) if prev_total is None else prev_total
        delta = _delta_pct(total, prev_total)
        metrics.append({
            'key': key,
            'label': label,
            'hint': hint,          # plain-English gloss, shown under the tile
            'format': fmt,
            'total': total,
            'prev_total': prev_total,
            'delta': delta,
            # the arrow already carries the sign — the template shows magnitude
            'delta_abs': abs(delta) if delta is not None else None,
            'values': current,
            'previous': previous,
        })

    metrics = []
    # Bars are unique people per day; the headline is unique people across the
    # whole window — someone who visits every day counts once in the headline.
    add(metrics, 'visitors', 'Visitors', 'different people who visited',
        'count',
        daily_distinct(views, 'created_at', 'visitor_key', start, end),
        daily_distinct(views, 'created_at', 'visitor_key', prev_start, prev_end),
        total=distinct_over(views, 'created_at', 'visitor_key', start, end),
        prev_total=distinct_over(views, 'created_at', 'visitor_key', prev_start, prev_end))
    add(metrics, 'views', 'Page views', 'pages they looked at',
        'count',
        daily_buckets(views, 'created_at', start, end),
        daily_buckets(views, 'created_at', prev_start, prev_end))
    add(metrics, 'trials', 'Trials', 'hosts who started a free trial',
        'count',
        daily_buckets(trials, 'created_at', start, end),
        daily_buckets(trials, 'created_at', prev_start, prev_end))
    add(metrics, 'paid', 'Paid hosts', 'hosts who started paying',
        'count',
        daily_buckets(paid, 'created_at', start, end),
        daily_buckets(paid, 'created_at', prev_start, prev_end))

    # Built by hand rather than with strftime('%b %-d') — the no-pad %-d flag
    # is glibc-only and blows up on Windows.
    labels = []
    iso = []
    for i in range(days):
        d = start + timedelta(days=i)
        labels.append(f'{d.strftime("%b")} {d.day}')
        iso.append(d.isoformat())

    prev_labels = []
    for i in range(days):
        d = prev_start + timedelta(days=i)
        prev_labels.append(f'{d.strftime("%b")} {d.day}')

    period_views = views.filter(created_at__date__gte=start, created_at__date__lte=end)

    # "Where visitors come from" — GA's acquisition report.
    source_rows = (
        period_views.values('referrer_host')
        .annotate(n=Count('visitor_key', distinct=True))
        .order_by('-n')[:6]
    )
    sources = [{
        'label': r['referrer_host'] or 'Direct — typed in or bookmarked',
        'value': r['n'],
    } for r in source_rows]

    # "Most visited pages" — GA's top-pages report, with readable names.
    page_rows = (
        period_views.values('path')
        .annotate(n=Count('id'), people=Count('visitor_key', distinct=True))
        .order_by('-n')[:6]
    )
    titles = _listing_titles_for([r['path'] for r in page_rows])
    top_pages = []
    for r in page_rows:
        name, sub = _friendly_page(r['path'], titles)
        top_pages.append({
            'name': name,
            'sub': sub,
            'value': r['n'],
            'people': r['people'],
        })

    # Conversion — the one ratio a non-technical owner actually needs.
    #
    # Only meaningful once visitor tracking has covered the WHOLE window:
    # bookings reach back through the old data, visitors only start the day
    # tracking was switched on, so mixing them early yields absurdities like
    # "800% of visitors booked". Suppress the rates until the window is clean.
    tracking_since = views.order_by('created_at').values_list('created_at', flat=True).first()
    covered = bool(tracking_since) and timezone.localtime(tracking_since).date() <= start

    # Read by key, not position — the tile order is a presentation choice and
    # has changed before; the funnel keeps reporting enquiries and bookings
    # whether or not either is charted above.
    by_key = {m['key']: m for m in metrics}
    visitors_total = by_key['visitors']['total']
    enquiries_total = sum(daily_buckets(enquiries, 'created_at', start, end))
    bookings_total = sum(daily_buckets(bookings, 'created_at', start, end))
    funnel = {
        'visitors': visitors_total,
        'enquiries': enquiries_total,
        'bookings': bookings_total,
        'covered': covered,
        'enquiry_rate': round(enquiries_total / visitors_total * 100, 1) if covered and visitors_total else None,
        'booking_rate': round(bookings_total / visitors_total * 100, 1) if covered and visitors_total else None,
    }

    return {
        'days': days,
        'start': start,
        'end': end,
        'is_custom': custom,
        'is_today': end == today,
        'prev_start': prev_start,
        'prev_end': prev_end,
        'labels': labels,
        'iso': iso,
        'prev_labels': prev_labels,
        'metrics': metrics,
        'sources': sources,
        'top_pages': top_pages,
        'funnel': funnel,
        'tracking_since': tracking_since,
        'tracking_covers_window': covered,
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


# ── charts ──────────────────────────────────────────────────────────────────

def subscription_charts(now=None):
    """Two honest series for the Subscriptions page.

    What is deliberately NOT here: an MRR-over-time line. Reconstructing it
    would need a history of each subscription's status, and we store only the
    current one — so any "MRR last 12 months" curve would be invented, not
    measured. A fabricated trend on a revenue screen is worse than no trend.

    ``started``  when subscriptions began, from ``StripeCustomer.created_at``.
    ``renewals`` what is due to bill in the coming months, from
                 ``current_period_end`` on live subscriptions — forward cash
                 visibility, which no other page shows.
    """
    now = now or timezone.now()
    today = now.date()
    price = float(PlatformSetting.load().subscription_price or 0)

    started = monthly_counts(StripeCustomer.objects.all(), 'created_at', 12)

    # Six forward months, including the current one.
    months, cur = [], _month_start(today)
    for _ in range(6):
        months.append(cur)
        cur = _add_month(cur)
    buckets = OrderedDict((f'{m.year}-{m.month:02d}', 0) for m in months)

    live = StripeCustomer.objects.filter(
        subscription_status__in=['active', 'past_due'],
        current_period_end__isnull=False,
        cancel_at_period_end=False,
    ).values_list('current_period_end', flat=True)
    for dt in live:
        d = _local_date(dt)
        if not d or d < today:
            continue
        key = f'{d.year}-{d.month:02d}'
        if key in buckets:
            buckets[key] += 1

    # Subscriptions still marked active whose paid period ended in the past.
    # They are counted in MRR but Stripe may already have moved on, so the
    # likeliest cause is a webhook that never landed. Surfacing the count is
    # the honest thing to do: it tells the reader how much to trust MRR.
    stale = StripeCustomer.objects.filter(
        subscription_status__in=['active', 'past_due'],
        current_period_end__lt=now,
    ).count()

    counts = list(buckets.values())
    renewals = {
        'labels': [m.strftime('%b %Y') for m in months],
        'counts': counts,
        'values': [round(n * price, 2) for n in counts],
        'total': sum(counts),
        'stale': stale,
    }
    return {'started': started, 'renewals': renewals}


def payment_series(qs, n=12):
    """Collected vs still-outstanding per month for a (possibly filtered) set.

    Bucketed on ``payment_date`` where the app recorded one and the scheduled
    ``expected_payment_date`` otherwise. That fallback is not cosmetic: rows
    with no ``payment_date`` are common, and keying on it alone silently drops
    them from the chart — an empty column reads as "no business that month"
    rather than "we never wrote that date down".

    Showing both series together is the point. Collected alone says how much
    came in; beside outstanding it says how much of what was owed came in,
    which is the number that reveals a collection problem.
    """
    eff = Coalesce('payment_date', 'expected_payment_date')
    dated = qs.annotate(eff_date=eff)
    paid = monthly_sum(dated.filter(is_paid=True), 'eff_date', 'amount', n)
    unpaid = monthly_sum(dated.filter(is_paid=False), 'eff_date', 'amount', n)
    return {
        'labels': paid['labels'],
        'collected': paid['values'],
        'outstanding': unpaid['values'],
    }


# ── the subscription business (our own revenue) ─────────────────────────────

def subscription_context(now=None):
    """Everything the Subscriptions page needs: recurring revenue, movement,
    trial funnel and the billing work queues.

    Scope note — this is deliberately about **the platform's own income from
    hosts**, not about hosts as accounts. Anything account-shaped (listings,
    co-hosts, blocked, last active) belongs on Hosts & Users; repeating it here
    is what made the two pages indistinguishable.

    A caveat that has to travel with the numbers: ``StripeCustomer`` records a
    status but not which plan was bought, so an active subscriber's interval is
    unknowable from our tables. MRR therefore values every active subscription
    at the monthly price. Where yearly subscribers exist the true figure is
    lower, so the page states the assumption instead of implying precision we
    do not have.
    """
    now = now or timezone.now()
    today = now.date()
    month_start = _month_start(today)

    setting = PlatformSetting.load()
    price = setting.subscription_price or Decimal('0')

    smap = stripe_map()
    counts = OrderedDict((k, 0) for k in SUBSCRIPTION_LABELS)

    rows = []
    trials_ending, past_due, cancelling, win_back, renewals = [], [], [], [], []
    soon = today + timedelta(days=30)

    for u in hosts_queryset().order_by('-created_at'):
        sc = smap.get(u.id)
        state = classify_subscription(u, sc, now)
        counts[state] += 1
        end = trial_end_for(u)
        renews = sc.current_period_end if sc else None
        pending_cancel = bool(sc and sc.cancel_at_period_end and state in ('active', 'past_due'))

        rows.append({
            'user': u,
            'stripe': sc,
            'state': state,
            'label': SUBSCRIPTION_LABELS.get(state, state),
            'trial_end': end,
            'renews': renews,
            'since': sc.created_at if sc else None,
            'pending_cancel': pending_cancel,
            # Only a live paid subscription can be cancelled or resumed; a
            # trialing or already-expired account has no billing to stop.
            'is_billable': state in ('active', 'past_due'),
            # What this one account contributes to MRR — zero unless it pays.
            'mrr': price if state == 'active' else Decimal('0'),
        })

        # Work queues: the accounts worth acting on, each for a different reason.
        if state == 'past_due':
            past_due.append({'user': u, 'renews': renews})
        if pending_cancel:
            cancelling.append({'user': u, 'renews': renews})
        if state == 'trialing' and end:
            days_left = (end.date() - today).days
            if 0 <= days_left <= 7:
                trials_ending.append({'user': u, 'days_left': days_left, 'trial_end': end})
        if state == 'expired':
            win_back.append({'user': u, 'trial_end': end})
        if state == 'active' and renews and today <= renews.date() <= soon:
            renewals.append({'user': u, 'renews': renews})

    trials_ending.sort(key=lambda r: r['days_left'])
    renewals.sort(key=lambda r: r['renews'])

    active = counts['active']
    mrr = price * active
    # ARPA over paying accounts only. Averaging across trials and comped
    # accounts would drag it below the list price for no useful reason.
    arpa = (mrr / active) if active else Decimal('0')

    new_paid = StripeCustomer.objects.filter(
        subscription_status='active', created_at__date__gte=month_start
    ).count()
    churned = StripeCustomer.objects.filter(
        subscription_status__in=['canceled', 'cancelled'], updated_at__date__gte=month_start
    ).count()

    # Trial conversion counts only trials that have RESOLVED. Including trials
    # still running would depress the rate purely because they haven't finished.
    decided = active + counts['expired'] + counts['canceled']
    conversion = round(active / decided * 100) if decided else None

    return {
        'setting': setting,
        'rows': rows,
        'counts': counts,
        'kpis': {
            'mrr': mrr,
            'arr': mrr * 12,
            'arpa': arpa,
            'active': active,
            'trialing': counts['trialing'],
            'past_due': counts['past_due'],
            'free': counts['free'],
            # Revenue that stops unless someone intervenes: failed payments plus
            # subscriptions already flagged to cancel at period end.
            'at_risk': price * (counts['past_due'] + len(cancelling)),
            'new_paid': new_paid,
            'churned': churned,
            'net_paid': new_paid - churned,
            'conversion': conversion,
            'decided': decided,
        },
        'queues': {
            'past_due': past_due,
            'cancelling': cancelling,
            'trials_ending': trials_ending,
            'win_back': win_back,
            'renewals': renewals,
            'total': len(past_due) + len(cancelling) + len(trials_ending),
        },
    }


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
    # Month-to-date vs the SAME days of last month. Comparing 6 days of August
    # against all 31 days of July would report a collapse every month until the
    # 31st — a partial period must only ever be compared with a partial period.
    mtd_days = (today - month_start).days + 1
    prev_month_end = month_start - timedelta(days=1)
    prev_cutoff = min(prev_month_start + timedelta(days=mtd_days - 1), prev_month_end)

    new_users_this_month = hosts.filter(created_at__date__gte=month_start).count()
    new_users_prev_month = hosts.filter(
        created_at__date__gte=prev_month_start, created_at__date__lte=prev_cutoff
    ).count()

    props = Property.objects.all()
    total_props = props.count()
    active_props = props.filter(status='Active').count()

    bookings = Booking.objects.all()
    total_bookings = bookings.count()
    bookings_this_month = bookings.filter(created_at__date__gte=month_start).count()
    confirmed_bookings = bookings.filter(status='confirmed').count()
    cancelled_bookings = bookings.filter(status='cancelled').count()

    # Money that was actually booked — a cancelled booking is not revenue, and
    # reporting it as such overstates the platform. Cancelled value is carried
    # separately so the dashboard can disclose it rather than hide it.
    live_bookings = bookings.exclude(status='cancelled')
    gross_booking_value = live_bookings.aggregate(t=Sum('price'))['t'] or Decimal('0')
    cancelled_value = bookings.filter(status='cancelled').aggregate(t=Sum('price'))['t'] or Decimal('0')

    live_payments = Payment.objects.exclude(booking__status='cancelled')
    collected = live_payments.filter(is_paid=True).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    outstanding = live_payments.filter(is_paid=False).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    enquiries = Enquiry.objects.all()
    total_enquiries = enquiries.count()
    open_enquiries = enquiries.filter(is_archive=False, is_booked=False).count()

    # ── one pass over all hosts: classify subscription, build the attention
    #    queue, and gather engagement/activation signals ────────────────────
    smap = stripe_map()
    listing_counts = dict(
        Property.objects.values_list('created_by').annotate(n=Count('id'))
    )
    # A listing published by a co-host belongs to that host's account. Counting
    # only created_by == host marked such hosts as "never published a listing".
    cohosts_of = {}
    for host_id, co_host_id in CoHost.objects.values_list('host_id', 'co_host_id'):
        cohosts_of.setdefault(host_id, []).append(co_host_id)

    def listings_for(user_id):
        return listing_counts.get(user_id, 0) + sum(
            listing_counts.get(cid, 0) for cid in cohosts_of.get(user_id, ())
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
        n_listings = listings_for(u.id)
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
            'cancelled_value': float(cancelled_value),
            'collected': float(collected),
            'outstanding': float(outstanding),
            'live_bookings': live_bookings.count(),
            'mtd_days': mtd_days,
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

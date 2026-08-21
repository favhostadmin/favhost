"""The console's section registry — the single source of truth for what a
co-admin can be granted.

Why a registry rather than flags on the model: adding a new console area should
mean adding one row here, not touching a model, a migration, a template and
four views. ``CoAdmin.permissions`` stores plain section keys, so granting a new
area to someone is data, never schema.

Two tiers:

``GRANTABLE``
    Sections the owner can hand to a co-admin individually — the day-to-day
    data areas (a person doing SEO gets Properties; a person doing billing
    support gets Subscriptions and Payments).

``OWNER_ONLY``
    Never grantable, by deliberate decision:

    * ``co_admins`` — whoever can appoint co-admins can grant themselves every
      other section, so making it grantable would collapse the whole permission
      system into "full access".

    Pricing used to be a third entry (``settings``) with its own page. It now
    lives on Subscriptions, which IS grantable — a billing-support co-admin
    needs to see revenue. The section grant therefore buys read access only;
    the price form is owner-gated inside the view itself.

Both are enforced server-side in ``access.py``; the nav merely hides what the
viewer cannot reach. Hiding a link is never the security boundary.
"""

# key, label, icon, one-line description shown next to the permission checkbox
SECTIONS = [
    ('dashboard',     'Dashboard',      'ti-layout-dashboard',      'Platform KPIs, charts and the attention queue.'),
    ('users',         'Hosts & Users',  'ti-users',                 'Host accounts, account health, block/delete powers.'),
    ('properties',    'Properties',     'ti-building-community',    'Every listing on the platform (read-only).'),
    ('enquiries',     'Enquiries',      'ti-message-dots',          'Guest enquiries across all hosts.'),
    ('subscriptions', 'Subscriptions',  'ti-crown',                 'Subscription states, trials and MRR.'),
    ('payments',      'Payments',       'ti-cash',                  'Payment records and revenue totals.'),
    ('seo',           'SEO / Landing',  'ti-world',                 'Edit the text, images and meta tags on the public /home landing page.'),
]

GRANTABLE = [s[0] for s in SECTIONS]

# Reachable only by the platform owner — never offered as a checkbox.
OWNER_ONLY = ('co_admins',)

SECTION_LABELS = {key: label for key, label, _icon, _desc in SECTIONS}

# Where each section lives, so we can send someone to a page they can actually
# open after login instead of bouncing them into a 404.
SECTION_URLS = {
    'dashboard':     'controlpanel:dashboard',
    'users':         'controlpanel:users',
    'properties':    'controlpanel:properties',
    'enquiries':     'controlpanel:enquiries',
    'subscriptions': 'controlpanel:subscriptions',
    'payments':      'controlpanel:payments',
    'seo':           'controlpanel:seo',
}


def clean_permissions(raw):
    """Normalise submitted permissions to known grantable keys, order preserved.

    Anything unrecognised — a stale key from an older release, or a hand-crafted
    POST trying to smuggle in ``settings`` — is dropped rather than stored.
    """
    if not raw:
        return []
    wanted = set(raw)
    return [key for key in GRANTABLE if key in wanted]

"""Turning a stored country name into something a console table can show.

``MyUser.country`` is free text — whatever the profile form's country <select>
submitted. To render a flag next to it we need the ISO-3166 alpha-2 code, which
the platform already holds in ``shared.CountryAndState`` (the same dataset the
signup/profile form is built from). Reading it from there rather than hard-coding
a list means the console can never disagree with the form about what a country
is called.

The map is small (~250 rows) and effectively static, so it is loaded once per
process and cached.
"""
from shared.models import CountryAndState


# The profile form labels a handful of countries differently from the dataset
# (see COUNTRY_NAME_ALIASES in templates/frontend/auth/profile_edit.html). A
# user who picked one of these has the form's label stored, so map it back or
# their flag would silently go missing.
NAME_ALIASES = {
    'eswatini': 'swaziland',
    'gambia': 'gambia the',
    'hong kong': 'hong kong s.a.r.',
    'ivory coast': "cote d'ivoire (ivory coast)",
    'macau': 'macau s.a.r.',
    'north macedonia': 'macedonia',
    'palestine': 'palestinian territory occupied',
    'republic of the congo': 'congo',
    'trinidad and tobago': 'trinidad and tobago',
    'vatican city': 'vatican city state (holy see)',
    # Common short forms people type or that older records carry.
    'usa': 'united states',
    'u.s.a.': 'united states',
    'us': 'united states',
    'u.s.': 'united states',
    'uk': 'united kingdom',
    'u.k.': 'united kingdom',
    'uae': 'united arab emirates',
    'south korea': 'korea south',
    'north korea': 'korea north',
    'russia': 'russian federation',
}

_ISO_BY_NAME = None


def _iso_by_name():
    global _ISO_BY_NAME
    if _ISO_BY_NAME is None:
        rows = CountryAndState.objects.values_list('country_name', 'country_code').distinct()
        _ISO_BY_NAME = {
            (name or '').strip().lower(): (code or '').strip().upper()
            for name, code in rows if name and code
        }
    return _ISO_BY_NAME


def iso2_for(name):
    """ISO alpha-2 for a stored country name, or '' when we can't place it."""
    key = (name or '').strip().lower()
    if not key:
        return ''
    table = _iso_by_name()
    code = table.get(key) or table.get(NAME_ALIASES.get(key, ''), '')
    # A record that already stores the code itself ("US") still deserves a flag.
    if not code and len(key) == 2 and key.isalpha() and key.upper() in set(table.values()):
        code = key.upper()
    return code


def location_cell(user):
    """Everything the console needs to render one host's location cell."""
    country = (getattr(user, 'country', '') or '').strip()
    city = (getattr(user, 'city', '') or '').strip()
    state = (getattr(user, 'state', '') or '').strip()
    return {
        'country': country,
        # Shown as a small code chip rather than a flag emoji: Chrome on Windows
        # renders regional-indicator pairs as bare letters, so a "flag" column
        # would look broken for a large share of viewers.
        'code': iso2_for(country),
        # City is the useful second line; fall back to state when it's all we hold.
        'locality': city or state,
    }


def countries_in_use(qs):
    """Sorted distinct countries actually present on these accounts.

    Drives the filter dropdown — offering all 249 countries when hosts live in
    four of them is the kind of thing that makes a console feel unfinished.
    """
    names = (
        qs.exclude(country__isnull=True).exclude(country__exact='')
        .values_list('country', flat=True).distinct()
    )
    seen = {}
    for n in names:
        key = n.strip()
        if key and key not in seen:
            seen[key] = {'name': key, 'code': iso2_for(key)}
    return [seen[k] for k in sorted(seen, key=str.lower)]

"""
Resolve a hotel/property's IANA timezone from its stored country (and, for the
US, its state) so guest check-in / check-out emails can be fired at *the
property's* local midnight regardless of where the server or host lives.

Resolution order (see ``resolve_timezone``):
    1. US property  -> state-level zone (Eastern/Central/Mountain/Pacific/...)
    2. Country name -> curated representative zone (handles multi-zone countries
       where pytz's first entry is a tiny island rather than the main city).
    3. Country name -> pytz single-zone fallback (correct for most countries).
    4. None (caller falls back to the host's timezone, then UTC).
"""
import pytz

# Country names/aliases that mean "United States" (state precision handled below)
US_ALIASES = {
    'united states', 'united states of america', 'usa', 'us', 'u.s.',
    'u.s.a.', 'america',
}

# US state (full name AND 2-letter code) -> representative IANA zone.
# Zones cover the bulk of each state's population; a handful of split states are
# assigned their majority zone (good enough for a "midnight local" reminder).
US_STATE_TIMEZONES = {
    # Eastern
    'connecticut': 'America/New_York', 'ct': 'America/New_York',
    'delaware': 'America/New_York', 'de': 'America/New_York',
    'district of columbia': 'America/New_York', 'dc': 'America/New_York',
    'florida': 'America/New_York', 'fl': 'America/New_York',
    'georgia': 'America/New_York', 'ga': 'America/New_York',
    'indiana': 'America/New_York', 'in': 'America/New_York',
    'kentucky': 'America/New_York', 'ky': 'America/New_York',
    'maine': 'America/New_York', 'me': 'America/New_York',
    'maryland': 'America/New_York', 'md': 'America/New_York',
    'massachusetts': 'America/New_York', 'ma': 'America/New_York',
    'michigan': 'America/New_York', 'mi': 'America/New_York',
    'new hampshire': 'America/New_York', 'nh': 'America/New_York',
    'new jersey': 'America/New_York', 'nj': 'America/New_York',
    'new york': 'America/New_York', 'ny': 'America/New_York',
    'north carolina': 'America/New_York', 'nc': 'America/New_York',
    'ohio': 'America/New_York', 'oh': 'America/New_York',
    'pennsylvania': 'America/New_York', 'pa': 'America/New_York',
    'rhode island': 'America/New_York', 'ri': 'America/New_York',
    'south carolina': 'America/New_York', 'sc': 'America/New_York',
    'vermont': 'America/New_York', 'vt': 'America/New_York',
    'virginia': 'America/New_York', 'va': 'America/New_York',
    'west virginia': 'America/New_York', 'wv': 'America/New_York',
    # Central
    'alabama': 'America/Chicago', 'al': 'America/Chicago',
    'arkansas': 'America/Chicago', 'ar': 'America/Chicago',
    'illinois': 'America/Chicago', 'il': 'America/Chicago',
    'iowa': 'America/Chicago', 'ia': 'America/Chicago',
    'kansas': 'America/Chicago', 'ks': 'America/Chicago',
    'louisiana': 'America/Chicago', 'la': 'America/Chicago',
    'minnesota': 'America/Chicago', 'mn': 'America/Chicago',
    'mississippi': 'America/Chicago', 'ms': 'America/Chicago',
    'missouri': 'America/Chicago', 'mo': 'America/Chicago',
    'nebraska': 'America/Chicago', 'ne': 'America/Chicago',
    'north dakota': 'America/Chicago', 'nd': 'America/Chicago',
    'oklahoma': 'America/Chicago', 'ok': 'America/Chicago',
    'south dakota': 'America/Chicago', 'sd': 'America/Chicago',
    'tennessee': 'America/Chicago', 'tn': 'America/Chicago',
    'texas': 'America/Chicago', 'tx': 'America/Chicago',
    'wisconsin': 'America/Chicago', 'wi': 'America/Chicago',
    # Mountain
    'colorado': 'America/Denver', 'co': 'America/Denver',
    'idaho': 'America/Denver', 'id': 'America/Denver',
    'montana': 'America/Denver', 'mt': 'America/Denver',
    'new mexico': 'America/Denver', 'nm': 'America/Denver',
    'utah': 'America/Denver', 'ut': 'America/Denver',
    'wyoming': 'America/Denver', 'wy': 'America/Denver',
    # Arizona (no DST)
    'arizona': 'America/Phoenix', 'az': 'America/Phoenix',
    # Pacific
    'california': 'America/Los_Angeles', 'ca': 'America/Los_Angeles',
    'nevada': 'America/Los_Angeles', 'nv': 'America/Los_Angeles',
    'oregon': 'America/Los_Angeles', 'or': 'America/Los_Angeles',
    'washington': 'America/Los_Angeles', 'wa': 'America/Los_Angeles',
    # Alaska / Hawaii
    'alaska': 'America/Anchorage', 'ak': 'America/Anchorage',
    'hawaii': 'Pacific/Honolulu', 'hi': 'Pacific/Honolulu',
}

# Curated representative zone for countries where pytz's first entry is a poor
# default (island/edge zone). Single-zone countries are handled by the pytz
# fallback and don't need to be listed here.
COUNTRY_TIMEZONES = {
    'united states': 'America/New_York',
    'united states of america': 'America/New_York',
    'usa': 'America/New_York',
    'canada': 'America/Toronto',
    'australia': 'Australia/Sydney',
    'brazil': 'America/Sao_Paulo',
    'mexico': 'America/Mexico_City',
    'russia': 'Europe/Moscow',
    'russian federation': 'Europe/Moscow',
    'indonesia': 'Asia/Jakarta',
    'argentina': 'America/Argentina/Buenos_Aires',
    'kazakhstan': 'Asia/Almaty',
    'chile': 'America/Santiago',
    'china': 'Asia/Shanghai',
    'india': 'Asia/Kolkata',
    'united kingdom': 'Europe/London',
    'uk': 'Europe/London',
    'united arab emirates': 'Asia/Dubai',
    'uae': 'Asia/Dubai',
    'new zealand': 'Pacific/Auckland',
    'south africa': 'Africa/Johannesburg',
    'spain': 'Europe/Madrid',
    'malaysia': 'Asia/Kuala_Lumpur',
    'philippines': 'Asia/Manila',
    'singapore': 'Asia/Singapore',
}

# name (lowercased) -> ISO 3166 alpha-2 code, from pytz's own country table.
_NAME2CODE = {name.strip().lower(): code for code, name in pytz.country_names.items()}


def resolve_timezone(country, state=None):
    """Return an IANA timezone string for the given country/state, or None."""
    if not country:
        return None
    ckey = country.strip().lower()

    # 1. US -> state precision
    if ckey in US_ALIASES:
        if state:
            zone = US_STATE_TIMEZONES.get(state.strip().lower())
            if zone:
                return zone
        return 'America/New_York'

    # 2. Curated representative zone
    if ckey in COUNTRY_TIMEZONES:
        return COUNTRY_TIMEZONES[ckey]

    # 3. pytz single-zone fallback (by country name -> code -> zone list)
    code = _NAME2CODE.get(ckey)
    if code:
        zones = pytz.country_timezones.get(code)
        if zones:
            return zones[0]

    return None

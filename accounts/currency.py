"""Currency conversion engine: live FX rates with caching + graceful fallback.

Every monetary value in the platform is stored as **USD** (the canonical base).
This module converts a stored USD amount into whatever currency the viewer is
using and formats it with the correct symbol.

Rates are fetched once a day from a free, key-less API and cached in a JSON
file on disk (``fx_rates_cache.json``) so the last-known-good set survives
restarts and API outages — deliberately NOT a DB table, so the feature needs
no migration. A static table is the final safety net so rendering never crashes.

Public helpers:
    get_rates()                      -> {code: rate}  (1 USD = rate units)
    convert(amount, to, from_='USD') -> Decimal       (quantized to 2dp)
    to_usd(amount, from_)            -> Decimal
    symbol_for(code)                 -> str
    format_money(amount, code)       -> str  (amount already in `code`)
    money(usd_amount, code)          -> str  (convert USD -> code, then format)
    money_raw(usd_amount, code)      -> str  (convert USD -> code, number only)
    refresh_rates(force=False)       -> bool (used by command / celery task)
"""
import logging
import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

BASE_CURRENCY = 'USD'

# Display symbols. Anything not listed falls back to its ISO code (see
# ``symbol_for``), so every option in the profile dropdown is covered.
CURRENCY_SYMBOLS = {
    'USD': '$', 'EUR': '€', 'GBP': '£', 'INR': '₹', 'JPY': '¥', 'CNY': '¥',
    'AUD': 'A$', 'CAD': 'C$', 'KRW': '₩', 'SGD': 'S$', 'HKD': 'HK$',
    'TWD': 'NT$', 'BRL': 'R$', 'RUB': '₽', 'MXN': 'Mex$', 'ZAR': 'R',
    'TRY': '₺', 'AED': 'د.إ', 'SAR': '﷼', 'CHF': 'CHF', 'SEK': 'kr',
    'NOK': 'kr', 'DKK': 'kr', 'PLN': 'zł', 'CZK': 'Kč', 'HUF': 'Ft',
    'RON': 'lei', 'ILS': '₪', 'THB': '฿', 'VND': '₫', 'IDR': 'Rp',
    'MYR': 'RM', 'PHP': '₱', 'PKR': '₨', 'BDT': '৳', 'LKR': 'Rs',
    'NPR': 'रू', 'EGP': 'E£', 'NGN': '₦', 'KES': 'KSh', 'GHS': '₵',
    'MAD': 'DH', 'COP': '$', 'CLP': '$', 'ARS': '$', 'PEN': 'S/',
    'UAH': '₴', 'KZT': '₸', 'GEL': '₾', 'AZN': '₼', 'QAR': '﷼',
    'KWD': 'KD', 'BHD': 'BD', 'OMR': '﷼', 'JOD': 'JD', 'LBP': 'L£',
    'MMK': 'K', 'KHR': '៛', 'LAK': '₭', 'MNT': '₮', 'BGN': 'лв',
    'ISK': 'kr', 'NZD': 'NZ$',
}

# 1 USD = X units. Approximate, used only when the network is unreachable AND
# no cached snapshot exists. Real values come from the live API.
STATIC_FALLBACK_RATES = {
    'USD': 1.0, 'EUR': 0.92, 'GBP': 0.79, 'INR': 83.3, 'JPY': 157.0,
    'CNY': 7.24, 'AUD': 1.51, 'CAD': 1.37, 'KRW': 1370.0, 'SGD': 1.35,
    'HKD': 7.81, 'TWD': 32.4, 'BRL': 5.42, 'RUB': 89.0, 'MXN': 18.6,
    'ZAR': 18.3, 'TRY': 32.3, 'AED': 3.67, 'SAR': 3.75, 'CHF': 0.90,
    'SEK': 10.6, 'NOK': 10.7, 'DKK': 6.87, 'PLN': 3.95, 'CZK': 23.2,
    'HUF': 360.0, 'RON': 4.58, 'ILS': 3.70, 'THB': 36.5, 'VND': 25400.0,
    'IDR': 16200.0, 'MYR': 4.70, 'PHP': 58.5, 'PKR': 278.0, 'BDT': 117.0,
    'LKR': 300.0, 'NPR': 133.0, 'EGP': 47.5, 'NGN': 1500.0, 'KES': 129.0,
    'GHS': 15.0, 'MAD': 9.95, 'UAH': 40.0, 'KZT': 470.0, 'NZD': 1.63,
}

SUPPORTED_CURRENCIES = sorted(CURRENCY_SYMBOLS.keys())

# Curated list offered in the public-site guest currency switcher.
COMMON_CURRENCIES = [
    'USD', 'EUR', 'GBP', 'INR', 'AUD', 'CAD', 'JPY', 'CNY', 'AED', 'SGD',
    'CHF', 'HKD', 'ZAR', 'BRL', 'MXN', 'THB', 'MYR', 'SAR', 'NZD', 'KRW',
]

_PRIMARY_URL = 'https://open.er-api.com/v6/latest/USD'
_FALLBACK_URL = 'https://api.frankfurter.app/latest?from=USD'
_REQUEST_TIMEOUT = 6          # seconds
_MAX_AGE_SECONDS = 24 * 3600  # refresh rates older than a day
_RETRY_THROTTLE_SECONDS = 1800  # don't re-hit a down API more than every 30 min
_CENTS = Decimal('0.01')

# Module-level throttle so a failing API isn't hammered on every request.
_last_attempt = None


# --------------------------------------------------------------------------- #
# Fetching / caching
# --------------------------------------------------------------------------- #
def fetch_live_rates():
    """Return {code: rate} (1 USD = rate) from the live API, or None on failure."""
    # Primary: open.er-api.com — one call, 160+ currencies including TWD/RUB.
    try:
        resp = requests.get(_PRIMARY_URL, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get('result') == 'success' and isinstance(data.get('rates'), dict):
            rates = {k.upper(): float(v) for k, v in data['rates'].items()}
            rates['USD'] = 1.0
            logger.info("Fetched %d exchange rates from open.er-api.com", len(rates))
            return rates
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("Primary FX source failed (%s); trying fallback.", exc)

    # Fallback: Frankfurter (ECB). Does not echo the base, so add USD=1.
    try:
        resp = requests.get(_FALLBACK_URL, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data.get('rates'), dict):
            rates = {k.upper(): float(v) for k, v in data['rates'].items()}
            rates['USD'] = 1.0
            logger.info("Fetched %d exchange rates from frankfurter.app", len(rates))
            return rates
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("Fallback FX source failed (%s).", exc)

    return None


def _cache_path():
    """On-disk JSON cache file for the latest rates (no DB table -> no migrations)."""
    base = getattr(settings, 'BASE_DIR', '.')
    return os.path.join(str(base), 'fx_rates_cache.json')


def _get_snapshot():
    """Return {'rates': {...}, 'fetched_at': datetime} from the cache file, or None."""
    try:
        with open(_cache_path(), 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        rates = data.get('rates')
        if not rates:
            return None
        ts = data.get('fetched_at')
        fetched_at = datetime.fromisoformat(ts) if ts else None
        return {'rates': rates, 'fetched_at': fetched_at}
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.debug("FX cache read failed: %s", exc)
        return None


def _save_snapshot(rates):
    try:
        with open(_cache_path(), 'w', encoding='utf-8') as fh:
            json.dump({'rates': rates, 'fetched_at': timezone.now().isoformat()}, fh)
    except OSError as exc:
        logger.warning("Could not persist exchange rates to %s: %s", _cache_path(), exc)


def _is_stale(snapshot):
    if not snapshot or not snapshot.get('fetched_at'):
        return True
    fetched = snapshot['fetched_at']
    now = timezone.now()
    if fetched.tzinfo is None:  # compare like-for-like if the stored ts was naive
        now = now.replace(tzinfo=None)
    return (now - fetched).total_seconds() > _MAX_AGE_SECONDS


def get_rates():
    """Return the active {code: rate} map (1 USD = rate), refreshing if stale."""
    global _last_attempt
    snapshot = _get_snapshot()
    if snapshot and snapshot['rates'] and not _is_stale(snapshot):
        return snapshot['rates']

    now = timezone.now()
    if _last_attempt is None or (now - _last_attempt).total_seconds() > _RETRY_THROTTLE_SECONDS:
        _last_attempt = now
        fresh = fetch_live_rates()
        if fresh:
            _save_snapshot(fresh)
            return fresh

    if snapshot and snapshot['rates']:
        return snapshot['rates']  # last-known-good
    return dict(STATIC_FALLBACK_RATES)


def refresh_rates(force=False):
    """Fetch + persist fresh rates. Returns True on success. Used by command/task."""
    global _last_attempt
    if not force:
        snapshot = _get_snapshot()
        if snapshot and snapshot['rates'] and not _is_stale(snapshot):
            return True
    _last_attempt = timezone.now()
    fresh = fetch_live_rates()
    if fresh:
        _save_snapshot(fresh)
        return True
    return False


# --------------------------------------------------------------------------- #
# Conversion / formatting
# --------------------------------------------------------------------------- #
def _to_decimal(value):
    if value is None or value == '':
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')


def _rate_for(rates, code):
    """1 USD = X units of `code`. Falls back to static, then 1 (treat as USD)."""
    code = (code or BASE_CURRENCY).upper()
    value = rates.get(code)
    if value is None:
        value = STATIC_FALLBACK_RATES.get(code, 1.0)
    return _to_decimal(value) or Decimal('1')


def convert(amount, to_currency, from_currency=BASE_CURRENCY):
    """Convert `amount` from one currency to another. Returns a 2dp Decimal."""
    amount = _to_decimal(amount)
    to_currency = (to_currency or BASE_CURRENCY).upper()
    from_currency = (from_currency or BASE_CURRENCY).upper()
    if to_currency == from_currency:
        return amount.quantize(_CENTS, rounding=ROUND_HALF_UP)
    rates = get_rates()
    usd = amount / _rate_for(rates, from_currency)
    result = usd * _rate_for(rates, to_currency)
    return result.quantize(_CENTS, rounding=ROUND_HALF_UP)


def to_usd(amount, from_currency):
    """Convert a host-entered amount (in `from_currency`) back to the USD base."""
    return convert(amount, BASE_CURRENCY, from_currency)


def symbol_for(code):
    code = (code or BASE_CURRENCY).upper()
    return CURRENCY_SYMBOLS.get(code, code)


def format_money(amount, code):
    """Format an amount that is ALREADY in `code`, with grouping + symbol."""
    code = (code or BASE_CURRENCY).upper()
    amount = _to_decimal(amount).quantize(_CENTS, rounding=ROUND_HALF_UP)
    formatted = f"{amount:,.2f}"
    symbol = CURRENCY_SYMBOLS.get(code)
    if symbol:
        return f"{symbol}{formatted}"
    return f"{formatted} {code}"  # unknown symbol -> append code (e.g. "9.99 SEK")


def money(usd_amount, code):
    """Convert a stored USD amount to `code` and format it for display."""
    return format_money(convert(usd_amount, code), code)


def money_raw(usd_amount, code):
    """Convert a stored USD amount to `code`; return the bare number (for JS/inputs)."""
    return f"{convert(usd_amount, code):.2f}"


def resolve_display_currency(requested, fallback):
    """Pick a valid display currency: the requested one if known, else the fallback."""
    rates = get_rates()
    code = (requested or '').upper()
    if code and code in rates:
        return code
    code = (fallback or BASE_CURRENCY).upper()
    return code if code in rates else BASE_CURRENCY


def display_context(code):
    """Template-context dict for a given display currency (used by public views)."""
    code = (code or BASE_CURRENCY).upper()
    return {
        'display_currency': code,
        'currency_symbol': symbol_for(code),
        'currency_rate': float(convert(1, code)),
        'currency_options': COMMON_CURRENCIES,
    }

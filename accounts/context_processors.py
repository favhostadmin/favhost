"""Inject the viewer's display currency into every template.

Resolution here is the *default* used on host-facing pages:
    authenticated -> user's profile currency; otherwise -> USD.
Public host-site views override these keys with the guest-selected currency.
"""
from .currency import BASE_CURRENCY, convert, symbol_for


def currency_context(request):
    code = BASE_CURRENCY
    user = getattr(request, 'user', None)
    if user is not None and getattr(user, 'is_authenticated', False):
        code = (getattr(user, 'currency', None) or BASE_CURRENCY).upper()
    return {
        'display_currency': code,
        'currency_symbol': symbol_for(code),
        # 1 USD expressed in the display currency, for any JS that still holds
        # a raw-USD value (most templates inject pre-converted values instead).
        'currency_rate': float(convert(1, code)),
    }

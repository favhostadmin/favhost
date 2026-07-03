"""Template tags for rendering money in the viewer's display currency.

Stored amounts are USD. ``{% money X %}`` converts USD -> display currency and
formats it with the symbol; ``{% money_raw X %}`` returns just the converted
number (for JS booking calculators and form ``value=`` prefills).

Usage:
    {% load currency_tags %}
    {% money property.price_per_night %}        -> ₹9,400.00
    parseFloat("{% money_raw property.price_per_night %}")  -> 9400.00
"""
from django import template

from accounts import currency as cur

register = template.Library()


def _ctx_currency(context):
    """Resolve the active display currency from context (view override or user)."""
    code = context.get('display_currency')
    if not code:
        request = context.get('request')
        user = getattr(request, 'user', None) if request else None
        if user is not None and getattr(user, 'is_authenticated', False):
            code = getattr(user, 'currency', None)
    return (code or cur.BASE_CURRENCY).upper()


@register.simple_tag(takes_context=True)
def money(context, amount):
    """USD amount -> 'symbol + grouped value' in the display currency."""
    return cur.money(amount, _ctx_currency(context))


@register.simple_tag(takes_context=True)
def money_raw(context, amount):
    """USD amount -> bare converted number (no symbol/grouping) for JS & inputs."""
    return cur.money_raw(amount, _ctx_currency(context))

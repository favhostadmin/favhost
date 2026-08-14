"""Small template helpers for the owner console."""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def page_link(context, page_number):
    """A link to ``page_number`` that keeps every other query parameter.

    The pagination partial used to re-list the filter names by hand, which meant
    every new filter silently reset itself the moment the owner clicked page 2.
    Copying the real querystring keeps any current and future filter intact.
    """
    request = context.get('request')
    if request is None:  # no request context processor — still emit a usable link
        return f'?page={page_number}'
    params = request.GET.copy()
    params['page'] = page_number
    return f'?{params.urlencode()}'

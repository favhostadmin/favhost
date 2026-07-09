"""Project-wide middleware."""

from django.shortcuts import render


class CustomPageNotFoundMiddleware:
    """Render the branded ``404.html`` for browser navigations to a missing URL.

    Django only uses ``templates/404.html`` when ``DEBUG=False``; with
    ``DEBUG=True`` (local + our dev server) it shows the yellow technical 404
    page instead. This middleware fills that gap so a mistyped/broken URL shows
    our on-brand "page not found" page in *every* environment.

    It only touches genuine navigational 404s. API, AJAX and non-HTML clients
    (which expect JSON / raw content) are left with their original response, and
    the admin keeps its own 404 page.
    """

    #: URL prefixes whose 404s we must not rewrite into an HTML page.
    SKIP_PREFIXES = ('/api/', '/admin/', '/static/', '/media/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if response.status_code != 404:
            return response

        if request.path.startswith(self.SKIP_PREFIXES):
            return response

        # AJAX / fetch callers handle the 404 status themselves; don't hand
        # them an HTML body they'd try to parse.
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return response

        # Only browser navigations that actually want HTML.
        accept = request.headers.get('Accept', '')
        if 'text/html' not in accept and '*/*' not in accept:
            return response

        return render(request, '404.html', status=404)

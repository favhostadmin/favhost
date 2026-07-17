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


class NoCacheAuthenticatedHTMLMiddleware:
    """Stop browsers from serving cached HTML pages to logged-in users.

    The subscription/trial paywall (``show_subscription_wall``) is rendered
    server-side into ``base.html`` on every request. But without explicit
    cache headers a browser will happily reuse a cached / back-forward-cache
    snapshot of a page on normal navigation — a snapshot captured *while the
    subscription was still active* — so the wall never appears until a hard
    refresh forces a fresh server render.

    Sending ``no-store`` on authenticated HTML responses forces the browser to
    re-fetch from the server on every navigation (and on back/forward), which
    re-runs the subscription check and shows the wall the moment access lapses.
    Only HTML pages for logged-in users are touched; static, media, API/JSON
    and file downloads (xlsx/csv exports) are left with their own caching.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return response

        content_type = response.get('Content-Type', '')
        if 'text/html' not in content_type:
            return response

        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private, max-age=0'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response

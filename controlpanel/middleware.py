"""Records public page views for the owner console's audience report.

Cheap by construction: one INSERT for anonymous HTML GETs only. Everything
else — signed-in traffic, the console itself, static/media, AJAX, redirects,
errors, non-GET — returns before touching the database. Any failure here is
swallowed: traffic logging must never be the reason a page breaks.
"""
import hashlib
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

# Paths that are never "site traffic".
SKIP_PREFIXES = (
    '/console', '/admin', '/static', '/media', '/billing',
    '/favicon', '/robots.txt', '/sitemap',
)


def client_ip(request):
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded or request.META.get('REMOTE_ADDR') or ''


def visitor_key(request):
    """A stable pseudonymous id for one visitor.

    Derived from IP + device, hashed one-way with the site secret so it can
    never be turned back into an address. It does NOT rotate, so the same
    person keeps the same id across days — which is what makes "unique
    visitors" a true count over any period rather than visits-per-day added up.

    Still no cookie and no stored personal data, but note this IS a persistent
    identifier: it is the deliberate trade for an accurate visitor count.
    """
    raw = '|'.join([
        client_ip(request),
        request.META.get('HTTP_USER_AGENT', '')[:200],
        settings.SECRET_KEY,
    ])
    return hashlib.sha256(raw.encode('utf-8', 'ignore')).hexdigest()[:32]


class PageViewMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            if self._should_record(request, response):
                self._record(request)
        except Exception:
            pass
        return response

    @staticmethod
    def _should_record(request, response):
        if request.method != 'GET' or response.status_code != 200:
            return False
        # A signed-in user is a host using the product, not a site visitor.
        if getattr(request, 'user', None) and request.user.is_authenticated:
            return False
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return False
        if 'text/html' not in (response.get('Content-Type') or ''):
            return False
        return not request.path.startswith(SKIP_PREFIXES)

    @staticmethod
    def _record(request):
        from .models import PageView

        referrer = urlparse(request.META.get('HTTP_REFERER') or '').netloc.lower()
        if referrer.startswith('www.'):
            referrer = referrer[4:]
        # Our own pages are not a referral source.
        if referrer and referrer.split(':')[0] == request.get_host().split(':')[0].replace('www.', ''):
            referrer = ''

        PageView.objects.create(
            path=request.path[:300],
            visitor_key=visitor_key(request),
            referrer_host=referrer[:200],
        )

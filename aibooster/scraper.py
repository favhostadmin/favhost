"""Fetch a listing page and pull out its photos.

Everything here takes a user-supplied URL, so every request goes through
safe_get(), which refuses anything that resolves to a private / loopback /
link-local address (SSRF) and re-checks each redirect hop.
"""
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TIMEOUT = 10
MAX_IMAGES = 10
MAX_REDIRECTS = 5
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'
)
_SKIP_HINTS = ('logo', 'icon', 'sprite', 'avatar', 'favicon', 'placeholder', 'pixel', 'badge', 'flag')
_SKIP_EXT = ('.svg', '.gif', '.ico')


class UnsafeURL(Exception):
    pass


def _check_public(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise UnsafeURL('Only http(s) URLs are allowed.')
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
    except socket.gaierror as exc:
        raise UnsafeURL('Host could not be resolved.') from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise UnsafeURL('Host is not a public address.')


def _follow(url):
    """Open `url` as a stream, following redirects manually (re-checking every hop).

    Returns (response, final_url); the caller reads or closes the response.
    """
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html,image/*;q=0.9,*/*;q=0.5'}
    for _ in range(MAX_REDIRECTS + 1):
        _check_public(url)
        resp = requests.get(url, headers=headers, timeout=TIMEOUT, stream=True, allow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, resp.headers.get('Location', ''))
            resp.close()
            continue
        resp.raise_for_status()
        return resp, url
    raise ValueError('Too many redirects.')


def _read(resp, max_bytes):
    chunks, size = [], 0
    for chunk in resp.iter_content(64 * 1024):
        size += len(chunk)
        if size > max_bytes:
            resp.close()
            raise ValueError('Response too large.')
        chunks.append(chunk)
    return b''.join(chunks)


def safe_get(url, max_bytes):
    """GET `url` (streamed, size-capped), following redirects manually.

    Returns (body bytes, content-type, encoding). Raises UnsafeURL /
    requests exceptions / ValueError on any problem.
    """
    resp, _final = _follow(url)
    return _read(resp, max_bytes), resp.headers.get('Content-Type', ''), resp.encoding


def _largest_from_srcset(srcset):
    best, best_w = '', -1
    for part in srcset.split(','):
        bits = part.strip().split()
        if not bits:
            continue
        try:
            width = int(bits[1].rstrip('wx')) if len(bits) > 1 else 0
        except ValueError:
            width = 0
        if width > best_w:
            best, best_w = bits[0], width
    return best


def _looks_like_photo(url):
    low = url.lower().split('?')[0]
    if low.endswith(_SKIP_EXT) or low.startswith('data:'):
        return False
    return not any(hint in low for hint in _SKIP_HINTS)


def scrape_images(page_url):
    """Return up to MAX_IMAGES photo URLs from `page_url` (or the URL itself if it is a
    direct image link), or [] on any failure."""
    try:
        resp, final_url = _follow(page_url)
        if (resp.headers.get('Content-Type') or '').lower().startswith('image/'):
            # The link IS a photo (e.g. a direct image address copied from a listing): use it as-is.
            resp.close()
            return [final_url]
        body, encoding = _read(resp, MAX_PAGE_BYTES), resp.encoding
        soup = BeautifulSoup(body.decode(encoding or 'utf-8', errors='replace'), 'html.parser')
        candidates = []
        for meta in soup.find_all('meta'):
            if meta.get('property') in ('og:image', 'og:image:url') or meta.get('name') == 'twitter:image':
                candidates.append(meta.get('content', ''))
        for img in soup.find_all('img'):
            srcset = img.get('srcset') or img.get('data-srcset') or ''
            candidates.append(
                _largest_from_srcset(srcset) if srcset
                else img.get('src') or img.get('data-src') or img.get('data-lazy-src') or ''
            )
        found, seen = [], set()
        for raw in candidates:
            raw = (raw or '').strip()
            if not raw:
                continue
            absolute = urljoin(page_url, raw)
            if absolute in seen or not _looks_like_photo(absolute):
                continue
            seen.add(absolute)
            found.append(absolute)
            if len(found) >= MAX_IMAGES:
                break
        return found
    except Exception:
        logger.warning('Photo Enhancer: scraping %s failed', page_url, exc_info=True)
        return []


# ── Listing Optimize: listing details ──────────────────────────────────────────
# Everything below is additive; the image functions above are unchanged.
import json
import re

from django.urls import Resolver404, resolve

OWN_HOSTS = {'favhost.com', 'www.favhost.com'}
MIN_FIELDS = 3  # fewer than this many populated fields = "almost nothing"
_DETAIL_FIELDS = ('title', 'description', 'property_type', 'amenities', 'guests', 'bedrooms', 'beds',
                  'bathrooms', 'price', 'rating', 'review_count', 'house_rules', 'location')


def empty_listing(url='', platform='other'):
    """Every field present and null: the model is never handed a gap it might fill with a guess."""
    data = {'source_url': url or None, 'platform': platform}
    data.update({name: None for name in _DETAIL_FIELDS})
    data['currency'] = None
    data['image_urls'] = []
    return data


def populated_count(data):
    return sum(1 for name in _DETAIL_FIELDS if data.get(name) not in (None, '', [], {}))


def is_sparse(data):
    return populated_count(data) < MIN_FIELDS or not (data.get('title') or data.get('description'))


def detect_platform(url, extra_hosts=()):
    host = (urlparse(url).hostname or '').lower()
    own = OWN_HOSTS | {h.lower() for h in extra_hosts if h}
    if host in own:
        return 'favhost'
    if host == 'airbnb.com' or host.startswith('airbnb.') or '.airbnb.' in host:
        return 'airbnb'
    if host == 'booking.com' or host.endswith('.booking.com'):
        return 'booking'
    return 'other'


def _clean(value, limit=6000):
    if value is None:
        return None
    text = re.sub(r'\s+', ' ', str(value)).strip()
    return text[:limit] or None


def _num(value):
    try:
        number = float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _walk(node):
    """Yield every dict inside a parsed JSON-LD document."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


_LISTING_TYPES = {'lodgingbusiness', 'hotel', 'hostel', 'bedandbreakfast', 'apartment', 'house', 'resort',
                  'vacationrental', 'accommodation', 'product', 'singlefamilyresidence', 'room', 'suite',
                  'campground', 'motel'}


def _jsonld_blocks(soup):
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            yield from _walk(json.loads(tag.string or tag.get_text() or ''))
        except ValueError:
            continue


def _types(block):
    raw = block.get('@type')
    raw = raw if isinstance(raw, list) else [raw]
    return {str(t).lower() for t in raw if t}


def _from_jsonld(soup, data):
    for block in _jsonld_blocks(soup):
        if not (_types(block) & _LISTING_TYPES):
            continue
        data['title'] = data['title'] or _clean(block.get('name'), 300)
        data['description'] = data['description'] or _clean(block.get('description'))
        rating = block.get('aggregateRating')
        if isinstance(rating, dict):
            if data['rating'] is None:
                data['rating'] = _num(rating.get('ratingValue'))
            if data['review_count'] is None:
                data['review_count'] = _num(rating.get('reviewCount') or rating.get('ratingCount'))
        offers = block.get('offers')
        offers = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offers, dict) and data['price'] is None:
            data['price'] = _num(offers.get('price') or offers.get('lowPrice'))
            if data['price'] is not None:
                data['currency'] = _clean(offers.get('priceCurrency'), 8)
        features = block.get('amenityFeature')
        if isinstance(features, list) and not data['amenities']:
            names = [_clean(f.get('name'), 120) for f in features
                     if isinstance(f, dict) and f.get('value') in (None, True, 'true', 'True')]
            data['amenities'] = [n for n in names if n] or None
        address = block.get('address')
        if isinstance(address, dict) and not data['location']:
            parts = [address.get(k) for k in ('addressLocality', 'addressRegion', 'addressCountry')]
            data['location'] = _clean(', '.join(str(p) for p in parts if p and not isinstance(p, dict)), 300)
        if data['bedrooms'] is None:
            data['bedrooms'] = _num(block.get('numberOfBedrooms') or block.get('numberOfRooms'))
        if data['bathrooms'] is None:
            data['bathrooms'] = _num(block.get('numberOfBathroomsTotal'))
        occupancy = block.get('occupancy')
        if isinstance(occupancy, dict) and data['guests'] is None:
            data['guests'] = _num(occupancy.get('maxValue') or occupancy.get('value'))
        images = block.get('image')
        images = images if isinstance(images, list) else [images]
        for img in images:
            img = img.get('url') if isinstance(img, dict) else img
            if isinstance(img, str) and img not in data['image_urls']:
                data['image_urls'].append(img)


def _meta(soup, **attrs):
    tag = soup.find('meta', attrs=attrs)
    return _clean(tag.get('content')) if tag and tag.get('content') else None


_COUNT_PATTERNS = (
    ('guests', r'(\d+)\+?\s+guests?'),
    ('bedrooms', r'(\d+)\s+bedrooms?'),
    ('beds', r'(\d+)\s+beds?\b'),
    ('bathrooms', r'(\d+(?:\.\d+)?)\s+(?:private\s+|shared\s+)?baths?(?:rooms?)?'),
)


def _counts_from_text(text, data):
    """Pick 'N guests / bedrooms / beds / baths' out of short summary text only."""
    for key, pattern in _COUNT_PATTERNS:
        if data[key] is None:
            m = re.search(pattern, text, re.I)
            if m:
                data[key] = _num(m.group(1))


_HEADINGS = ['h1', 'h2', 'h3', 'h4', 'h5']


def _section_after_heading(soup, names, as_list=False):
    """Text (or list items) that follow a heading such as 'House rules'."""
    for heading in soup.find_all(_HEADINGS):
        title = heading.get_text(' ', strip=True).lower()
        if not any(title.startswith(n) for n in names):
            continue
        if as_list:
            container = heading.find_next(['ul', 'ol'])
            items = [_clean(li.get_text(' ', strip=True), 120) for li in (container.find_all('li') if container else [])]
            items = [i for i in items if i]
            if items:
                return items[:80]
            continue
        parts = []
        for sib in heading.find_next_siblings(limit=8):
            if sib.name in _HEADINGS:
                break
            parts.append(sib.get_text(' ', strip=True))
        text = _clean(' '.join(parts), 3000)
        if text:
            return text
    return None


def _find_key(node, key):
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_key(item, key)
            if found is not None:
                return found
    return None


def _ugc(node):
    """Airbnb wraps text as {localizedString: ...} (sometimes inside 'content' / 'text')."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        for key in ('localizedString', 'localizedStringWithTranslationPreference', 'text', 'source'):
            if isinstance(node.get(key), str):
                return node[key]
        for key in ('content', 'ugcContent'):
            if key in node:
                return _ugc(node[key])
    return None


def _html_text(value):
    if not value:
        return None
    text = BeautifulSoup(value.replace('<br />', '\n').replace('<br>', '\n'), 'html.parser').get_text()
    text = re.sub(r'[ \t \xa0]+', ' ', text.replace('\r', ''))
    return re.sub(r'\n{3,}', '\n\n', text).strip()[:6000] or None


def _rule_groups(section):
    """Flatten Airbnb's 'House rules' / 'Safety & property' groups into readable lines."""
    lines = []
    for group in (section or {}).get('groupItems') or []:
        for item in group.get('items') or []:
            line = _clean(item.get('title'), 200)
            detail = _clean(_ugc(item.get('description')), 400)
            if line:
                lines.append(f'{line} ({detail})' if detail else line)
    return ' | '.join(lines)[:3000] or None


def _from_airbnb_state(soup, data):
    """Airbnb's page carries the full listing as JSON inside a script tag."""
    for tag in soup.find_all('script'):
        raw = tag.string or ''
        if 'pdpPresentation' not in raw:
            continue
        try:
            pdp = _find_key(json.loads(raw), 'pdpPresentation')
        except ValueError:
            continue
        if not isinstance(pdp, dict) or 'descriptions' not in pdp:
            continue  # another script's smaller 'pdpPresentation' (e.g. pet policy only)
        try:
            data['title'] = _clean(_ugc((pdp.get('title') or {}).get('content')), 300) or data['title']
            data['description'] = _html_text(_ugc(((pdp.get('descriptions') or {}).get('longDescriptionHtml')))) \
                or data['description']
            groups = (pdp.get('amenities') or {}).get('seeAllAmenitiesGroups') or []
            names = [_clean(a.get('title'), 120) for g in groups for a in g.get('amenities') or []
                     if a.get('available') is not False]
            data['amenities'] = [n for n in dict.fromkeys(names) if n] or data['amenities']
            overview = pdp.get('overview') or {}
            kind = (overview.get('title') or '').split(' in ')[0]
            data['property_type'] = _clean(kind, 80) if ' in ' in (overview.get('title') or '') else data['property_type']
            _counts_from_text(' '.join(str(i) for i in overview.get('items') or []), data)
            if data['guests'] is None:
                data['guests'] = _num(pdp.get('personCapacity'))
            data['house_rules'] = _rule_groups(pdp.get('rules')) or data['house_rules']
            safety = _rule_groups(pdp.get('safetyAndProperty'))
            if safety:
                data['safety_and_property'] = safety
            location = pdp.get('location') or {}
            data['location'] = _clean(location.get('subtitle'), 300) or data['location']
            about = ' '.join(filter(None, (_ugc(d.get('content')) for d in location.get('previewLocationDetails') or []
                                           if isinstance(d, dict))))
            if about:
                data['location_description'] = _html_text(about)
            highlights = [_clean(_ugc(h.get('headline')), 200) for h in pdp.get('highlights') or [] if isinstance(h, dict)]
            if any(highlights):
                data['highlights'] = [h for h in highlights if h]
        except Exception:
            logger.warning('Listing Optimize: Airbnb state parse failed', exc_info=True)
        return


def parse_listing(html, url, platform):
    """Pure parsing step (no network): HTML -> the listing dict, missing fields null."""
    data = empty_listing(url, platform)
    soup = BeautifulSoup(html, 'html.parser')
    if platform == 'airbnb':
        _from_airbnb_state(soup, data)
    _from_jsonld(soup, data)

    h1 = soup.find('h1')
    data['title'] = (data['title'] or _meta(soup, property='og:title')
                     or (_clean(h1.get_text(' ', strip=True), 300) if h1 else None))
    summary = _meta(soup, property='og:description') or _meta(soup, name='description')
    data['description'] = data['description'] or summary
    if data['title'] and data['title'] == data['description']:
        data['description'] = None

    _counts_from_text(' '.join(t for t in (summary, data['title']) if t), data)
    data['amenities'] = data['amenities'] or _section_after_heading(
        soup, ('amenities', 'facilities', 'most popular facilities', 'what this place offers'), as_list=True)
    data['house_rules'] = data['house_rules'] or _section_after_heading(soup, ('house rules',))
    for name in ('og:image', 'og:image:url'):
        img = _meta(soup, property=name)
        if img:
            data['image_urls'].append(urljoin(url, img))
    for img in soup.find_all('img'):
        raw = (img.get('data-src') or img.get('src') or '').strip()
        absolute = urljoin(url, raw) if raw else ''
        if absolute and _looks_like_photo(absolute):
            data['image_urls'].append(absolute)
    data['image_urls'] = [u[:500] for u in dict.fromkeys(data['image_urls'])][:MAX_IMAGES]
    return data


def scrape_listing(url, platform):
    """Fetch and parse a listing page. Returns the listing dict (all-null on any failure)."""
    try:
        body, _ctype, encoding = safe_get(url, MAX_PAGE_BYTES)
        html = body.decode(encoding or 'utf-8', errors='replace')
        # Airbnb answers www.airbnb.com with a tiny page that auto-submits a form to the visitor's
        # regional domain; the real listing lives there.
        handoff = re.search(r'action="https://([a-z0-9.-]+)/v2/domain_switch/handoff"', html)
        if handoff and platform == 'airbnb' and detect_platform(f'https://{handoff.group(1)}/') == 'airbnb':
            parts = urlparse(url)
            url = parts._replace(netloc=handoff.group(1)).geturl()
            body, _ctype, encoding = safe_get(url, MAX_PAGE_BYTES)
            html = body.decode(encoding or 'utf-8', errors='replace')
        return parse_listing(html, url, platform)
    except Exception:
        logger.warning('Listing Optimize: scraping %s failed', url, exc_info=True)
        return empty_listing(url, platform)


def manual_listing(text, url='', platform='other'):
    """Wrap hand-pasted details; the model reads the text as-is."""
    data = empty_listing(url, platform)
    text = re.sub(r'[ \t]+', ' ', (text or '').replace('\r', '')).strip()
    data['manual_text'] = re.sub(r'\n{3,}', '\n\n', text)[:12000]
    return data


def read_own_listing(url):
    """Read a FavHost listing from the local DB (public fields only). None if it isn't a public listing."""
    try:
        match = resolve(urlparse(url).path)
    except Resolver404:
        return None
    from property.models import Property
    qs = Property.objects.filter(created_by__is_active=True, status='Active').prefetch_related('amenities', 'images')
    kwargs = match.kwargs
    try:
        if match.url_name == 'listing-detail-slug':
            prop = qs.filter(slug=kwargs['slug'], created_by__short_code=kwargs['short_code']).first()
        elif match.url_name == 'request-book-page-slug':
            prop = qs.filter(slug=kwargs['slug']).first()
        elif match.url_name == 'request-book-page-detail':
            prop = qs.filter(pk=kwargs['pk']).first()
        else:
            return None
    except Exception:
        logger.warning('Listing Optimize: own-listing lookup failed for %s', url, exc_info=True)
        return None
    if not prop:
        return None

    data = empty_listing(url, 'favhost')
    data['title'] = _clean(prop.title, 300)
    data['description'] = _clean(prop.description)
    data['property_type'] = prop.get_property_type_display() or None
    data['guests'] = prop.guest or None
    # This platform records bathroom/bed *types*, not counts, so they stay as labelled facts.
    data['bathrooms'] = {'bathroom_type': prop.bathroom_type} if prop.bathroom_type else None
    data['beds'] = {'bed_type': prop.bed_type} if prop.bed_type else None
    data['price'] = float(prop.price_per_night) if prop.price_per_night is not None else None
    data['amenities'] = [a.name for a in prop.amenities.all()] or None
    data['house_rules'] = _clean(prop.house_rules)
    data['location'] = _clean(', '.join(p for p in (prop.city, prop.state, prop.country) if p), 300)
    # Extras this platform has that OTAs don't; public, non-sensitive fields only.
    data['minimum_nights'] = prop.minimum_booking
    data['check_in_time'] = prop.check_in_time.strftime('%H:%M') if prop.check_in_time else None
    data['check_out_time'] = prop.check_out_time.strftime('%H:%M') if prop.check_out_time else None
    data['cleaning_fee'] = float(prop.cleaning_fee) if prop.cleaning_fee else None
    data['cancellation_policy'] = _clean(prop.cancellation_policy)
    for image in prop.images.all()[:MAX_IMAGES]:
        try:
            data['image_urls'].append(image.image.url)
        except Exception:
            continue
    return data

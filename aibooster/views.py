import json
import logging
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import imaging, scraper, storage
from .models import BoosterLead, ImageJob, ListingReport
from .tasks import dispatch, dispatch_report

logger = logging.getLogger(__name__)

DAILY_LIMIT = 50
# Anonymous visitors cost real money and can mint new sessions by clearing cookies,
# so they are also capped per IP address.
ANON_IP_DAILY_LIMIT = 50
MAX_PER_SUBMIT = 25
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
DOWNLOAD_LINK_MAX_AGE = 300  # seconds
UNLOCK_SESSION_KEY = 'aibooster_unlocked'
BATCH_SESSION_KEY = 'aibooster_batch'  # ids of the most recent submission
LEAD_SESSION_KEY = 'aibooster_lead_given'  # visitor already gave name+email this session
DOWNLOAD_SALT = 'aibooster.download'
_EXT_BY_FORMAT = {'JPEG': 'jpg', 'MPO': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}


# ── helpers ────────────────────────────────────────────────────────────────

def _session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _used_today(session_key):
    since = timezone.now() - timedelta(days=1)
    return (ImageJob.objects.filter(session_key=session_key, created_at__gte=since)
            .exclude(status=ImageJob.STATUS_HELD).count())


SAMPLES_DIR = Path(__file__).resolve().parent / 'static' / 'aibooster' / 'samples'


def _samples():
    """Before/after showcase pairs found in static/aibooster/samples/.

    Drop in `<name>-before.jpg` + `<name>-after.jpg` (optionally prefixed `01-` to
    set the order) and they appear in the hero slider and the gallery. The page
    shows nothing fake when the folder is empty.
    """
    pairs = []
    if SAMPLES_DIR.is_dir():
        for before in sorted(SAMPLES_DIR.glob('*-before.*')):
            stem = before.name.rsplit('-before', 1)[0]
            after = next(iter(sorted(SAMPLES_DIR.glob(f'{stem}-after.*'))), None)
            if not after:
                continue
            label = stem.lstrip('0123456789').lstrip('-_ ') or stem
            pairs.append({
                'label': label.replace('-', ' ').replace('_', ' ').title(),
                'before': f'aibooster/samples/{before.name}',
                'after': f'aibooster/samples/{after.name}',
            })
    return pairs


def _base_template(request):
    """Logged-in hosts get the app layout; visitors from the landing page get the public one."""
    return 'frontend/base/base.html' if request.user.is_authenticated else 'aibooster/public_base.html'


def _ip_used_today(ip):
    if not ip:
        return 0
    since = timezone.now() - timedelta(days=1)
    return (ImageJob.objects.filter(ip_address=ip, created_at__gte=since)
            .exclude(status=ImageJob.STATUS_HELD).count())


def _unlocked_ids(request):
    return set(request.session.get(UNLOCK_SESSION_KEY, []))


def _batch_jobs(request):
    """Jobs of this session's most recent submission, in submission order."""
    ids = request.session.get(BATCH_SESSION_KEY, [])
    if not ids:
        return []
    try:
        jobs = list(ImageJob.objects.filter(pk__in=ids, session_key=_session_key(request)))
    except (ValidationError, ValueError):
        return []
    order = {i: n for n, i in enumerate(ids)}
    return sorted(jobs, key=lambda j: order.get(str(j.id), 0))


def _client_ip(request):
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded or request.META.get('REMOTE_ADDR') or None


def _payload(job, unlocked):
    data = {
        'id': str(job.id),
        'status': job.status,
        'error': job.error if job.status == ImageJob.STATUS_FAILED else '',
        'before_url': reverse('aibooster:image-before', args=[job.id]),
        # Scraped photos are only saved once the worker starts, so the page must not ask for the
        # original before it exists (that was the broken BEFORE image).
        'has_before': bool(job.original_key),
        'unlocked': str(job.id) in unlocked,
    }
    if job.status == ImageJob.STATUS_DONE:
        data['after_url'] = reverse('aibooster:image-after', args=[job.id])
    return data


def _owned_job(request, job_id):
    try:
        return ImageJob.objects.get(pk=job_id, session_key=_session_key(request))
    except ImageJob.DoesNotExist:
        raise Http404


def _stream(key, filename=None):
    try:
        response = FileResponse(storage.get_storage().open(key, 'rb'), content_type='image/jpeg',
                                as_attachment=bool(filename), filename=filename)
    except Exception:
        raise Http404
    response['Cache-Control'] = 'private, no-store'
    return response


def _store_upload(upload, job_id):
    """Validate an uploaded file and save it as the job's original. Returns the key or None."""
    if upload.size > MAX_UPLOAD_BYTES:
        return None
    data = upload.read()
    try:
        fmt = imaging.image_format(data)
        imaging.open_image(data)
    except Exception:
        return None
    return storage.save_bytes(storage.new_key(job_id, 'original', _EXT_BY_FORMAT.get(fmt, 'img')), data)


# ── pages ──────────────────────────────────────────────────────────────────

def image_page(request):
    key = _session_key(request)
    unlocked = _unlocked_ids(request)
    jobs = _batch_jobs(request)
    return render(request, 'aibooster/image_booster.html', {
        'jobs_json': [_payload(j, unlocked) for j in jobs],
        'base_template': _base_template(request),
        'samples': _samples(),
        'daily_limit': DAILY_LIMIT,
        'remaining': max(DAILY_LIMIT - _used_today(key), 0),
        'max_per_submit': MAX_PER_SUBMIT,
    })


def report_page(request):
    key = _session_key(request)
    return render(request, 'aibooster/boost_report.html', {
        'base_template': _base_template(request),
        'report_daily_limit': REPORT_DAILY_LIMIT,
        'report_remaining': max(REPORT_DAILY_LIMIT - _reports_today(key), 0),
        'report_json': _report_payload(_latest_report(request)),
    })


# ── start / poll ───────────────────────────────────────────────────────────

@require_POST
def image_start(request):
    """Create jobs from a listing URL and/or uploaded files. Always answers 200 JSON
    so the page can fall back to the upload box with a friendly message."""
    key = _session_key(request)
    remaining = DAILY_LIMIT - _used_today(key)
    if remaining <= 0:
        return JsonResponse({'ok': False, 'message': f'You’ve reached today’s limit of {DAILY_LIMIT} images. Please come back tomorrow.'})

    ip = _client_ip(request)
    if not request.user.is_authenticated:
        remaining = min(remaining, ANON_IP_DAILY_LIMIT - _ip_used_today(ip))
        if remaining <= 0:
            return JsonResponse({'ok': False, 'message': 'You’ve reached today’s free limit. Log in or come back tomorrow.'})

    listing_url = (request.POST.get('listing_url') or '').strip()
    uploads = request.FILES.getlist('images')
    if not listing_url and not uploads:
        return JsonResponse({'ok': False, 'message': 'Paste a listing URL or choose some photos to upload.'})

    budget = min(MAX_PER_SUBMIT, remaining)
    notes, jobs = [], []

    # Uploads: the original is stored right here, so the worker only has to enhance it.
    skipped = 0
    for upload in uploads:
        if len(jobs) >= budget:
            notes.append(f'Only the first {budget} photos were used.')
            break
        job = ImageJob(session_key=key, ip_address=ip,
                       source_url=listing_url[:2000] if _valid_http_url(listing_url) else '')
        original_key = _store_upload(upload, job.id)
        if not original_key:
            skipped += 1
            continue
        job.original_key = original_key
        jobs.append(job)
    if skipped:
        notes.append(f'{skipped} file(s) were skipped (not a valid image, or over 5 MB).')

    # Listing URL: scrape image links; the worker downloads each one.
    fallback = False
    if listing_url:
        urls = scraper.scrape_images(listing_url) if _valid_http_url(listing_url) else []
        if not urls:
            fallback = True
            notes.append("We couldn't pull photos from that link — some sites block automated access. "
                         'Please upload the photos directly instead.')
        for image_url in urls:
            if len(jobs) >= budget:
                break
            jobs.append(ImageJob(session_key=key, ip_address=ip, source_url=listing_url, image_url=image_url[:2000]))

    if not jobs:
        return JsonResponse({'ok': False, 'fallback': fallback, 'message': ' '.join(notes)})

    for job in jobs[1:]:
        job.status = ImageJob.STATUS_HELD
    for job in jobs:
        job.save()
    request.session[BATCH_SESSION_KEY] = [str(j.id) for j in jobs]
    dispatch(jobs[0].id)   # preview of ONE photo first; the rest wait for Continue

    unlocked = _unlocked_ids(request)
    return JsonResponse({
        'ok': True,
        'fallback': fallback,
        'message': ' '.join(notes),
        'jobs': [_payload(j, unlocked) for j in jobs],
        'remaining': max(DAILY_LIMIT - _used_today(key), 0),
    })


@require_POST
def image_continue(request):
    """The visitor liked the preview: enhance the rest of the batch."""
    key = _session_key(request)
    held = [j for j in _batch_jobs(request) if j.status == ImageJob.STATUS_HELD]
    if not held:
        return JsonResponse({'ok': False, 'message': 'There are no more photos waiting.'})

    remaining = DAILY_LIMIT - _used_today(key)
    if not request.user.is_authenticated:
        remaining = min(remaining, ANON_IP_DAILY_LIMIT - _ip_used_today(_client_ip(request)))
    if remaining <= 0:
        return JsonResponse({'ok': False, 'message': 'You’ve reached today’s limit. Please come back tomorrow.'})

    release = held[:remaining]
    ids = [j.id for j in release]
    ImageJob.objects.filter(pk__in=ids, status=ImageJob.STATUS_HELD).update(status=ImageJob.STATUS_PENDING)
    for job_id in ids:
        dispatch(job_id)

    unlocked = _unlocked_ids(request)
    note = '' if len(release) == len(held) else f'Only {len(release)} more photo(s) fit in today’s limit.'
    return JsonResponse({
        'ok': True,
        'message': note,
        'jobs': [_payload(j, unlocked) for j in _batch_jobs(request)],
        'remaining': max(DAILY_LIMIT - _used_today(key), 0),
    })


def _valid_http_url(value):
    parsed = urlparse(value)
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)


@require_GET
def image_status(request):
    ids = [i for i in (request.GET.get('ids') or '').split(',') if i][:DAILY_LIMIT]
    try:
        jobs = ImageJob.objects.filter(pk__in=ids, session_key=_session_key(request))
    except (ValidationError, ValueError):
        return JsonResponse({'jobs': []})
    unlocked = _unlocked_ids(request)
    return JsonResponse({'jobs': [_payload(j, unlocked) for j in jobs]})


# ── preview: BEFORE (original) and AFTER (watermarked only) ────────────────

@require_GET
def image_before(request, job_id):
    job = _owned_job(request, job_id)
    if not job.original_key:
        raise Http404
    return _stream(job.original_key)


@require_GET
def image_after(request, job_id):
    job = _owned_job(request, job_id)
    if job.status != ImageJob.STATUS_DONE or not job.watermarked_key:
        raise Http404
    return _stream(job.watermarked_key)


# ── download gate ──────────────────────────────────────────────────────────

@require_POST
def image_unlock(request):
    """Unlock every finished image of the current batch for download (one lead per unlock)."""
    jobs = [j for j in _batch_jobs(request) if j.status == ImageJob.STATUS_DONE and j.clean_key]
    if not jobs:
        return JsonResponse({'ok': False, 'message': 'Your images are not ready yet.'}, status=400)

    try:
        body = json.loads(request.body or '{}')
    except ValueError:
        body = {}
    name = (body.get('name') or request.POST.get('name') or '').strip()
    email = (body.get('email') or request.POST.get('email') or '').strip()
    unlocked = _unlocked_ids(request)
    if (request.session.get(LEAD_SESSION_KEY) or all(str(j.id) in unlocked for j in jobs)) and not (name or email):
        # Already gave name+email this session: unlock the (newly finished) photos and just mint a link.
        unlocked.update(str(j.id) for j in jobs)
        request.session[UNLOCK_SESSION_KEY] = sorted(unlocked)
        return JsonResponse({'ok': True, 'url': _download_url(jobs)})
    errors = {}
    if not name:
        errors['name'] = 'Please enter your name.'
    elif len(name) > 120:
        errors['name'] = 'Name is too long.'
    try:
        EmailValidator()(email)
    except ValidationError:
        errors['email'] = 'Please enter a valid email address.'
    if errors:
        return JsonResponse({'ok': False, 'errors': errors}, status=400)

    BoosterLead.objects.create(
        name=name, email=email, feature=BoosterLead.FEATURE_IMAGE,
        source_url=jobs[0].source_url, ip_address=_client_ip(request),
    )
    unlocked.update(str(j.id) for j in jobs)
    request.session[UNLOCK_SESSION_KEY] = sorted(unlocked)
    request.session[LEAD_SESSION_KEY] = True
    return JsonResponse({'ok': True, 'url': _download_url(jobs)})


def _download_url(jobs):
    token = signing.dumps({'jobs': [str(j.id) for j in jobs]}, salt=DOWNLOAD_SALT)
    return reverse('aibooster:image-download', args=[token])


@require_GET
def image_download(request, token):
    try:
        data = signing.loads(token, salt=DOWNLOAD_SALT, max_age=DOWNLOAD_LINK_MAX_AGE)
        job_ids = list(data['jobs'])
    except (signing.BadSignature, KeyError, TypeError):
        return HttpResponseForbidden('This download link has expired. Please click Download again.')

    # Re-check server-side: the signed link alone is never enough. Only images this
    # session owns AND has unlocked are served.
    unlocked = _unlocked_ids(request)
    allowed = [i for i in job_ids if i in unlocked]
    if not allowed:
        return HttpResponseForbidden('Please enter your details to unlock this download.')
    try:
        found = {str(j.id): j for j in ImageJob.objects.filter(pk__in=allowed, session_key=_session_key(request))}
    except (ValidationError, ValueError):
        raise Http404
    jobs = [found[i] for i in allowed if i in found
            and found[i].status == ImageJob.STATUS_DONE and found[i].clean_key]
    if not jobs:
        raise Http404

    if len(jobs) == 1:
        return _stream(jobs[0].clean_key, filename=f'favhost-enhanced-{str(jobs[0].id)[:8]}.jpg')

    # Several images: bundle into a ZIP on disk (JPEGs don't compress, so store them as-is).
    archive = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_STORED) as zf:
        for n, job in enumerate(jobs, 1):
            try:
                zf.writestr(f'favhost-enhanced-{n:02d}.jpg', storage.read_bytes(job.clean_key))
            except Exception:
                logger.warning('Photo Enhancer: clean file missing for job %s', job.id)
    archive.seek(0)
    response = FileResponse(archive, content_type='application/zip', as_attachment=True,
                            filename='favhost-enhanced-photos.zip')
    response['Cache-Control'] = 'private, no-store'
    return response


# ── Listing Audit ───────────────────────────────────────────────────────────

REPORT_DAILY_LIMIT = 10
REPORT_SESSION_KEY = 'aibooster_report'  # id of this session's most recent report
MIN_MANUAL_CHARS = 40
MAX_MANUAL_CHARS = 12000
REPORT_FRIENDLY = 'Something went wrong on our side. Please try again in a moment.'


def _reports_today(session_key):
    since = timezone.now() - timedelta(days=1)
    return ListingReport.objects.filter(session_key=session_key, created_at__gte=since).count()


def _latest_report(request):
    report_id = request.session.get(REPORT_SESSION_KEY)
    if not report_id:
        return None
    try:
        return ListingReport.objects.get(pk=report_id, session_key=_session_key(request))
    except (ListingReport.DoesNotExist, ValidationError, ValueError):
        return None


def _report_payload(report):
    if report is None:
        return None
    return {
        'id': str(report.id),
        'status': report.status,
        'error': report.error if report.status == ListingReport.STATUS_FAILED else '',
        'platform': report.platform,
        'source_url': report.source_url,
        'result': report.result_json if report.status == ListingReport.STATUS_DONE else None,
        'status_url': reverse('aibooster:report-status', args=[report.id]),
    }


def _own_hosts(request):
    hosts = {request.get_host().split(':')[0]}
    for name in ('DOMAIN_URL', 'BASE_URL'):
        host = urlparse(getattr(settings, name, '') or '').hostname
        if host:
            hosts.add(host)
    return hosts


@require_POST
def report_start(request):
    """Gather the listing data and queue the analysis. Always answers 200 JSON so the page can
    show a friendly message (and the manual-paste box) instead of an error page."""
    key = _session_key(request)
    if _reports_today(key) >= REPORT_DAILY_LIMIT:
        return JsonResponse({'ok': False, 'message': f'You’ve reached today’s limit of {REPORT_DAILY_LIMIT} reports. Please come back tomorrow.'})

    url = (request.POST.get('listing_url') or '').strip()
    manual = (request.POST.get('manual_text') or '').strip()
    if url and not _valid_http_url(url):
        return JsonResponse({'ok': False, 'message': 'That doesn’t look like a valid link. Paste the full address, starting with https://'})
    if not url and not manual:
        return JsonResponse({'ok': False, 'message': 'Paste a listing URL, or paste your listing details below.'})
    if len(manual) > MAX_MANUAL_CHARS:
        return JsonResponse({'ok': False, 'needs_manual': True,
                             'message': f'That text is too long — please keep it under {MAX_MANUAL_CHARS:,} characters.'})

    platform = scraper.detect_platform(url, _own_hosts(request)) if url else ListingReport.PLATFORM_OTHER
    try:
        if manual:
            if len(manual) < MIN_MANUAL_CHARS:
                return JsonResponse({'ok': False, 'needs_manual': True,
                                     'message': 'Please paste a bit more of your listing (title, description, amenities…) so we have something to analyse.'})
            scraped = scraper.manual_listing(manual, url, platform)
        else:
            scraped = scraper.read_own_listing(url) if platform == ListingReport.PLATFORM_FAVHOST else None
            if scraped is None:
                scraped = scraper.scrape_listing(url, platform)
            if scraper.is_sparse(scraped):
                # Nothing useful found: don't spend an AI call on an empty page.
                return JsonResponse({
                    'ok': False, 'needs_manual': True,
                    'message': "We couldn't read enough details from that link — many sites block automated access. "
                               'Please paste your listing details in the box below instead.',
                })
        report = ListingReport.objects.create(
            source_url=url[:2000], platform=platform, scraped_json=scraped, session_key=key)
    except Exception:
        logger.exception('Listing Audit: could not start a report')
        return JsonResponse({'ok': False, 'message': REPORT_FRIENDLY})

    request.session[REPORT_SESSION_KEY] = str(report.id)
    dispatch_report(report.id)
    return JsonResponse({
        'ok': True,
        'report': _report_payload(report),
        'remaining': max(REPORT_DAILY_LIMIT - _reports_today(key), 0),
    })


@require_GET
def report_status(request, report_id):
    try:
        report = ListingReport.objects.get(pk=report_id, session_key=_session_key(request))
    except ListingReport.DoesNotExist:
        raise Http404
    return JsonResponse({'report': _report_payload(report)})

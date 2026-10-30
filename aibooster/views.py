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
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import imaging, payments, report_pdf, scraper, services, storage
from .models import ImageJob, ListingReport, Order
from .tasks import dispatch, dispatch_report

logger = logging.getLogger(__name__)

DAILY_LIMIT = 50
# Anonymous visitors cost real money and can mint new sessions by clearing cookies,
# so they are also capped per IP address.
ANON_IP_DAILY_LIMIT = 50
MAX_PER_SUBMIT = 25
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
DOWNLOAD_LINK_MAX_AGE = 300  # seconds
BATCH_SESSION_KEY = 'aibooster_batch'  # ids of the most recent submission
FLASH_SESSION_KEY = 'aibooster_flash'  # one-shot message shown after returning from Stripe
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


def _payload(job):
    data = {
        'id': str(job.id),
        'status': job.status,
        'error': job.error if job.status == ImageJob.STATUS_FAILED else '',
        'before_url': reverse('aibooster:image-before', args=[job.id]),
        # Scraped photos are only saved once the worker starts, so the page must not ask for the
        # original before it exists (that was the broken BEFORE image).
        'has_before': bool(job.original_key),
        'paid': job.is_paid,
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

def _pay_return(request, kind, route):
    """Back from Stripe: verify the payment with Stripe, then redirect to the clean URL with a
    one-shot message. Returns a redirect response, or None when this isn't a Stripe return."""
    session_id = request.GET.get('session_id')
    if session_id:
        order = payments.confirm_session(session_id)
        request.session[FLASH_SESSION_KEY] = 'paid' if order and order.kind == kind else 'unconfirmed'
        return redirect(route)
    if request.GET.get('canceled'):
        request.session[FLASH_SESSION_KEY] = 'canceled'
        return redirect(route)
    return None


def image_page(request):
    back = _pay_return(request, Order.KIND_PHOTOS, 'aibooster:image')
    if back:
        return back
    key = _session_key(request)
    jobs = _batch_jobs(request)
    return render(request, 'aibooster/image_booster.html', {
        'jobs_json': [_payload(j) for j in jobs],
        'base_template': _base_template(request),
        'samples': _samples(),
        'daily_limit': DAILY_LIMIT,
        'remaining': max(DAILY_LIMIT - _used_today(key), 0),
        'max_per_submit': MAX_PER_SUBMIT,
        'price': payments.price_info(Order.KIND_PHOTOS),
        'flash': request.session.pop(FLASH_SESSION_KEY, ''),
    })


def report_page(request):
    back = _pay_return(request, Order.KIND_REPORT, 'aibooster:report')
    if back:
        return back
    key = _session_key(request)
    return render(request, 'aibooster/boost_report.html', {
        'base_template': _base_template(request),
        'report_daily_limit': REPORT_DAILY_LIMIT,
        'report_remaining': max(REPORT_DAILY_LIMIT - _reports_today(key), 0),
        'report_json': _report_payload(_latest_report(request)),
        'price': payments.price_info(Order.KIND_REPORT),
        'flash': request.session.pop(FLASH_SESSION_KEY, ''),
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

    # "Add more photos": new photos join the current batch (always locked until paid), up to the cap,
    # and only while nothing in the batch has been paid for.
    existing = _batch_jobs(request) if request.POST.get('append') else []
    if existing and any(j.is_paid for j in existing):
        return JsonResponse({'ok': False, 'message': 'This set is already paid for, so no more photos can be added. Use “Start over” for a new set.'})
    room = MAX_PER_SUBMIT - len(existing)
    if existing and room <= 0:
        return JsonResponse({'ok': False, 'message': f'You’ve reached the limit of {MAX_PER_SUBMIT} photos for one set.'})

    budget = min(room if existing else MAX_PER_SUBMIT, remaining)
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

    for job in (jobs if existing else jobs[1:]):
        job.status = ImageJob.STATUS_HELD
    for job in jobs:
        job.save()
    all_jobs = existing + jobs
    request.session[BATCH_SESSION_KEY] = [str(j.id) for j in all_jobs]
    if not existing:
        dispatch(jobs[0].id)   # preview of ONE photo first; the rest stay locked until the visitor pays

    return JsonResponse({
        'ok': True,
        'fallback': fallback,
        'message': ' '.join(notes),
        'jobs': [_payload(j) for j in all_jobs],
        'remaining': max(DAILY_LIMIT - _used_today(key), 0),
    })


def _checkout_urls(request, route):
    base = request.build_absolute_uri(reverse(route))
    return base + '?session_id={CHECKOUT_SESSION_ID}', base + '?canceled=1'


@require_POST
def image_checkout(request):
    """Start the one-time payment for every photo of the current batch that isn't paid yet
    (price per photo x number of photos). Answers JSON with the Stripe page to send the visitor to."""
    jobs = [j for j in _batch_jobs(request) if not j.is_paid and j.status != ImageJob.STATUS_FAILED]
    if not jobs:
        return JsonResponse({'ok': False, 'message': 'There is nothing to pay for.'})
    order = Order(kind=Order.KIND_PHOTOS, session_key=_session_key(request), job_ids=[str(j.id) for j in jobs],
                  quantity=len(jobs), user_id=request.user.pk if request.user.is_authenticated else None)
    try:
        order.save()
        success, cancel = _checkout_urls(request, 'aibooster:image')
        url = payments.create_checkout(request, order, success, cancel)
    except payments.PaymentError as exc:
        return JsonResponse({'ok': False, 'message': str(exc)})
    return JsonResponse({'ok': True, 'url': url})


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
    return JsonResponse({'jobs': [_payload(j) for j in jobs]})


# ── preview: BEFORE (original) and AFTER (watermarked until paid) ────────────────

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
    # Paid photos are shown clean (no watermark); unpaid ones only ever get the watermarked copy.
    return _stream(job.clean_key if job.is_paid and job.clean_key else _current_preview_key(job))


def _current_preview_key(job):
    """The watermarked preview, redrawn first if it was made with an older watermark design, so a change
    to the watermark reaches photos that were enhanced before it (not only new ones)."""
    marker = f'preview-{imaging.WATERMARK_VERSION}-'
    if marker in job.watermarked_key or not job.clean_key:
        return job.watermarked_key
    try:
        marked = imaging.watermark(imaging.open_image(storage.read_bytes(job.clean_key)))
        new_key = storage.save_bytes(storage.new_key(job.id, f'preview-{imaging.WATERMARK_VERSION}', 'jpg'),
                                     imaging.to_jpeg_bytes(marked, 82))
    except Exception:
        logger.warning('Photo Enhancer: could not redraw the preview of job %s', job.id, exc_info=True)
        return job.watermarked_key
    old_key = job.watermarked_key
    ImageJob.objects.filter(pk=job.pk).update(watermarked_key=new_key)
    job.watermarked_key = new_key
    try:
        storage.get_storage().delete(old_key)
    except Exception:
        logger.warning('Photo Enhancer: could not delete the old preview %s', old_key, exc_info=True)
    return new_key


# ── download gate ──────────────────────────────────────────────────────────

@require_POST
def image_unlock(request):
    """Mint a short-lived download link for the paid, finished photos of the current batch.
    If nothing is paid yet the page sends the visitor to checkout instead."""
    batch = _batch_jobs(request)
    jobs = [j for j in batch if j.is_paid and j.status == ImageJob.STATUS_DONE and j.clean_key]
    working = [j for j in batch if j.is_paid and j.status in (ImageJob.STATUS_PENDING, ImageJob.STATUS_PROCESSING)]
    if working:
        # Never hand out a half-finished ZIP: wait until every paid photo is enhanced.
        return JsonResponse({'ok': False, 'enhancing': True, 'left': len(working),
                             'message': f'Still enhancing {len(working)} photo{"s" if len(working) > 1 else ""}. '
                                        'Your download will be ready in a moment.'}, status=409)
    if not jobs:
        if any(j.is_paid for j in batch):
            return JsonResponse({'ok': False, 'message': 'Your photos are not ready yet.'}, status=400)
        return JsonResponse({'ok': False, 'needs_payment': True})
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

    # Re-check server-side: the signed link alone is never enough. Only photos this
    # session owns AND has paid for are served.
    try:
        found = {str(j.id): j for j in ImageJob.objects.filter(pk__in=job_ids, session_key=_session_key(request), is_paid=True)}
    except (ValidationError, ValueError):
        raise Http404
    if not found:
        return HttpResponseForbidden('Please complete payment to download these photos.')
    jobs = [found[i] for i in job_ids if i in found
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


# ── Listing Optimize ───────────────────────────────────────────────────────────

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
        'result': services.teaser(services.present(report.result_json), report.is_paid) if report.status == ListingReport.STATUS_DONE else None,
        'paid': report.is_paid,
        'download_url': reverse('aibooster:report-download', args=[report.id]) if report.status == ListingReport.STATUS_DONE and report.is_paid else '',
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
        logger.exception('Listing Optimize: could not start a report')
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


@require_GET
def report_download(request, report_id):
    """The finished report as a PDF (only for the session that ran it)."""
    try:
        report = ListingReport.objects.get(pk=report_id, session_key=_session_key(request),
                                           status=ListingReport.STATUS_DONE)
    except ListingReport.DoesNotExist:
        raise Http404
    if not report.is_paid:
        return HttpResponseForbidden('Please unlock the full report to download it.')
    pdf = report_pdf.build(report, services.present(report.result_json))
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="favhost-listing-optimize-{str(report.id)[:8]}.pdf"'
    return response


@require_POST
def report_checkout(request):
    """Start the one-time payment that unlocks the full report (and its PDF / print)."""
    report = _latest_report(request)
    if report is None or report.status != ListingReport.STATUS_DONE:
        return JsonResponse({'ok': False, 'message': 'Your report is not ready yet.'})
    if report.is_paid:
        return JsonResponse({'ok': True, 'paid': True})
    order = Order(kind=Order.KIND_REPORT, session_key=_session_key(request), report=report, quantity=1,
                  user_id=request.user.pk if request.user.is_authenticated else None)
    try:
        order.save()
        success, cancel = _checkout_urls(request, 'aibooster:report')
        url = payments.create_checkout(request, order, success, cancel)
    except payments.PaymentError as exc:
        return JsonResponse({'ok': False, 'message': str(exc)})
    return JsonResponse({'ok': True, 'url': url})


# ── start over: let the visitor clear their data ────────────────────────────

def _forget_job(job):
    """Delete an unpaid photo's files and row. Paid photos and jobs a worker may be running are kept."""
    if job.is_paid or job.status in (ImageJob.STATUS_PENDING, ImageJob.STATUS_PROCESSING):
        return
    for key in (job.original_key, job.watermarked_key, job.clean_key):
        if key:
            try:
                storage.get_storage().delete(key)
            except Exception:
                logger.warning('Photo Enhancer: could not delete %s', key, exc_info=True)
    job.delete()


@require_POST
def image_reset(request):
    """Clear this session's current batch: unpaid photos are deleted for good; paid ones stay on file."""
    for job in _batch_jobs(request):
        _forget_job(job)
    request.session.pop(BATCH_SESSION_KEY, None)
    return JsonResponse({'ok': True})


@require_POST
def image_remove(request):
    """Take one locked, unpaid photo out of the current batch (picked by mistake). The first photo,
    which carries the free preview, and anything paid or being enhanced cannot be removed."""
    job_id = request.POST.get('id') or ''
    batch = _batch_jobs(request)
    job = next((j for j in batch if str(j.id) == job_id), None)
    if not job or batch[0].id == job.id or job.is_paid or job.status not in (ImageJob.STATUS_HELD, ImageJob.STATUS_FAILED):
        return JsonResponse({'ok': False, 'message': 'This photo can’t be removed.'}, status=400)
    _forget_job(job)
    request.session[BATCH_SESSION_KEY] = [str(j.id) for j in batch if j.id != job.id]
    return JsonResponse({'ok': True})


@require_POST
def report_reset(request):
    """Clear this session's current report: an unpaid report is deleted for good; a paid one stays on file."""
    report = _latest_report(request)
    if report and not report.is_paid and report.status in (ListingReport.STATUS_DONE, ListingReport.STATUS_FAILED):
        report.delete()
    request.session.pop(REPORT_SESSION_KEY, None)
    return JsonResponse({'ok': True})

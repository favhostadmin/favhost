"""The per-image enhance pipeline, in the required order:

1. save original  2. OpenAI edit  3. upscale to 3000px -> clean_key (private)
4. watermarked copy -> watermarked_key  5. store token usage + cost.
"""
import logging
import time

from . import imaging, openai_client, scraper, storage
from .models import ImageJob

logger = logging.getLogger(__name__)

_API_TYPES = {'JPEG': ('jpg', 'image/jpeg'), 'PNG': ('png', 'image/png'), 'WEBP': ('webp', 'image/webp')}
MIN_EDGE = 200


def _friendly(job, message):
    job.status = ImageJob.STATUS_FAILED
    job.error = message
    job.save(update_fields=['status', 'error'])


def _fetch_original(job):
    """Step 1 for scraped images (uploads were already stored by the view)."""
    try:
        data, _ctype, _enc = scraper.safe_get(job.image_url, scraper.MAX_IMAGE_BYTES)
        fmt = imaging.image_format(data)  # also proves the bytes are a real image
    except Exception:
        logger.warning('Image Booster: could not fetch image %s', job.image_url, exc_info=True)
        raise openai_client.EnhanceError("We couldn't download this image from the listing.")
    ext = _API_TYPES.get(fmt, ('img', None))[0]
    job.original_key = storage.save_bytes(storage.new_key(job.id, 'original', ext), data)
    job.save(update_fields=['original_key'])


def run(job_id):
    # Claim the job so a duplicate delivery can't process it twice.
    if not ImageJob.objects.filter(pk=job_id, status=ImageJob.STATUS_PENDING).update(
            status=ImageJob.STATUS_PROCESSING):
        return
    job = ImageJob.objects.get(pk=job_id)
    t0 = time.monotonic()
    try:
        # 1. Original in storage.
        if not job.original_key:
            _fetch_original(job)
        original = storage.read_bytes(job.original_key)
        src = imaging.open_image(original)
        if min(src.size) < MIN_EDGE:
            raise openai_client.EnhanceError('This image is too small to enhance.')

        # Send a <=1536px JPEG: smaller upload, fewer input tokens, same result.
        payload = imaging.prepare_for_api(src)
        t_prep = time.monotonic()

        # 2. OpenAI edit (retries once internally).
        result, usage = openai_client.edit_image(payload, 'image.jpg', 'image/jpeg')
        enhanced = imaging.open_image(result)
        t_api = time.monotonic()

        # 3. Upscale to 3000px on the long edge -> clean copy in private storage.
        clean = imaging.upscale_to_clean(enhanced)
        job.clean_key = storage.save_bytes(storage.new_key(job.id, 'clean', 'jpg'),
                                           imaging.to_jpeg_bytes(clean, 90))

        # 4. Separate watermarked copy.
        marked = imaging.watermark(enhanced)
        job.watermarked_key = storage.save_bytes(storage.new_key(job.id, 'preview', 'jpg'),
                                                 imaging.to_jpeg_bytes(marked, 82))

        # 5. Usage + cost.
        job.input_tokens = int(usage.get('input_tokens') or 0)
        job.output_tokens = int(usage.get('output_tokens') or 0)
        job.cost_cents = openai_client.compute_cost_cents(usage)
        job.status = ImageJob.STATUS_DONE
        job.error = ''
        job.save()
        logger.info('Image Booster job %s done in %.1fs (prep %.1fs, openai %.1fs, finish %.1fs)',
                    job_id, time.monotonic() - t0, t_prep - t0, t_api - t_prep, time.monotonic() - t_api)
    except openai_client.EnhanceError as exc:
        _friendly(job, str(exc))
    except Exception:
        logger.exception('Image Booster: job %s crashed', job_id)
        _friendly(job, 'Something went wrong while enhancing this image. Please try again.')


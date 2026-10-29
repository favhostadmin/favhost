"""Thin client for OpenAI's /v1/images/edits (plain requests; no SDK dependency)."""
import base64
import logging
import time
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

EDITS_URL = 'https://api.openai.com/v1/images/edits'
MODEL = 'gpt-image-2'
SIZE = '1536x1024'
QUALITY = 'medium'
# (connect, read). A healthy edit returns in ~30-60s; a call that is silent for
# 90s is hung, and retrying it is faster than waiting longer.
REQUEST_TIMEOUT = (10, 90)
RETRY_DELAY = 2
MAX_RETRY_DELAY = 20


class EnhanceError(Exception):
    """Raised with a message that is safe to show to the user."""


class _Permanent(Exception):
    """An API error a retry cannot fix (bad key, no credits, rejected request)."""


UNAVAILABLE_MSG = 'Image enhancement is temporarily unavailable. Please try again later.'
_PERMANENT_CODES = {'insufficient_quota', 'credit_balance_exhausted', 'invalid_api_key', 'billing_hard_limit_reached'}


def _api_error_code(resp):
    try:
        return (resp.json().get('error') or {}).get('code') or ''
    except ValueError:
        return ''


def _retry_delay(exc):
    """Honour a rate-limit's Retry-After (capped); otherwise a short pause."""
    after = getattr(exc, 'retry_after', None)
    return min(after, MAX_RETRY_DELAY) if after else RETRY_DELAY


def _rate(name, default):
    """USD per 1M tokens. Defaults are gpt-image-1's published rates (placeholder
    until gpt-image-2 pricing is confirmed); override via the OPENAI_IMAGE_* env vars."""
    return Decimal(str(getattr(settings, name, None) or default))


def compute_cost_cents(usage):
    details = usage.get('input_tokens_details') or {}
    in_total = int(usage.get('input_tokens') or 0)
    if details:
        img_in = int(details.get('image_tokens') or 0)
        txt_in = int(details.get('text_tokens') or max(in_total - img_in, 0))
    else:
        # No breakdown given: price all input as image tokens (the dominant part).
        img_in, txt_in = in_total, 0
    out = int(usage.get('output_tokens') or 0)
    usd = (
        txt_in * _rate('OPENAI_IMAGE_TEXT_INPUT_RATE', '5')
        + img_in * _rate('OPENAI_IMAGE_IMAGE_INPUT_RATE', '10')
        + out * _rate('OPENAI_IMAGE_OUTPUT_RATE', '40')
    ) / Decimal(1_000_000)
    return (usd * 100).quantize(Decimal('0.0001'))


def edit_image(image_bytes, filename, content_type):
    """Run one edit. Returns (result_bytes, usage dict). Retries once, then raises EnhanceError."""
    api_key = getattr(settings, 'OPENAI_API_KEY', '')
    prompt = getattr(settings, 'BOOSTER_IMAGE_PROMPT', '')
    if not api_key or not prompt:
        logger.error('Photo Enhancer: OPENAI_API_KEY / BOOSTER_IMAGE_PROMPT not configured')
        raise EnhanceError('Image enhancement is not available right now. Please try again later.')

    last_error = None
    for attempt in (1, 2):
        try:
            resp = requests.post(
                EDITS_URL,
                headers={'Authorization': f'Bearer {api_key}'},
                # The prompt is passed through exactly as configured.
                data={'model': MODEL, 'prompt': prompt, 'size': SIZE, 'quality': QUALITY, 'n': '1'},
                files={'image': (filename, image_bytes, content_type)},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                detail = f'HTTP {resp.status_code}: {resp.text[:300]}'
                # 429 is retryable only when it is a rate limit, not an empty balance.
                if resp.status_code in (400, 401, 403, 404) or _api_error_code(resp) in _PERMANENT_CODES:
                    raise _Permanent(detail)
                err = RuntimeError(detail)
                try:
                    err.retry_after = float(resp.headers.get('Retry-After', ''))
                except (TypeError, ValueError):
                    pass
                raise err
            payload = resp.json()
            result = base64.b64decode(payload['data'][0]['b64_json'])
            usage = payload.get('usage') or {}
            logger.info(
                'OpenAI image edit ok: model=%s size=%s quality=%s input_tokens=%s output_tokens=%s cost_cents=%s',
                MODEL, SIZE, QUALITY, usage.get('input_tokens', 0), usage.get('output_tokens', 0),
                compute_cost_cents(usage),
            )
            return result, usage
        except _Permanent as exc:
            logger.error('OpenAI image edit rejected (not retrying): model=%s size=%s quality=%s error=%s',
                         MODEL, SIZE, QUALITY, exc)
            raise EnhanceError(UNAVAILABLE_MSG) from exc
        except Exception as exc:
            last_error = exc
            logger.warning('OpenAI image edit attempt %s failed: model=%s size=%s quality=%s error=%s',
                           attempt, MODEL, SIZE, QUALITY, exc)
            if attempt == 1:
                time.sleep(_retry_delay(exc))
    raise EnhanceError("We couldn't enhance this image. Please try again in a moment.") from last_error

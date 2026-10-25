"""Listing Audit: send the gathered listing data to OpenAI's chat completions API and
validate the JSON that comes back. Plain requests, like openai_client.py."""
import json
import logging
import os
import re
import time
from decimal import Decimal

import requests
from django.conf import settings

from .models import ListingReport

logger = logging.getLogger(__name__)

CHAT_URL = 'https://api.openai.com/v1/chat/completions'
# (connect, read). Long structured outputs take a while, but a silent 120s call is hung.
REQUEST_TIMEOUT = (10, 120)
MAX_COMPLETION_TOKENS = 10000
MISSING = 'DATA_NOT_AVAILABLE'
UNAVAILABLE_MSG = 'The Listing Audit is temporarily unavailable. Please try again later.'
FAILED_MSG = "We couldn't generate your report this time. Please try again in a moment."
BAD_OUTPUT_MSG = "We couldn't read the analysis we got back. Please try again, or paste the listing details manually."

_PERMANENT_CODES = {'insufficient_quota', 'credit_balance_exhausted', 'invalid_api_key', 'billing_hard_limit_reached'}

INSTRUCTIONS = (
    'You cannot browse. Use ONLY the data provided above. For any field, metric, review analysis or '
    'competitor data that is not in the provided data, output the literal string DATA_NOT_AVAILABLE and '
    'list it under missing_data. Never invent reviews, ratings, prices or competitor figures. '
    'Respond with ONLY valid JSON matching the schema below - no markdown, no code fences.'
)
SCHEMA = '''{
  "overall_score": 0-100,
  "biggest_issue": "",
  "scorecard": [{"category":"","score":0,"issue":"","fix":""}],
  "fields": [
    {"field_name":"", "current":"", "suggested":"",
     "char_count":0, "char_limit":0, "reason":""}
  ],
  "missing_data": [""]
}
"fields" must follow Airbnb editor order: Title, Property details, Description (summary, the space, guest access, other things to note), Location, Amenities, House Rules, Safety & Property, Booking settings, Cancellation policy.
"suggested" must be plain text only, ready to paste into Airbnb. No markdown inside it.'''
STRICT_RETRY = (
    'Your previous reply could not be parsed as JSON. Reply again with ONLY one valid JSON object that '
    'matches the schema exactly: no markdown, no code fences, no commentary before or after, no trailing commas.'
)


class ReportError(Exception):
    """Raised with a message that is safe to show to the user."""


class _Permanent(Exception):
    """An API error a retry cannot fix (bad key, no credits, rejected request)."""


def _conf(name):
    return getattr(settings, name, '') or os.environ.get(name, '')


def _rate(name, default):
    """USD per 1M tokens. Defaults are placeholders; set OPENAI_REPORT_INPUT_RATE / _OUTPUT_RATE
    to the chosen model's published prices."""
    return Decimal(str(_conf(name) or default))


def compute_cost_cents(input_tokens, output_tokens):
    usd = (input_tokens * _rate('OPENAI_REPORT_INPUT_RATE', '2.5')
           + output_tokens * _rate('OPENAI_REPORT_OUTPUT_RATE', '10')) / Decimal(1_000_000)
    return (usd * 100).quantize(Decimal('0.0001'))


def build_messages(scraped):
    user = f'{json.dumps(scraped, ensure_ascii=False, indent=2)}\n\n{INSTRUCTIONS}\n\n{SCHEMA}'
    # The configured prompt is the system message exactly as stored.
    return [{'role': 'system', 'content': _conf('BOOSTER_REPORT_PROMPT')},
            {'role': 'user', 'content': user}]


def _post(messages, model, api_key):
    """One chat-completions request, retried once on a transient failure. Returns (text, usage)."""
    last = None
    for attempt in (1, 2):
        try:
            resp = requests.post(
                CHAT_URL,
                headers={'Authorization': f'Bearer {api_key}'},
                json={'model': model, 'messages': messages,
                      'response_format': {'type': 'json_object'},
                      'max_completion_tokens': MAX_COMPLETION_TOKENS},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                try:
                    code = (resp.json().get('error') or {}).get('code') or ''
                except ValueError:
                    code = ''
                detail = f'HTTP {resp.status_code}: {resp.text[:300]}'
                if resp.status_code in (400, 401, 403, 404) or code in _PERMANENT_CODES:
                    raise _Permanent(detail)
                raise RuntimeError(detail)
            payload = resp.json()
            return payload['choices'][0]['message']['content'] or '', payload.get('usage') or {}
        except _Permanent as exc:
            logger.error('Listing Audit: OpenAI rejected request (not retrying): model=%s error=%s', model, exc)
            raise ReportError(UNAVAILABLE_MSG) from exc
        except Exception as exc:
            last = exc
            logger.warning('Listing Audit: OpenAI attempt %s failed: model=%s error=%s', attempt, model, exc)
            if attempt == 1:
                time.sleep(2)
    raise ReportError(FAILED_MSG) from last


_FENCE = re.compile(r'^\s*```(?:json)?\s*|\s*```\s*$', re.I)


def parse_json(text):
    """Parse the model's reply as a JSON object; tolerate a stray code fence. Raises ValueError."""
    text = _FENCE.sub('', text or '').strip()
    try:
        data = json.loads(text)
    except ValueError:
        # Last resort: the outermost {...} (model added a sentence around the JSON).
        start, end = text.find('{'), text.rfind('}')
        if start == -1 or end <= start:
            raise
        data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError('not an object')
    return data


def _plain(text):
    """'suggested' must paste cleanly into Airbnb: strip any markdown the model slipped in."""
    text = str(text if text is not None else '')
    text = re.sub(r'```[a-z]*\n?|```', '', text)
    text = re.sub(r'(\*\*|__)(.+?)\1', r'\2', text, flags=re.S)
    text = re.sub(r'^\s{0,3}#{1,6}\s+', '', text, flags=re.M)
    text = re.sub(r'`([^`]*)`', r'\1', text)
    return text.strip()


def _int(value, default=0, lo=None, hi=None):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    if lo is not None:
        number = max(lo, number)
    if hi is not None:
        number = min(hi, number)
    return number


def _text(value):
    return '' if value is None else str(value).strip()


def normalize(data):
    """Coerce the model's JSON into the exact schema the page renders. Raises ValueError if unusable."""
    raw_fields = data.get('fields')
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ValueError('no fields')
    fields = []
    for item in raw_fields:
        if not isinstance(item, dict):
            continue
        suggested = _plain(item.get('suggested'))
        fields.append({
            'field_name': _text(item.get('field_name')),
            'current': _text(item.get('current')),
            'suggested': suggested,
            # Counted here, not trusted from the model: models miscount characters.
            'char_count': len(suggested),
            'char_limit': _int(item.get('char_limit'), 0, lo=0),
            'reason': _text(item.get('reason')),
        })
    if not fields:
        raise ValueError('no usable fields')
    scorecard = [{
        'category': _text(row.get('category')),
        'score': _int(row.get('score'), 0, 0, 100),
        'issue': _text(row.get('issue')),
        'fix': _text(row.get('fix')),
    } for row in (data.get('scorecard') or []) if isinstance(row, dict)]
    missing = [_text(m) for m in (data.get('missing_data') or []) if _text(m)] \
        if isinstance(data.get('missing_data'), list) else []
    # Anything the model marked DATA_NOT_AVAILABLE must also be listed, even if it forgot to.
    for f in fields:
        if MISSING in (f['current'], f['suggested']) and f['field_name'] and f['field_name'] not in missing:
            missing.append(f['field_name'])
    return {
        'overall_score': _int(data.get('overall_score'), 0, 0, 100),
        'biggest_issue': _text(data.get('biggest_issue')),
        'scorecard': scorecard,
        'fields': fields,
        'missing_data': missing,
    }


def generate(scraped):
    """Run the analysis. Returns (result dict, usage dict, model). Retries once on unparseable JSON."""
    api_key, model = _conf('OPENAI_API_KEY'), _conf('OPENAI_REPORT_MODEL')
    if not api_key or not model or not _conf('BOOSTER_REPORT_PROMPT'):
        logger.error('Listing Audit: OPENAI_API_KEY / OPENAI_REPORT_MODEL / BOOSTER_REPORT_PROMPT not configured')
        raise ReportError(UNAVAILABLE_MSG)

    messages = build_messages(scraped)
    tokens_in = tokens_out = 0
    for attempt in (1, 2):
        text, usage = _post(messages, model, api_key)
        call_in, call_out = int(usage.get('prompt_tokens') or 0), int(usage.get('completion_tokens') or 0)
        tokens_in += call_in
        tokens_out += call_out
        logger.info('Listing Audit OpenAI call %s: model=%s input_tokens=%s output_tokens=%s cost_cents=%s',
                    attempt, model, call_in, call_out, compute_cost_cents(call_in, call_out))
        try:
            result = normalize(parse_json(text))
            return result, {'input_tokens': tokens_in, 'output_tokens': tokens_out}, model
        except ValueError:
            logger.warning('Listing Audit: unparseable model output (attempt %s): %.200r', attempt, text)
            if attempt == 1:
                messages = messages + [{'role': 'assistant', 'content': text[:4000]},
                                       {'role': 'user', 'content': STRICT_RETRY}]
    err = ReportError(BAD_OUTPUT_MSG)
    err.usage = {'input_tokens': tokens_in, 'output_tokens': tokens_out}  # both calls were still billed
    raise err


def run(report_id):
    """Worker entry point: process one ListingReport."""
    # Claim it so a duplicate delivery can't run (and bill) it twice.
    if not ListingReport.objects.filter(pk=report_id, status=ListingReport.STATUS_PENDING).update(
            status=ListingReport.STATUS_PROCESSING):
        return
    report = ListingReport.objects.get(pk=report_id)
    t0 = time.monotonic()
    try:
        result, usage, model = generate(report.scraped_json)
        report.result_json = result
        report.input_tokens = usage['input_tokens']
        report.output_tokens = usage['output_tokens']
        report.cost_cents = compute_cost_cents(usage['input_tokens'], usage['output_tokens'])
        report.status = ListingReport.STATUS_DONE
        report.error = ''
        report.save()
        logger.info('Listing Audit %s done in %.1fs: model=%s input_tokens=%s output_tokens=%s cost_cents=%s',
                    report_id, time.monotonic() - t0, model, report.input_tokens, report.output_tokens,
                    report.cost_cents)
    except ReportError as exc:
        usage = getattr(exc, 'usage', None)
        if usage:
            report.input_tokens, report.output_tokens = usage['input_tokens'], usage['output_tokens']
            report.cost_cents = compute_cost_cents(report.input_tokens, report.output_tokens)
        _fail(report, str(exc))
    except Exception:
        logger.exception('Listing Audit: %s crashed', report_id)
        _fail(report, FAILED_MSG)


def _fail(report, message):
    report.status = ListingReport.STATUS_FAILED
    report.error = message
    report.save(update_fields=['status', 'error', 'input_tokens', 'output_tokens', 'cost_cents'])

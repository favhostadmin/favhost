"""Listing Optimize: send the gathered listing data to OpenAI's chat completions API and
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
REQUEST_TIMEOUT = (10, 300)   # a long structured answer can legitimately take a few minutes
MAX_COMPLETION_TOKENS = 10000
MISSING = 'DATA_NOT_AVAILABLE'
UNAVAILABLE_MSG = 'The Listing Optimize is temporarily unavailable. Please try again later.'
FAILED_MSG = "We couldn't generate your report this time. Please try again in a moment."
BAD_OUTPUT_MSG = "We couldn't read the analysis we got back. Please try again, or paste the listing details manually."

_PERMANENT_CODES = {'insufficient_quota', 'credit_balance_exhausted', 'invalid_api_key', 'billing_hard_limit_reached'}

INSTRUCTIONS = (
    'You cannot browse. Use ONLY the data provided above. For any field, metric, review analysis or '
    'competitor data that is not in the provided data, output the literal string DATA_NOT_AVAILABLE and '
    'list it under missing_data. Never invent reviews, ratings, prices or competitor figures. '
    'Scores in the scorecard are integers from 0 to 100, like overall_score. Score a category only from data you were given; '
    'if a category cannot be assessed, give it score 0 and start its issue with DATA_NOT_AVAILABLE, then say in one plain sentence '
    'what is missing and put in fix what the host should add. Never use the literal DATA_NOT_AVAILABLE inside biggest_issue: '
    'biggest_issue must be one or two plain sentences about the most important problem you could actually assess. '
    'In "suggested" never write DATA_NOT_AVAILABLE: simply leave out any detail you cannot verify and mention in "reason" what the host should add. '
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
    """One chat-completions request, retried (with a short pause) on a transient failure such as a
    timeout, a rate limit or a 5xx. Returns (text, usage)."""
    last = None
    for attempt in (1, 2, 3):
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
            logger.error('Listing Optimize: OpenAI rejected request (not retrying): model=%s error=%s', model, exc)
            raise ReportError(UNAVAILABLE_MSG) from exc
        except Exception as exc:
            last = exc
            logger.warning('Listing Optimize: OpenAI attempt %s failed: model=%s error=%s', attempt, model, exc)
            if attempt < 3:
                time.sleep(3 * attempt)
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
        logger.error('Listing Optimize: OPENAI_API_KEY / OPENAI_REPORT_MODEL / BOOSTER_REPORT_PROMPT not configured')
        raise ReportError(UNAVAILABLE_MSG)

    messages = build_messages(scraped)
    tokens_in = tokens_out = 0
    for attempt in (1, 2):
        text, usage = _post(messages, model, api_key)
        call_in, call_out = int(usage.get('prompt_tokens') or 0), int(usage.get('completion_tokens') or 0)
        tokens_in += call_in
        tokens_out += call_out
        logger.info('Listing Optimize OpenAI call %s: model=%s input_tokens=%s output_tokens=%s cost_cents=%s',
                    attempt, model, call_in, call_out, compute_cost_cents(call_in, call_out))
        try:
            result = normalize(parse_json(text))
            return result, {'input_tokens': tokens_in, 'output_tokens': tokens_out}, model
        except ValueError:
            logger.warning('Listing Optimize: unparseable model output (attempt %s): %.200r', attempt, text)
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
        logger.info('Listing Optimize %s done in %.1fs: model=%s input_tokens=%s output_tokens=%s cost_cents=%s',
                    report_id, time.monotonic() - t0, model, report.input_tokens, report.output_tokens,
                    report.cost_cents)
    except ReportError as exc:
        usage = getattr(exc, 'usage', None)
        if usage:
            report.input_tokens, report.output_tokens = usage['input_tokens'], usage['output_tokens']
            report.cost_cents = compute_cost_cents(report.input_tokens, report.output_tokens)
        _fail(report, str(exc))
    except Exception:
        logger.exception('Listing Optimize: %s crashed', report_id)
        _fail(report, FAILED_MSG)


def _fail(report, message):
    report.status = ListingReport.STATUS_FAILED
    report.error = message
    report.save(update_fields=['status', 'error', 'input_tokens', 'output_tokens', 'cost_cents'])


# ── Presentation: turn the raw analysis into something a host can read ──────

_NA_LEAD = re.compile(r'^\s*DATA_NOT_AVAILABLE\s*[:\-–]?\s*', re.I)
_NA_IS = re.compile(r'\s+(?:is|are|was|were)\s+DATA_NOT_AVAILABLE', re.I)
_NA_TAIL = re.compile(r'\s*[:\-–]\s*DATA_NOT_AVAILABLE\b\.?', re.I)


def friendly(text):
    """Replace the machine placeholder with plain English."""
    text = _text(text)
    if MISSING not in text.upper():
        return text
    text = _NA_LEAD.sub('Some details couldn’t be checked from your listing: ', text)
    text = _NA_IS.sub(' couldn’t be checked', text)
    text = _NA_TAIL.sub('', text)
    text = re.sub(r'DATA_NOT_AVAILABLE', 'not available', text, flags=re.I)
    text = re.sub(r'supplied (?:inputs?|data)', 'listing details we could read', text, flags=re.I)
    return text.strip()


def _clean_block(text):
    """Remove every part of a text that is just a missing value ("Bedrooms: DATA_NOT_AVAILABLE"),
    whether it sits on its own line or between | separators. Returns (clean text, labels removed)."""
    text = _text(text)
    if MISSING not in text.upper():
        return text, []
    dropped, lines = [], []
    for line in text.split('\n'):
        if MISSING not in line.upper():
            lines.append(line)
            continue
        keep = []
        for seg in (re.split(r'\s*\|\s*', line) if '|' in line else [line]):
            if MISSING in seg.upper():
                label = seg.split(':')[0].strip(' -•*')
                if label and label.upper() != MISSING and len(label) < 60:
                    dropped.append(label)
            else:
                keep.append(seg)
        if keep:
            lines.append(' | '.join(keep))
    return '\n'.join(lines).strip(), dropped


def grade_for(score):
    if score >= 80:
        return 'Excellent'
    if score >= 65:
        return 'Good'
    if score >= 50:
        return 'Fair'
    return 'Needs work'


def present(result):
    """Display copy of a stored result: placeholders removed, rows flagged as assessed or not,
    missing items de-duplicated. The stored JSON is never modified."""
    if not isinstance(result, dict):
        return result
    out = dict(result)
    out['biggest_issue'] = friendly(result.get('biggest_issue'))
    out['grade'] = grade_for(_int(result.get('overall_score'), 0, 0, 100))
    rows = []
    raw_rows = [r for r in result.get('scorecard') or [] if isinstance(r, dict)]
    # The model often scores categories out of 10 while the overall score is out of 100.
    scale = 10 if raw_rows and max(_int(r.get('score'), 0) for r in raw_rows) <= 10 else 1
    for row in raw_rows:
        issue, fix = _text(row.get('issue')), _text(row.get('fix'))
        assessed = MISSING not in (issue + fix).upper()
        rows.append({
            'category': _text(row.get('category')),
            'score': _int(_int(row.get('score'), 0) * scale, 0, 0, 100),
            'issue': friendly(issue),
            'fix': friendly(fix),
            'assessed': assessed,
        })
    out['scorecard'] = rows
    fields = []
    for f in result.get('fields') or []:
        if not isinstance(f, dict):
            continue
        current, _ = _clean_block(f.get('current'))
        suggested, todo = _clean_block(f.get('suggested'))
        f = dict(f)
        f['current'], f['suggested'] = current, suggested
        f['char_count'] = len(suggested)
        # What the host still has to fill in before pasting, instead of a raw placeholder in the text.
        f['todo'] = ', '.join(dict.fromkeys(label.lower() for label in todo))
        fields.append(f)
    out['fields'] = fields
    seen, missing = set(), []
    for item in result.get('missing_data') or []:
        item = _NA_TAIL.sub('', _text(item)).strip(' .:')
        item = friendly(item) if MISSING in item.upper() else item
        if item and item.lower() not in seen:
            seen.add(item.lower())
            missing.append(item)
    out['missing_data'] = missing
    return out


# ── Paywall: what a visitor sees before paying ──────────────────────────────

LOCKED_TEXT = ('Unlock the full report to see exactly what we found here and the step-by-step fix, '
               'in plain language you can act on today.')
LOCKED_REWRITE = ('Your improved wording for this part of the listing is ready. Unlock the full report to read it '
                  'and copy it straight into your listing in one click.')


FREE_ITEMS = 2   # how many items of each section an unpaid visitor can read
FREE_CARDS = 1     # ...and in the scorecard list only the weakest area is free
FREE_REWRITES = 1   # ...except the copy-paste-ready rewrites, where only the first is free


def teaser(result, paid):
    """The report as it is sent to the browser. Paid: everything. Unpaid: only FREE_ITEMS items per
    section are readable (the two weakest areas, and the first rewrite); everything else keeps
    just its title and score. The real text of locked items is replaced with filler on the server, so
    it never reaches the page (blurring alone could be undone in dev tools)."""
    if not isinstance(result, dict):
        return result
    out = dict(result)
    out['paid'] = bool(paid)
    if paid:
        return out
    rows = result.get('scorecard') or []
    # The same two areas are free in "quick wins" and in the scorecard, so nothing leaks between them.
    weakest = sorted((i for i, r in enumerate(rows) if r.get('assessed')), key=lambda i: rows[i]['score'])
    free_rows = set(weakest[:FREE_ITEMS])
    free_card = set(weakest[:FREE_CARDS])
    cards = []
    for i, row in enumerate(rows):
        row = dict(row)
        if i not in free_rows:   # also areas we couldn't score: their "what to add" advice is part of the report
            row['locked'] = True
            row['issue'] = row['fix'] = LOCKED_TEXT
        elif row.get('assessed') and i not in free_card:
            # readable in "Fix first" (already public there) but locked in the scorecard list
            row['card_locked'] = True
        cards.append(row)
    out['scorecard'] = cards
    fields = []
    usable = [f for f in result.get('fields') or [] if f.get('suggested') and f['suggested'] != MISSING]
    free_fields = {id(f) for f in usable[:FREE_REWRITES]}
    for f in result.get('fields') or []:
        if id(f) in free_fields or f not in usable:
            fields.append(f)
            continue
        fields.append({'field_name': f['field_name'], 'locked': True, 'current': LOCKED_REWRITE,
                       'suggested': LOCKED_REWRITE, 'char_count': 0, 'char_limit': 0, 'reason': ''})
    out['fields'] = fields
    return out

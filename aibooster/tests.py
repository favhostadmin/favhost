import json
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from . import scraper, services
from .models import ListingReport

LISTING_HTML = '''
<html><head><title>x</title>
<meta property="og:description" content="Entire cabin · 4 guests · 2 bedrooms · 3 beds · 1 bath">
<script type="application/ld+json">
{"@type": "LodgingBusiness", "name": "Cosy Cabin", "description": "A quiet cabin by the lake.",
 "aggregateRating": {"ratingValue": "4.8", "reviewCount": "52"},
 "amenityFeature": [{"name": "Wifi", "value": true}, {"name": "Pool", "value": false}]}
</script></head>
<body><h2>House rules</h2><p>No parties.</p><p>No smoking.</p></body></html>
'''

GOOD_REPLY = {
    'overall_score': 72, 'biggest_issue': 'Title is vague',
    'scorecard': [{'category': 'Title', 'score': 60, 'issue': 'Vague', 'fix': 'Be specific'}],
    'fields': [{'field_name': 'Title', 'current': 'Cosy Cabin', 'suggested': '**Lakeside Cabin** with Wifi',
                'char_count': 1, 'char_limit': 50, 'reason': 'Clearer'}],
    'missing_data': ['Reviews'],
}
CONF = dict(BOOSTER_REPORT_PROMPT='SYSTEM PROMPT', OPENAI_REPORT_MODEL='test-model', OPENAI_API_KEY='k')


class ScraperTests(TestCase):
    def test_parse_extracts_and_nulls(self):
        data = scraper.parse_listing(LISTING_HTML, 'https://example.com/x', 'other')
        self.assertEqual(data['title'], 'Cosy Cabin')
        self.assertEqual(data['rating'], 4.8)
        self.assertEqual(data['review_count'], 52)
        self.assertEqual((data['guests'], data['bedrooms'], data['beds'], data['bathrooms']), (4, 2, 3, 1))
        self.assertEqual(data['amenities'], ['Wifi'])
        self.assertEqual(data['house_rules'], 'No parties. No smoking.')
        self.assertIsNone(data['price'])
        self.assertIsNone(data['property_type'])
        self.assertFalse(scraper.is_sparse(data))

    def test_empty_page_is_sparse(self):
        self.assertTrue(scraper.is_sparse(scraper.parse_listing('<html></html>', 'https://e.com', 'other')))

    def test_detect_platform(self):
        d = scraper.detect_platform
        self.assertEqual(d('https://www.airbnb.co.uk/rooms/1'), 'airbnb')
        self.assertEqual(d('https://www.booking.com/hotel/x.html'), 'booking')
        self.assertEqual(d('https://favhost.com/x'), 'favhost')
        self.assertEqual(d('http://localhost/x', ['localhost']), 'favhost')
        self.assertEqual(d('https://notairbnb.com/x'), 'other')


@override_settings(**CONF)
class ServiceTests(TestCase):
    def test_messages_verbatim(self):
        msgs = services.build_messages({'title': 'T'})
        self.assertEqual(msgs[0], {'role': 'system', 'content': 'SYSTEM PROMPT'})
        self.assertIn('"title": "T"', msgs[1]['content'])
        self.assertIn('DATA_NOT_AVAILABLE', msgs[1]['content'])
        self.assertTrue(msgs[1]['content'].index('You cannot browse') > msgs[1]['content'].index('"title"'))

    def test_generate_normalizes(self):
        usage = {'prompt_tokens': 100, 'completion_tokens': 50}
        with mock.patch.object(services, '_post', return_value=(json.dumps(GOOD_REPLY), usage)):
            result, used, _ = services.generate({'title': 'T'})
        self.assertEqual(result['fields'][0]['suggested'], 'Lakeside Cabin with Wifi')
        self.assertEqual(result['fields'][0]['char_count'], len('Lakeside Cabin with Wifi'))

    def test_retry_once_then_succeed(self):
        usage = {'prompt_tokens': 10, 'completion_tokens': 5}
        with mock.patch.object(services, '_post', side_effect=[('not json', usage), (json.dumps(GOOD_REPLY), usage)]) as post:
            _, used, _ = services.generate({})
        self.assertEqual(post.call_count, 2)
        self.assertEqual(used['input_tokens'], 20)
        self.assertIn('could not be parsed', post.call_args[0][0][-1]['content'])

    def test_fail_after_retry(self):
        with mock.patch.object(services, '_post', return_value=('garbage', {})) as post:
            with self.assertRaises(services.ReportError):
                services.generate({})
        self.assertEqual(post.call_count, 2)

    def test_code_fence_tolerated(self):
        self.assertEqual(services.parse_json('```json\n{"a": 1}\n```'), {'a': 1})


@override_settings(**CONF)
class ViewTests(TestCase):
    def post(self, **data):
        return self.client.post(reverse('aibooster:report-start'), data)

    def test_sparse_url_does_not_call_ai(self):
        with mock.patch.object(scraper, 'safe_get', return_value=(b'<html></html>', 'text/html', 'utf-8')), \
                mock.patch('aibooster.views.dispatch_report') as dispatch:
            body = self.post(listing_url='https://www.airbnb.com/rooms/1').json()
        self.assertFalse(body['ok'])
        self.assertTrue(body['needs_manual'])
        dispatch.assert_not_called()
        self.assertEqual(ListingReport.objects.count(), 0)

    def test_full_flow_manual_text(self):
        usage = {'prompt_tokens': 1000, 'completion_tokens': 500}
        with mock.patch.object(services, '_post', return_value=(json.dumps(GOOD_REPLY), usage)), \
                mock.patch('aibooster.tasks.run_listing_report.apply_async', side_effect=RuntimeError('no broker')), \
                mock.patch('aibooster.tasks.connection'), mock.patch('aibooster.tasks.threading.Thread') as thread:
            body = self.post(manual_text='Cosy cabin by the lake, sleeps 4, wifi, fire pit, quiet area.').json()
            self.assertTrue(body['ok'])
            thread.call_args.kwargs['target'](*thread.call_args.kwargs['args'])  # run the worker inline
        report = ListingReport.objects.get()
        self.assertEqual(report.status, 'done')
        self.assertEqual(report.input_tokens, 1000)
        self.assertGreater(report.cost_cents, 0)
        polled = self.client.get(body['report']['status_url']).json()['report']
        self.assertEqual(polled['status'], 'done')
        self.assertEqual(polled['result']['overall_score'], 72)
        self.assertEqual(self.client.get(reverse('aibooster:report')).status_code, 200)

    def test_daily_limit(self):
        self.client.get(reverse('aibooster:report'))
        key = self.client.session.session_key
        for _ in range(10):
            ListingReport.objects.create(session_key=key)
        body = self.post(manual_text='x' * 100).json()
        self.assertFalse(body['ok'])
        self.assertIn('limit', body['message'])

    def test_status_is_session_scoped(self):
        report = ListingReport.objects.create(session_key='someone-else')
        self.assertEqual(self.client.get(reverse('aibooster:report-status', args=[report.id])).status_code, 404)

    def test_private_url_is_refused_by_scraper(self):
        body = self.post(listing_url='http://127.0.0.1/admin').json()
        self.assertFalse(body['ok'])
        self.assertTrue(body['needs_manual'])

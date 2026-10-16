from unittest import mock

from django.test import SimpleTestCase

from . import scraper


class FakeResponse:
    def __init__(self, content_type, body=b'', encoding='utf-8'):
        self.headers = {'Content-Type': content_type}
        self._body = body
        self.encoding = encoding
        self.closed = False

    def iter_content(self, size):
        yield self._body

    def close(self):
        self.closed = True


class ScrapeImagesTests(SimpleTestCase):
    def test_direct_image_link_is_used_as_the_photo(self):
        resp = FakeResponse('image/jpeg')
        url = 'https://a0.muscache.com/im/pictures/abc/original/x.jpeg?im_w=720'
        with mock.patch.object(scraper, '_follow', return_value=(resp, url)):
            self.assertEqual(scraper.scrape_images(url), [url])
        self.assertTrue(resp.closed)

    def test_html_page_still_returns_its_photos(self):
        html = b'<html><head><meta property="og:image" content="https://cdn.example.com/a.jpg"></head><body><img src="/b.jpg"></body></html>'
        resp = FakeResponse('text/html; charset=utf-8', html)
        with mock.patch.object(scraper, '_follow', return_value=(resp, 'https://example.com/room')):
            self.assertEqual(scraper.scrape_images('https://example.com/room'),
                             ['https://cdn.example.com/a.jpg', 'https://example.com/b.jpg'])

    def test_failure_returns_empty_list(self):
        with mock.patch.object(scraper, '_follow', side_effect=scraper.UnsafeURL('no')):
            self.assertEqual(scraper.scrape_images('http://127.0.0.1/x'), [])

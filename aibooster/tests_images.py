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


class FullGalleryTests(SimpleTestCase):
    def _scrape(self, html):
        resp = FakeResponse('text/html; charset=utf-8', html.encode())
        with mock.patch.object(scraper, '_follow', return_value=(resp, 'https://www.airbnb.com/rooms/1')):
            return scraper.scrape_images('https://www.airbnb.com/rooms/1')

    def test_photos_hidden_in_embedded_json_are_found_up_to_25(self):
        # Airbnb-style: a handful of <img> tags, the whole gallery inside a script (JSON-escaped slashes)
        gallery = ','.join('{"baseUrl":"https:\/\/a0.muscache.com\/im\/pictures\/miso\/Hosting-9\/original\/p%02d.jpeg"}' % i for i in range(40))
        html = ('<img src="https://a0.muscache.com/im/pictures/miso/Hosting-9/original/p00.jpeg?im_w=480">'
                '<img src="https://a0.muscache.com/im/pictures/user/abc/avatar.jpg">'
                '<script>{"photos":[' + gallery + ']}</script>')
        urls = self._scrape(html)
        self.assertEqual(len(urls), 25)
        self.assertTrue(all(u.endswith('?im_w=1200') for u in urls))          # asked for the large version
        self.assertEqual(len(set(urls)), 25)                                    # the <img> thumbnail and its JSON twin are one photo
        self.assertFalse(any('/user/' in u for u in urls))                      # host avatars are not listing photos

    def test_size_variants_of_one_booking_photo_collapse(self):
        html = ('<img src="https://cf.bstatic.com/xdata/images/hotel/max500/111.jpg">'
                '<img src="https://cf.bstatic.com/xdata/images/hotel/square60/111.jpg">'
                '<img src="https://cf.bstatic.com/xdata/images/hotel/max1024x768/222.jpg">')
        self.assertEqual(self._scrape(html), ['https://cf.bstatic.com/xdata/images/hotel/max1024x768/111.jpg',
                                              'https://cf.bstatic.com/xdata/images/hotel/max1024x768/222.jpg'])

    def test_a_small_listing_still_returns_just_its_photos(self):
        html = '<img src="https://example.com/a.jpg"><img src="https://example.com/b.jpg"><img src="https://example.com/logo.png">'
        self.assertEqual(self._scrape(html), ['https://example.com/a.jpg', 'https://example.com/b.jpg'])

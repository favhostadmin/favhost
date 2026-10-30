from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from . import payments, services
from .models import ImageJob, ListingReport, Order

PRICE = {'photos': {'id': 'price_photo', 'amount': 50, 'currency': 'usd'},
         'report': {'id': 'price_report', 'amount': 999, 'currency': 'usd'}}


def fake_price(kind):
    return PRICE[kind]


def fake_session(**extra):
    base = dict(id='cs_test_1', url='https://checkout.stripe.test/pay', payment_status='paid',
                metadata={}, amount_total=None, customer_details=SimpleNamespace(email='host@example.com', name='Host'))
    base.update(extra)
    return SimpleNamespace(**base)


@mock.patch('aibooster.payments.get_price', side_effect=fake_price)
class PaymentFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.get(reverse('aibooster:image'))   # creates the session
        self.key = self.client.session.session_key

    def _batch(self, n=4):
        jobs = []
        for i in range(n):
            jobs.append(ImageJob.objects.create(
                session_key=self.key, original_key=f'o{i}', clean_key=f'c{i}' if i == 0 else '',
                status=ImageJob.STATUS_DONE if i == 0 else ImageJob.STATUS_HELD))
        session = self.client.session
        session['aibooster_batch'] = [str(j.id) for j in jobs]
        session.save()
        return jobs

    # ---- photos ----
    def test_photo_checkout_charges_price_times_photo_count(self, _):
        self._batch(4)
        with mock.patch('aibooster.payments.stripe.checkout.Session.create', return_value=fake_session()) as create:
            data = self.client.post(reverse('aibooster:image-checkout')).json()
        self.assertTrue(data['ok'])
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs['line_items'], [{'price': 'price_photo', 'quantity': 4}])
        self.assertEqual(kwargs['mode'], 'payment')
        order = Order.objects.get()
        self.assertEqual((order.quantity, order.amount_total, order.status), (4, 200, Order.STATUS_PENDING))

    def test_download_needs_payment_then_works(self, _):
        jobs = self._batch(2)
        r = self.client.post(reverse('aibooster:image-unlock')).json()
        self.assertTrue(r.get('needs_payment'))
        order = Order.objects.create(kind=Order.KIND_PHOTOS, session_key=self.key,
                                     job_ids=[str(j.id) for j in jobs], quantity=2)
        with mock.patch('aibooster.tasks.dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                payments.fulfill(order.id, fake_session())
        self.assertEqual(ImageJob.objects.filter(is_paid=True).count(), 2)
        held_now = ImageJob.objects.get(pk=jobs[1].id)
        self.assertEqual(held_now.status, ImageJob.STATUS_PENDING)
        dispatch.assert_called_once_with(jobs[1].id)
        # the released photo is still being enhanced, so the download is held back until it is done
        self.assertTrue(self.client.post(reverse('aibooster:image-unlock')).json()['enhancing'])
        ImageJob.objects.filter(pk=jobs[1].id).update(status=ImageJob.STATUS_DONE, clean_key='c1')
        self.assertTrue(self.client.post(reverse('aibooster:image-unlock')).json()['ok'])

    def test_fulfill_is_idempotent(self, _):
        jobs = self._batch(2)
        order = Order.objects.create(kind=Order.KIND_PHOTOS, session_key=self.key,
                                     job_ids=[str(j.id) for j in jobs], quantity=2)
        with mock.patch('aibooster.tasks.dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                payments.fulfill(order.id, fake_session())
                payments.fulfill(order.id, fake_session())
        self.assertEqual(dispatch.call_count, 1)

    def test_unpaid_download_link_is_refused(self, _):
        jobs = self._batch(1)
        from .views import _download_url
        resp = self.client.get(_download_url(jobs))
        self.assertEqual(resp.status_code, 403)

    # ---- report ----
    def _report(self, paid=False):
        result = {
            'overall_score': 51, 'biggest_issue': 'Thin description.',
            'scorecard': [{'category': c, 'score': s, 'issue': f'issue {c}', 'fix': f'fix {c}'}
                          for c, s in (('Title', 60), ('Photos', 30), ('Pricing', 40), ('Rules', 50))],
            'fields': [{'field_name': n, 'current': 'old ' + n, 'suggested': 'new ' + n, 'char_count': 5, 'char_limit': 50, 'reason': 'because'}
                       for n in ('Title', 'Description', 'Amenities', 'Rules')],
            'missing_data': [],
        }
        report = ListingReport.objects.create(session_key=self.key, status=ListingReport.STATUS_DONE,
                                              result_json=result, is_paid=paid)
        session = self.client.session
        session['aibooster_report'] = str(report.id)
        session.save()
        return report

    def test_unpaid_report_never_sends_locked_text(self, _):
        report = self._report()
        res = self.client.get(reverse('aibooster:report-status', args=[report.id])).json()['report']
        self.assertFalse(res['paid'])
        self.assertEqual(res['download_url'], '')
        body = str(res['result'])
        # scores are Title 60, Photos 30, Pricing 40, Rules 50: the two weakest (Photos, Pricing) are free
        for hidden in ('issue Title', 'fix Title', 'issue Rules', 'fix Rules', 'new Description', 'new Amenities', 'new Rules', 'old Rules'):
            self.assertNotIn(hidden, body)
        for shown in ('issue Photos', 'fix Pricing', 'new Title'):   # only the first rewrite is free
            self.assertIn(shown, body)
        locked = [c for c in res['result']['scorecard'] if c.get('locked')]
        self.assertEqual(len(locked), 2)
        cl = [c['category'] for c in res['result']['scorecard'] if c.get('card_locked')]
        self.assertEqual(cl, ['Pricing'])   # 2nd weakest: readable in Fix first, locked in the scorecard list

    def test_pdf_blocked_until_paid_then_report_complete(self, _):
        report = self._report()
        self.assertEqual(self.client.get(reverse('aibooster:report-download', args=[report.id])).status_code, 403)
        with mock.patch('aibooster.payments.stripe.checkout.Session.create', return_value=fake_session()) as create:
            data = self.client.post(reverse('aibooster:report-checkout')).json()
        self.assertTrue(data['ok'])
        self.assertEqual(create.call_args.kwargs['line_items'], [{'price': 'price_report', 'quantity': 1}])
        order = Order.objects.get()
        payments.fulfill(order.id, fake_session())
        res = self.client.get(reverse('aibooster:report-status', args=[report.id])).json()['report']
        self.assertTrue(res['paid'])
        self.assertIn('fix Rules', str(res['result']))
        pdf = self.client.get(reverse('aibooster:report-download', args=[report.id]))
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))

    def test_return_from_stripe_verifies_with_stripe(self, _):
        report = self._report()
        order = Order.objects.create(kind=Order.KIND_REPORT, session_key=self.key, report=report, quantity=1)
        paid = fake_session(metadata={'ai_order_id': str(order.id)})
        with mock.patch('aibooster.payments.stripe.checkout.Session.retrieve', return_value=paid):
            resp = self.client.get(reverse('aibooster:report') + '?session_id=cs_test_1')
        self.assertEqual(resp.status_code, 302)
        report.refresh_from_db()
        self.assertTrue(report.is_paid)
        page = self.client.get(reverse('aibooster:report'))
        self.assertContains(page, 'Payment received')

    def test_unpaid_session_does_not_unlock(self, _):
        report = self._report()
        order = Order.objects.create(kind=Order.KIND_REPORT, session_key=self.key, report=report, quantity=1)
        unpaid = fake_session(metadata={'ai_order_id': str(order.id)}, payment_status='unpaid')
        with mock.patch('aibooster.payments.stripe.checkout.Session.retrieve', return_value=unpaid):
            self.client.get(reverse('aibooster:report') + '?session_id=cs_test_1')
        report.refresh_from_db()
        self.assertFalse(report.is_paid)

    def test_webhook_routing(self, _):
        report = self._report()
        order = Order.objects.create(kind=Order.KIND_REPORT, session_key=self.key, report=report, quantity=1)
        self.assertTrue(payments.handle_webhook_session(fake_session(metadata={'ai_order_id': str(order.id)})))
        report.refresh_from_db()
        self.assertTrue(report.is_paid)
        self.assertFalse(payments.handle_webhook_session(fake_session(metadata={})))   # a subscription checkout


class StartOverTests(TestCase):
    def setUp(self):
        self.client.get(reverse('aibooster:image'))
        self.key = self.client.session.session_key

    def _session(self, **items):
        session = self.client.session
        session.update(items)
        session.save()

    def test_unpaid_photos_are_deleted_paid_ones_kept(self):
        unpaid = ImageJob.objects.create(session_key=self.key, status=ImageJob.STATUS_DONE, original_key='o1')
        paid = ImageJob.objects.create(session_key=self.key, status=ImageJob.STATUS_DONE, original_key='o2', is_paid=True)
        self._session(aibooster_batch=[str(unpaid.id), str(paid.id)])
        with mock.patch('aibooster.storage.get_storage') as get_storage:
            self.assertTrue(self.client.post(reverse('aibooster:image-reset')).json()['ok'])
        self.assertFalse(ImageJob.objects.filter(pk=unpaid.id).exists())
        self.assertTrue(ImageJob.objects.filter(pk=paid.id).exists())
        get_storage.return_value.delete.assert_called_once_with('o1')
        self.assertNotIn('aibooster_batch', self.client.session)

    def test_running_job_is_not_deleted_under_the_worker(self):
        busy = ImageJob.objects.create(session_key=self.key, status=ImageJob.STATUS_PROCESSING)
        self._session(aibooster_batch=[str(busy.id)])
        self.client.post(reverse('aibooster:image-reset'))
        self.assertTrue(ImageJob.objects.filter(pk=busy.id).exists())

    def test_report_reset(self):
        unpaid = ListingReport.objects.create(session_key=self.key, status=ListingReport.STATUS_DONE)
        self._session(aibooster_report=str(unpaid.id))
        self.assertTrue(self.client.post(reverse('aibooster:report-reset')).json()['ok'])
        self.assertFalse(ListingReport.objects.filter(pk=unpaid.id).exists())
        paid = ListingReport.objects.create(session_key=self.key, status=ListingReport.STATUS_DONE, is_paid=True)
        self._session(aibooster_report=str(paid.id))
        self.client.post(reverse('aibooster:report-reset'))
        self.assertTrue(ListingReport.objects.filter(pk=paid.id).exists())
        self.assertNotIn('aibooster_report', self.client.session)

    def test_reset_needs_post(self):
        self.assertEqual(self.client.get(reverse('aibooster:image-reset')).status_code, 405)


class AddMorePhotosTests(TestCase):
    def setUp(self):
        self.client.get(reverse('aibooster:image'))
        self.key = self.client.session.session_key

    def _png(self, name='a.png'):
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (20, 20), 'red').save(buf, 'PNG')
        return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')

    def _start(self, n, **extra):
        data = {'images': [self._png(f'p{i}.png') for i in range(n)], 'listing_url': ''}
        data.update(extra)
        with mock.patch('aibooster.views.dispatch') as dispatch, \
                mock.patch('aibooster.storage.save_bytes', side_effect=lambda key, b: key):
            r = self.client.post(reverse('aibooster:image-start'), data).json()
        return r, dispatch

    def test_added_photos_join_the_batch_locked(self):
        first, d1 = self._start(3)
        self.assertEqual(len(first['jobs']), 3)
        d1.assert_called_once()
        more, d2 = self._start(2, append='1')
        self.assertTrue(more['ok'])
        self.assertEqual(len(more['jobs']), 5)
        self.assertEqual([j['id'] for j in more['jobs'][:3]], [j['id'] for j in first['jobs']])
        d2.assert_not_called()   # nothing new is enhanced before payment
        self.assertEqual(ImageJob.objects.filter(status=ImageJob.STATUS_HELD).count(), 4)

    def test_batch_is_capped(self):
        self._start(24)
        more, _ = self._start(5, append='1')
        self.assertEqual(len(more['jobs']), 25)
        again, _ = self._start(1, append='1')
        self.assertFalse(again['ok'])

    def test_no_adding_after_payment(self):
        first, _ = self._start(2)
        ImageJob.objects.filter(pk=first['jobs'][0]['id']).update(is_paid=True)
        more, _ = self._start(1, append='1')
        self.assertFalse(more['ok'])
        self.assertEqual(ImageJob.objects.count(), 2)


def real_session(order_id, **extra):
    """A genuine stripe-python object (not a dict), like Stripe returns in production."""
    import stripe
    data = {'id': 'cs_live_x', 'object': 'checkout.session', 'payment_status': 'paid', 'amount_total': 999,
            'metadata': {'ai_order_id': str(order_id)} if order_id else {},
            'customer_details': {'email': 'host@example.com', 'name': 'Host'}}
    data.update(extra)
    return stripe.checkout.Session.construct_from(data, 'sk_test')


@mock.patch('aibooster.payments.get_price', side_effect=fake_price)
class RealStripeObjectTests(TestCase):
    """Regression: a StripeObject has no .get(), which crashed the return trip from Stripe."""

    def setUp(self):
        cache.clear()
        self.client.get(reverse('aibooster:image'))
        self.key = self.client.session.session_key

    def _return(self, route, order, **extra):
        with mock.patch('aibooster.payments.stripe.checkout.Session.retrieve', return_value=real_session(order.id, **extra)):
            resp = self.client.get(reverse(route) + '?session_id=cs_live_x')
        self.assertEqual(resp.status_code, 302)       # redirected to the clean URL, no error page
        return self.client.get(reverse(route))

    def test_photo_return_trip_then_page_renders(self, _):
        jobs = [ImageJob.objects.create(session_key=self.key, original_key='o', clean_key='c', watermarked_key='w',
                                        status=ImageJob.STATUS_DONE),
                ImageJob.objects.create(session_key=self.key, original_key='o2', status=ImageJob.STATUS_HELD)]
        session = self.client.session
        session['aibooster_batch'] = [str(j.id) for j in jobs]
        session.save()
        order = Order.objects.create(kind=Order.KIND_PHOTOS, session_key=self.key, job_ids=[str(j.id) for j in jobs], quantity=2)
        with mock.patch('aibooster.tasks.dispatch'):
            with self.captureOnCommitCallbacks(execute=True):
                page = self._return('aibooster:image', order)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Payment received')
        self.assertEqual(ImageJob.objects.filter(is_paid=True).count(), 2)
        order.refresh_from_db()
        self.assertEqual((order.status, order.customer_email), (Order.STATUS_PAID, 'host@example.com'))

    def test_report_return_trip_then_page_renders(self, _):
        report = ListingReport.objects.create(session_key=self.key, status=ListingReport.STATUS_DONE, is_paid=False,
                                              result_json={'overall_score': 50, 'scorecard': [], 'fields': [], 'missing_data': []})
        session = self.client.session
        session['aibooster_report'] = str(report.id)
        session.save()
        order = Order.objects.create(kind=Order.KIND_REPORT, session_key=self.key, report=report, quantity=1)
        page = self._return('aibooster:report', order)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Payment received')
        report.refresh_from_db()
        self.assertTrue(report.is_paid)

    def test_webhook_with_real_object(self, _):
        report = ListingReport.objects.create(session_key=self.key, status=ListingReport.STATUS_DONE)
        order = Order.objects.create(kind=Order.KIND_REPORT, session_key=self.key, report=report, quantity=1)
        self.assertTrue(payments.handle_webhook_session(real_session(order.id)))
        report.refresh_from_db()
        self.assertTrue(report.is_paid)
        self.assertFalse(payments.handle_webhook_session(real_session(None)))   # a subscription checkout

    def test_unpaid_real_session_does_not_unlock_and_does_not_crash(self, _):
        report = ListingReport.objects.create(session_key=self.key, status=ListingReport.STATUS_DONE)
        order = Order.objects.create(kind=Order.KIND_REPORT, session_key=self.key, report=report, quantity=1)
        self._return('aibooster:report', order, payment_status='unpaid')
        report.refresh_from_db()
        self.assertFalse(report.is_paid)


class AfterPaymentTests(TestCase):
    def setUp(self):
        self.client.get(reverse('aibooster:image'))
        self.key = self.client.session.session_key

    def _batch(self, *jobs):
        session = self.client.session
        session['aibooster_batch'] = [str(j.id) for j in jobs]
        session.save()

    def test_preview_is_watermarked_until_paid_then_clean(self):
        job = ImageJob.objects.create(session_key=self.key, status=ImageJob.STATUS_DONE, clean_key='CLEAN', watermarked_key='MARKED')
        with mock.patch('aibooster.views._stream', return_value=HttpResponse('x')) as stream:
            self.client.get(reverse('aibooster:image-after', args=[job.id]))
            stream.assert_called_with('MARKED')
            ImageJob.objects.filter(pk=job.id).update(is_paid=True)
            self.client.get(reverse('aibooster:image-after', args=[job.id]))
            stream.assert_called_with('CLEAN')

    def test_download_waits_until_every_paid_photo_is_enhanced(self):
        done = ImageJob.objects.create(session_key=self.key, status=ImageJob.STATUS_DONE, clean_key='c', is_paid=True)
        busy = ImageJob.objects.create(session_key=self.key, status=ImageJob.STATUS_PROCESSING, is_paid=True)
        self._batch(done, busy)
        r = self.client.post(reverse('aibooster:image-unlock'))
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()['enhancing'])
        ImageJob.objects.filter(pk=busy.id).update(status=ImageJob.STATUS_DONE, clean_key='c2')
        r = self.client.post(reverse('aibooster:image-unlock'))
        self.assertTrue(r.json()['ok'])


class RemovePhotoTests(TestCase):
    def setUp(self):
        self.client.get(reverse('aibooster:image'))
        self.key = self.client.session.session_key
        self.jobs = [ImageJob.objects.create(session_key=self.key, original_key=f'o{i}',
                                             status=ImageJob.STATUS_DONE if i == 0 else ImageJob.STATUS_HELD) for i in range(3)]
        session = self.client.session
        session['aibooster_batch'] = [str(j.id) for j in self.jobs]
        session.save()

    def _remove(self, job):
        with mock.patch('aibooster.storage.get_storage'):
            return self.client.post(reverse('aibooster:image-remove'), {'id': str(job.id)})

    def test_a_locked_photo_can_be_removed(self):
        self.assertTrue(self._remove(self.jobs[1]).json()['ok'])
        self.assertFalse(ImageJob.objects.filter(pk=self.jobs[1].id).exists())
        self.assertEqual(self.client.session['aibooster_batch'], [str(self.jobs[0].id), str(self.jobs[2].id)])

    def test_first_paid_or_running_photos_stay(self):
        self.assertEqual(self._remove(self.jobs[0]).status_code, 400)
        ImageJob.objects.filter(pk=self.jobs[2].id).update(is_paid=True)
        self.assertEqual(self._remove(self.jobs[2]).status_code, 400)
        ImageJob.objects.filter(pk=self.jobs[1].id).update(status=ImageJob.STATUS_PROCESSING)
        self.assertEqual(self._remove(self.jobs[1]).status_code, 400)
        self.assertEqual(ImageJob.objects.count(), 3)

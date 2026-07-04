# bookings/utils.py
import requests
import re
from icalendar import Calendar
from celery import shared_task
from django.utils import timezone
from property.models import PropertyChannel, PropertyBlockDate
from booking.models import Booking, Payment
import logging
from datetime import datetime, timedelta


def fetch_ical_events(calendar_url):
    # Add User-Agent to avoid being blocked by some calendar providers (e.g. Airbnb)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    if not calendar_url:
        return []

    response = requests.get(calendar_url.strip(), headers=headers, timeout=20)
    response.raise_for_status()

    # calendar = Calendar.from_ical(response.text)

    calendar = Calendar.from_ical(response.content)
    return calendar.walk('VEVENT')


logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_property_channel(self, channel_id):
    """
    Syncs a single PropertyChannel.
    Fetches iCal feed, upserts bookings, and cancels missing future bookings.
    """

    try:
        # Select related to minimize DB queries
        channel = PropertyChannel.objects.filter(is_connected=True).select_related('property', 'channel_type').get(id=channel_id)
    except PropertyChannel.DoesNotExist:
        # logger.error(f"PropertyChannel {channel_id} not found.")
        return
    
    logger.info(f"Starting sync for {channel}")


    try:
        events = fetch_ical_events(channel.calendar_link)
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error fetching iCal for {channel}: {e}")
        if 400 <= e.response.status_code < 500:
            return  # Do not retry client errors (400 Bad Request, 404 Not Found, etc.)
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"Failed to fetch iCal for {channel}: {e}")
        # Retry on network failure
        raise self.retry(exc=e)

    logger.info(f"Fetched {len(events)} events for {channel}")

    synced_booking_uids = []
    synced_block_uids = []
    
    for event in events:
        uid = event.get('UID')
        if not uid:
            continue
            
        # Ensure UID is a string
        if hasattr(uid, 'to_ical'):
             uid = uid.to_ical().decode('utf-8')
        else:
             uid = str(uid)

        dtstart = event.get('DTSTART')
        dtend = event.get('DTEND')
        
        if not dtstart or not dtend:
            continue
            
        # .dt returns a python date or datetime object
        start_date = dtstart.dt
        end_date = dtend.dt
        
        # Normalize to date objects
        if isinstance(start_date, datetime):
            start_date = start_date.date()
        if isinstance(end_date, datetime):
            end_date = end_date.date()

        if start_date >= end_date:
            continue
            
        # Extract summary and description
        summary = event.get('SUMMARY')
        description = event.get('DESCRIPTION')

        # Decode iCal fields if necessary
        if summary and hasattr(summary, 'to_ical'):
            summary = summary.to_ical().decode('utf-8')
        
        if description and hasattr(description, 'to_ical'):
            description = description.to_ical().decode('utf-8')

        summary_lower = summary.lower() if summary else ""

        # --- 1. Handle Blocked Dates ---
        # Detect blocked dates based on common keywords across channels (Agoda, Booking.com, Expedia, etc.)
        if any(keyword in summary_lower for keyword in ['blocked', 'not available', 'closed', 'unavailable', 'airbnb (not available)']):
            # Delete existing segments for this external_uid to recalculate based on current local bookings
            PropertyBlockDate.objects.filter(external_uid=uid, property=channel.property).delete()

            # Find local confirmed bookings that overlap with this external block range
            overlapping_bookings = Booking.objects.filter(
                property=channel.property,
                status='confirmed',
                check_in_date__lt=end_date,
                check_out_date__gt=start_date
            ).order_by('check_in_date')

            block_segments = []
            current_ptr = start_date

            for booking in overlapping_bookings:
                if booking.check_in_date > current_ptr:
                    # Create a block segment from the current pointer to the start of the booking
                    block_segments.append(PropertyBlockDate(
                        external_uid=uid,
                        property=channel.property,
                        start_date=current_ptr,
                        end_date=booking.check_in_date,
                        reason=description or f"Imported block from {channel.channel_type.name}",
                        is_active=True
                    ))
                # Move pointer to the end of the booking to skip the occupied range
                current_ptr = max(current_ptr, booking.check_out_date)

            # Create a final segment if there is remaining time after the last booking
            if current_ptr < end_date:
                block_segments.append(PropertyBlockDate(
                    external_uid=uid,
                    property=channel.property,
                    start_date=current_ptr,
                    end_date=end_date,
                    reason=description or f"Imported block from {channel.channel_type.name}",
                    is_active=True
                ))

            if block_segments:
                PropertyBlockDate.objects.bulk_create(block_segments)

            synced_block_uids.append(uid)
            continue

        # --- 2. Handle Cancelled Bookings ---
        if 'cancelled' in summary_lower:
            Booking.objects.filter(external_uid=uid).update(status='cancelled', last_synced_at=timezone.now())
            continue


        # --- 3. Handle Tentative Bookings ---
        if 'tentative' in summary_lower:
            print("Tentative booking found, skipping...")
            logger.info(f"Ignored tentative event {uid} for {channel}")
            Booking.objects.filter(external_uid=uid).update(status='cancelled', last_synced_at=timezone.now())
            continue

        # --- 4. Handle Reserved (Bookings) ---
        notes = f"Imported from {channel.channel_type.name}"
        
        if summary:
            notes += f"\nSummary: {summary}"

        guest_first_name = channel.channel_type.name
        guest_last_name = 'Guest'

        if description:
            notes += f"\nDescription: {description}"

            # Parse guest name from Airbnb description
            # Format: "Booking via Airbnb – Guest: John Doe"
            if 'Guest:' in description:
                try:
                    guest_info = description.split('Guest:')[-1].strip()
                    if guest_info:
                        name_parts = guest_info.split(' ', 1)
                        if len(name_parts) == 2:
                            guest_first_name = name_parts[0]
                            guest_last_name = name_parts[1]
                        else:
                            guest_first_name = guest_info
                            guest_last_name = ''
                except Exception:
                    pass

        property_price = channel.property.price_per_night or 0
        cleaning_price = channel.property.cleaning_fee or 0
        deposit_fee = channel.property.refundable_deposit or 0
        application_fee = channel.property.application_fees or 0

        total_night = (end_date - start_date).days
        total_price = property_price * total_night

        # Check if booking exists to handle updates and payment regeneration
        booking_qs = Booking.objects.filter(external_uid=uid, property=channel.property)
        
        if booking_qs.exists():
            booking = booking_qs.first()
            synced_booking_uids.append(uid)
            dates_changed = (booking.check_in_date != start_date) or (booking.check_out_date != end_date)

            # If the channel moved this booking's dates, make sure the new
            # range doesn't now clash with a *different* confirmed booking
            # for this property before applying it — otherwise we'd silently
            # create two overlapping reservations for the same listing.
            if dates_changed:
                conflicting_booking = Booking.objects.filter(
                    property=channel.property,
                    status='confirmed',
                    check_in_date__lt=end_date,
                    check_out_date__gt=start_date
                ).exclude(pk=booking.pk).exists()

                if conflicting_booking:
                    logger.warning(
                        f"Skipped date update for booking {booking.id} ({uid}): "
                        f"new dates {start_date}–{end_date} overlap with another "
                        f"confirmed booking for {channel.property}. Keeping existing dates."
                    )
                    booking.status = 'confirmed'
                    booking.notes = notes
                    booking.last_synced_at = timezone.now()
                    booking.save()
                    continue

            # Update fields
            # booking.first_name = guest_first_name
            # booking.last_name = guest_last_name
            # Do not overwrite first_name, last_name, phone, email, or notes
            # to ensure that manual changes made by the admin are preserved.
            booking.check_in_date = start_date
            booking.check_out_date = end_date
            booking.status = 'confirmed'
            booking.notes = notes
            booking.last_synced_at = timezone.now()
            booking.save()

            if dates_changed:
                logger.info(f"Booking {booking.id} dates updated via iCal. Regenerating payments.")
                booking.payments.all().delete()
                generate_booking_payments(booking)
        else:
            # Find local confirmed bookings that overlap with this external reservation
            overlapping_bookings = Booking.objects.filter(
                property=channel.property,
                status='confirmed',
                check_in_date__lt=end_date,
                check_out_date__gt=start_date
            ).order_by('check_in_date')

            if overlapping_bookings.exists():
                logger.warning(f"External reservation {uid} overlaps with local bookings. Converting non-overlapping parts to block dates.")
                
                # Create blocks for the gaps instead of a booking record
                PropertyBlockDate.objects.filter(external_uid=uid, property=channel.property).delete()
                block_segments = []
                current_ptr = start_date

                for booking in overlapping_bookings:
                    if booking.check_in_date > current_ptr:
                        block_segments.append(PropertyBlockDate(
                            external_uid=uid,
                            property=channel.property,
                            start_date=current_ptr,
                            end_date=booking.check_in_date,
                            reason=f"Reservation {summary} (Conflict with local booking)",
                            is_active=True
                        ))
                    current_ptr = max(current_ptr, booking.check_out_date)

                if current_ptr < end_date:
                    block_segments.append(PropertyBlockDate(
                        external_uid=uid,
                        property=channel.property,
                        start_date=current_ptr,
                        end_date=end_date,
                        reason=f"Reservation {summary} (Conflict with local booking)",
                        is_active=True
                    ))

                if block_segments:
                    PropertyBlockDate.objects.bulk_create(block_segments)
                
                synced_block_uids.append(uid)
                continue

            # No overlap found, create the booking normally
            # Ensure we remove any old blocks for this UID if it's now a valid booking
            PropertyBlockDate.objects.filter(external_uid=uid, property=channel.property).delete()
            synced_booking_uids.append(uid)

            booking = Booking.objects.create(
                external_uid=uid,
                property=channel.property,
                first_name=guest_first_name,
                last_name=guest_last_name,
                guest_count=1,
                channel=channel.channel_type,
                check_in_date=start_date,
                check_out_date=end_date,
                status='confirmed',
                notes=notes,
                last_synced_at=timezone.now(),
                price_per_night=property_price,
                price=total_price,
                cleaning_fee=cleaning_price,
                deposit_fee=deposit_fee,
                application_fee=application_fee
            )
            logger.info(f"Created booking {booking.id} for {channel}")
            generate_booking_payments(booking)

    # Cancel missing future bookings for this specific channel
    today = timezone.now().date()
    
    missing_bookings = Booking.objects.filter(
        property=channel.property,
        channel=channel.channel_type,
        status='confirmed',
        check_in_date__gte=today,
        external_uid__isnull=False
    ).exclude(external_uid__in=synced_booking_uids)
    
    if missing_bookings.exists():
        count = missing_bookings.update(status='cancelled', last_synced_at=timezone.now())
        logger.info(f"Cancelled {count} missing bookings for {channel}")

    # Delete missing future blocked dates
    missing_blocks = PropertyBlockDate.objects.filter(
        property=channel.property,
        external_uid__isnull=False,
        end_date__gte=today
    ).exclude(external_uid__in=synced_block_uids)

    if missing_blocks.exists():
        count = missing_blocks.count()
        missing_blocks.delete()
        logger.info(f"Deleted {count} missing blocked dates for {channel}")

    logger.info(f"Successfully synced {channel}")

@shared_task
def trigger_sync_all_channels():
    """
    Periodic task to trigger sync for all connected channels.
    """
    channels = PropertyChannel.objects.filter(is_connected=True)
    logger.info(f"Periodic sync started: Found {channels.count()} channels.")
    for channel in channels:
        sync_property_channel.delay(channel.id)

def generate_booking_payments(booking):
    """
    Generates payment schedule for a booking.
    Creates Payment objects for deposits, fees, and rent installments.
    """
    
    def date_to_datetime(date_obj):
        """Convert a date object to timezone-aware datetime at start of day"""
        if date_obj is None:
            return None
        return timezone.make_aware(datetime.combine(date_obj, datetime.min.time()))
    
    # Determine the due date for upfront fees (deposit, application fee)
    first_due_date = None
    if booking.check_in_date:
        first_due_date = date_to_datetime(booking.check_in_date - timedelta(days=1))

    payments_to_create = []

    if (booking.deposit_fee or 0) > 0:
        payments_to_create.append(Payment(
            booking=booking,
            type='Refundable deposit',
            amount=booking.deposit_fee,
            is_paid=False,
            expected_payment_date=first_due_date
        ))

    if (booking.cleaning_fee or 0) > 0:
        payments_to_create.append(Payment(
            booking=booking,
            type='Cleaning Fee',
            amount=booking.cleaning_fee,
            is_paid=False,
            expected_payment_date=first_due_date
        ))

    if (booking.application_fee or 0) > 0:
        payments_to_create.append(Payment(
            booking=booking,
            type='Application Fee',
            amount=booking.application_fee,
            is_paid=False,
            expected_payment_date=first_due_date
        ))

    if booking.check_in_date and booking.check_out_date:
        installment_start_date = booking.check_in_date
        installment_num = 1
        while installment_start_date < booking.check_out_date:
            # The end of the current 30-day installment period
            period_end_date = installment_start_date + timedelta(days=30)
            
            # The actual end date for this installment is the earlier of the period end or the checkout date
            installment_end_date = min(period_end_date, booking.check_out_date)
            
            # Calculate number of days for this installment
            days_in_period = (installment_end_date - installment_start_date).days
            if days_in_period <= 0:
                break

            amount = days_in_period * booking.price_per_night
            
            # Payment is due 30 days before the installment period starts
            payment_due_date = date_to_datetime(installment_start_date - timedelta(days=1))

            payments_to_create.append(Payment(
                booking=booking,
                type=f'Payment {installment_num}',
                amount=amount,
                expected_payment_date=payment_due_date,
                is_paid=False
            ))

            installment_start_date = period_end_date
            installment_num += 1

    if (booking.deposit_fee or 0) > 0:
        payments_to_create.append(Payment(
            booking=booking,
            type='Refundable to guest',
            amount=booking.deposit_fee,
            is_paid=False,
            expected_payment_date=date_to_datetime(booking.check_out_date)
        ))
    
    Payment.objects.bulk_create(payments_to_create)

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
import random
import uuid
from accounts.models import MyUser
from property.models import Property
from booking.models import Booking, BookingChannel, Enquiry, Payment
from tasks.models import Task


WEEK_START = date(2026, 6, 15)
WEEK_END = date(2026, 6, 21)

GUEST_NAMES = [
    ("John", "Smith", "john.smith@email.com", "+1", "2125550101"),
    ("Sarah", "Johnson", "sarah.j@email.com", "+1", "3105550202"),
    ("Michael", "Brown", "michael.b@email.com", "+44", "2075550303"),
    ("Emily", "Davis", "emily.davis@email.com", "+1", "4155550404"),
    ("James", "Wilson", "james.w@email.com", "+61", "285550505"),
    ("Maria", "Garcia", "maria.garcia@email.com", "+34", "915550606"),
    ("David", "Rodriguez", "david.r@email.com", "+1", "3055550707"),
    ("Lisa", "Anderson", "lisa.a@email.com", "+1", "7025550808"),
    ("Robert", "Taylor", "robert.t@email.com", "+44", "1615550909"),
    ("Jennifer", "Thomas", "jennifer.t@email.com", "+1", "6175551010"),
    ("Daniel", "Jackson", "daniel.j@email.com", "+1", "2065551111"),
    ("Sophie", "Martin", "sophie.m@email.com", "+33", "155551212"),
    ("Chris", "Lee", "chris.lee@email.com", "+1", "8085551313"),
    ("Anna", "Kim", "anna.kim@email.com", "+82", "255551414"),
    ("Thomas", "Mueller", "thomas.m@email.com", "+49", "3055551515"),
    ("Olivia", "Brown", "olivia.b@email.com", "+44", "2085551616"),
    ("Ethan", "Miller", "ethan.m@email.com", "+1", "3125551717"),
    ("Noah", "Phillips", "noah.p@email.com", "+1", "4045551818"),
    ("Emma", "Roberts", "emma.r@email.com", "+61", "295551919"),
    ("Mason", "Davis", "mason.d@email.com", "+1", "5035552020"),
]

TASK_DESCRIPTIONS = {
    "cleaning": [
        "Deep clean all rooms including under beds",
        "Change all bed linens and towels",
        "Restock bathroom amenities (soap, shampoo, toilet paper)",
        "Mop all hard floors and vacuum carpets",
        "Clean kitchen appliances and wipe all surfaces",
        "Wash windows and balcony doors",
        "Disinfect all high-touch surfaces",
        "Professional carpet steam cleaning",
        "Clean patio furniture and sweep balcony",
        "Wipe down all kitchen cabinets and drawers",
    ],
    "maintenance": [
        "Fix leaking faucet in bathroom sink",
        "Replace air conditioning filter",
        "Check and refill pool chemical levels",
        "Inspect smoke detectors and replace batteries",
        "Unclog shower drain",
        "Repair loose cabinet handle in kitchen",
        "Service HVAC system before guest arrival",
        "Touch up paint on scratched walls in hallway",
        "Replace burnt-out light bulbs throughout",
        "Fix squeaky bedroom door hinge",
        "Check water heater pressure and temperature",
        "Clean gutters and downspouts",
        "Replace broken window blind cord",
        "Fix toilet running continuously",
    ],
    "payment": [
        "Process outstanding invoice for booking deposit",
        "Send payment reminder for balance due",
        "Reconcile credit card settlement for last month",
        "Process refund for cancelled reservation",
        "Issue invoice for additional guest charges",
    ],
    "other": [
        "Order new welcome basket supplies for check-ins",
        "Update house manual with new WiFi instructions",
        "Print and frame new emergency exit map",
        "Restock first aid kit",
        "Coordinate with photographer for new listing photos",
        "Schedule annual termite inspection",
        "Buy welcome chocolates and wine for guests",
        "Arrange airport transfer for incoming guests",
    ],
}

ENQUIRY_NOTES = [
    "We are a family of 4 looking for a quiet getaway. Do you offer early check-in?",
    "Interested in booking for a business trip. Is there a desk in the room?",
    "Celebrating our anniversary! Any special packages available?",
    "Traveling with our small dog (well-trained). Is pet-friendly available?",
    "Looking for a long-term stay (3 weeks). Any monthly discount?",
    "We need two adjoining rooms if possible. Do you have availability?",
    "Is there parking included? We will be renting a car.",
    "Do you provide airport pickup service? Arriving at 11 PM.",
    "We have a late flight on checkout day. Is luggage storage available?",
    "Interested in booking for a small photoshoot. Are we allowed extra guests?",
    "We have guests with mobility issues. Is the property wheelchair accessible?",
    "Is breakfast included or are there nearby cafes?",
    "Do you have a crib available for our infant?",
    "Can we check in as early as noon? We have a conference nearby.",
    "Looking to book for a group of 6. Do you have extra beds?",
]

ASSIGNED_STAFF = ["Mike", "Sarah", "Carlos", "Emma", "Priya", "John", "Maria", "David", "Lisa", ""]


def get_guest(idx):
    g = GUEST_NAMES[idx % len(GUEST_NAMES)]
    return {"first_name": g[0], "last_name": g[1], "email": g[2], "country_code": g[3], "phone": g[4]}


class Command(BaseCommand):
    help = "Seed realistic hotel data for the week of June 15-21, 2026"

    def handle(self, *args, **options):
        self.stdout.write("Seeding weekly hotel data...\n")

        hosts = list(MyUser.objects.filter(is_staff=False, is_admin=False)[:6])
        if not hosts:
            hosts = list(MyUser.objects.all()[:3])
        host = hosts[0]
        properties = list(Property.objects.all())
        channels = list(BookingChannel.objects.all())

        existing_ids = set(
            Booking.objects.filter(
                check_in_date__gte=WEEK_START, check_in_date__lte=WEEK_END
            ).values_list("property_id", flat=True)
        )

        guest_counter = [0]

        def next_guest():
            g = get_guest(guest_counter[0])
            guest_counter[0] += 1
            return g

        created_count = 0

        for prop in properties:
            if prop.id in existing_ids:
                continue

            offset_start = random.randint(0, 5)
            nights = random.randint(2, 5)
            if offset_start + nights > 7:
                nights = 7 - offset_start
            if nights < 2:
                continue

            check_in = WEEK_START + timedelta(days=offset_start)
            check_out = check_in + timedelta(days=nights)
            ch = random.choice(channels)
            guest = next_guest()
            price = prop.price_per_night or Decimal("150.00")
            total_price = price * Decimal(str(nights))
            cleaning = Decimal("50.00") if random.random() > 0.3 else Decimal("75.00")
            deposit = total_price * Decimal("0.15")
            guest_count = random.randint(1, prop.guest or 4)

            bk = Booking.objects.create(
                property=prop,
                channel=ch,
                first_name=guest["first_name"],
                last_name=guest["last_name"],
                email=guest["email"],
                country_code=guest["country_code"],
                phone=guest["phone"],
                check_in_date=check_in,
                check_out_date=check_out,
                guest_count=guest_count,
                status="confirmed",
                price_per_night=price,
                cleaning_fee=cleaning,
                application_fee=Decimal("0.00"),
                deposit_fee=deposit,
                price=total_price + cleaning + deposit,
                notes=random.choice([
                    "Guest requested extra pillows. Allergic to feathers.",
                    "Late check-in after 10 PM. Keys left in lockbox.",
                    "Celebrating honeymoon. Please prepare champagne.",
                    "Business traveler, needs quiet workspace.",
                    "Guest has a rental car. Reserve parking spot.",
                    "",
                    "",
                ]),
            )

            for i, pt in enumerate(["Payment 1", "Cleaning Fee", "Refundable deposit"]):
                amt = price * Decimal("0.5") if i == 0 else (cleaning if i == 1 else deposit)
                pay_date = check_in - timedelta(days=7) if i == 0 else (check_in if i == 1 else check_in)
                Payment.objects.create(
                    booking=bk,
                    type=pt,
                    amount=amt,
                    expected_payment_date=pay_date,
                    payment_date=pay_date if i < 2 else None,
                    is_paid=i < 2,
                    notes="" if i < 2 else "Pending refund after checkout inspection",
                )

            created_count += 1
            self.stdout.write(f"  Booking: {guest['first_name']} {guest['last_name']} @ {prop.title} ({check_in} to {check_out})")

        self.stdout.write(f"\n  Created {created_count} new bookings")

        today = date(2026, 6, 17)

        existing_task_dates = set(Task.objects.filter(date__gte=WEEK_START, date__lte=WEEK_END).values_list("date", "property_id"))
        task_count = 0
        for prop in properties:
            for day_offset in range(7):
                d = WEEK_START + timedelta(days=day_offset)
                if (d, prop.id) in existing_task_dates:
                    continue

                should_create = False
                if d == today or d == today + timedelta(days=1):
                    should_create = True
                elif d >= today and random.random() < 0.3:
                    should_create = True
                elif d < today and random.random() < 0.15:
                    should_create = True

                if not should_create:
                    continue

                task_type = random.choice(["cleaning", "cleaning", "maintenance", "payment", "other"])
                desc_list = TASK_DESCRIPTIONS.get(task_type, TASK_DESCRIPTIONS["other"])
                details = random.choice(desc_list)
                assigned = random.choice(ASSIGNED_STAFF) if random.random() > 0.3 else ""
                time_choices = [None, None, None, None, "09:00", "10:00", "11:00", "14:00", "15:00", "16:00"]
                chosen_time = random.choice(time_choices)
                t = None
                if chosen_time:
                    t = (timezone.datetime.strptime(chosen_time, "%H:%M").time())

                Task.objects.create(
                    property=prop,
                    created_by=host,
                    task_type=task_type,
                    details=details,
                    date=d,
                    time=t,
                    assigned_to=assigned,
                    repeat="None",
                    completed=d < today,
                )
                task_count += 1

        self.stdout.write(f"  Created {task_count} new tasks")

        existing_enquiry_props = set(
            Enquiry.objects.filter(check_in_date__gte=WEEK_START, check_in_date__lte=WEEK_END)
            .values_list("property_id", flat=True)
        )
        enquiry_count = 0
        for prop in properties:
            if prop.id in existing_enquiry_props:
                continue

            offset_start = random.randint(0, 5)
            nights = random.randint(1, 5)
            ci = WEEK_START + timedelta(days=offset_start)
            co = ci + timedelta(days=nights)
            if co > WEEK_END + timedelta(days=2):
                co = WEEK_END + timedelta(days=2)

            guest = next_guest()
            note = random.choice(ENQUIRY_NOTES)

            Enquiry.objects.create(
                property=prop,
                first_name=guest["first_name"],
                last_name=guest["last_name"],
                email=guest["email"],
                country_code=guest["country_code"],
                phone=guest["phone"],
                check_in_date=ci,
                check_out_date=co,
                adults=random.randint(1, 3),
                children=random.randint(0, 2),
                notes_for_host=note,
                is_archive=False,
                is_booked=False,
            )
            enquiry_count += 1

        self.stdout.write(f"  Created {enquiry_count} new enquiries")

        self.stdout.write(self.style.SUCCESS(
            f"\nDone! Total this week: {Booking.objects.filter(check_in_date__gte=WEEK_START, check_in_date__lte=WEEK_END).count()} bookings, "
            f"{Task.objects.filter(date__gte=WEEK_START, date__lte=WEEK_END).count()} tasks, "
            f"{Enquiry.objects.filter(check_in_date__gte=WEEK_START, check_in_date__lte=WEEK_END).count()} enquiries"
        ))

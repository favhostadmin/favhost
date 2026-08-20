"""Registry of every editable piece of the public ``/home`` landing page.

Why a registry rather than one model field per piece of copy: the page has
dozens of small texts and images, and a plain Django model field per string
would mean a migration every time a field is added or reworded. Instead each
entry here is just data — key, section, label, input type, and the built-in
default (the exact copy that ships in ``frontend/website/home.html``). A row
in ``SeoContentBlock`` only appears once someone overrides a key, so an
untouched page renders byte-for-byte the same as the static original.

This mirrors ``controlpanel.permissions.SECTIONS``: one file is the whole
source of truth, so adding a new editable field never touches a model, a
migration, or four different views.
"""
from django.templatetags.static import static as _static

SEO_SECTIONS = [
    ('meta', 'SEO & Meta Tags'),
    ('hero', 'Hero Banner'),
    ('features', 'Features'),
    ('how', 'How It Works'),
    ('pricing', 'Pricing'),
    ('about', 'About Us'),
    ('testimonials', 'Testimonials'),
    ('faq', 'FAQ'),
    ('footer', 'Footer'),
]

TEXT = 'text'
TEXTAREA = 'textarea'
IMAGE = 'image'

SEO_FIELDS = [
    # ── Meta tags ──────────────────────────────────────────────────────
    dict(key='meta.title', section='meta', label='Page title', type=TEXT,
         default='Vacation Rental Software & Channel Manager | Favhost'),
    dict(key='meta.description', section='meta', label='Meta description', type=TEXTAREA,
         default='Favhost is vacation rental software that syncs your calendars, automates guest messages, '
                  'and manages bookings across Airbnb, Vrbo, and Booking.com. Start free.'),
    dict(key='meta.canonical', section='meta', label='Canonical URL', type=TEXT,
         default='https://www.favhost.com/home'),
    dict(key='meta.schema_json', section='meta', label='Extra schema markup (JSON-LD, optional)', type=TEXTAREA,
         default=''),
    dict(key='meta.robots_txt', section='meta', label='robots.txt (site-wide — applies to the whole domain, not just /home)', type=TEXTAREA,
         default='User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /api/\nDisallow: /*?utm_\n\n'
                  'Sitemap: https://www.favhost.com/sitemap.xml'),

    # ── Hero banner ────────────────────────────────────────────────────
    dict(key='hero.title', section='hero', label='Hero title (H1)', type=TEXT,
         default='One Platform to manage Short-term vacation rentals, Hotel and Mid term rental business'),
    dict(key='hero.description', section='hero', label='Hero description', type=TEXTAREA,
         default='Build for Vacation Rentals | Hostel | B&Bs | Hotels - All in one Channel manager, PMS, '
                  'Booking engine, Direct booking website, Reservations, Accounting, Tasks and Housekeeping.'),
    dict(key='hero.cta_label', section='hero', label='CTA button text', type=TEXT,
         default='Get started for free'),
    dict(key='hero.image_1', section='hero', label='Hero image 1', type=IMAGE,
         default='website/img/herobanner.jpg'),
    dict(key='hero.image_1_alt', section='hero', label='Hero image 1 — alt text', type=TEXT,
         default='Vacation rental property managed with Favhost short-term rental software'),
    dict(key='hero.image_2', section='hero', label='Hero image 2', type=IMAGE,
         default='website/img/herobanner1.jpg'),
    dict(key='hero.image_2_alt', section='hero', label='Hero image 2 — alt text', type=TEXT,
         default='Vacation rental property managed with Favhost short-term rental software'),
    dict(key='hero.image_3', section='hero', label='Hero image 3', type=IMAGE,
         default='website/img/herobanner2.jpg'),
    dict(key='hero.image_3_alt', section='hero', label='Hero image 3 — alt text', type=TEXT,
         default='Vacation rental property managed with Favhost short-term rental software'),

    # ── Features ───────────────────────────────────────────────────────
    dict(key='features.title', section='features', label='Section title (H2)', type=TEXT,
         default='Key Features of Our Channel Manager Application'),
    dict(key='features.subtitle', section='features', label='Section subtitle', type=TEXT,
         default='Everything you need to manage your property effortlessly'),
    dict(key='features.intro', section='features', label='Section intro', type=TEXTAREA,
         default='Boost direct revenue and streamline hotel operations with an all-in-one property management '
                  'tool.\n\nKey features include a real-time Channel Manager to sync rates and inventory across '
                  'OTAs instantly, preventing overbookings. Build your brand with a commission-free Direct '
                  'Booking Website featuring an integrated booking engine.\n\nSimplify daily property workflows '
                  'by choosing an application that allows you to seamlessly manage tasks and automate '
                  'housekeeping schedules.\n\nOptimize your hospitality business, increase occupancy, avoid '
                  'double bookings and improve guest satisfaction today.'),

    dict(key='feature_1.title', section='features', label='Feature 1 — title (H3)', type=TEXT, default='Channel Manager'),
    dict(key='feature_1.description', section='features', label='Feature 1 — description', type=TEXTAREA,
         default='Our integrated Channel Manager acts as your central command center, synchronizing your '
                  'availability and rates across multiple OTAs like Airbnb, Vrbo, Booking.com.\n\nZero '
                  'Double-Bookings: Instant two-way synchronization means that when a guest books on one '
                  'platform, your calendar closes on all others automatically.\n\nBoosted Visibility: Easily '
                  'list on more channels without increasing your workload, so you reach more guests and '
                  'maximize occupancy effortlessly.'),
    dict(key='feature_1.image', section='features', label='Feature 1 — image', type=IMAGE,
         default='website/img/service-2.jpg'),
    dict(key='feature_1.image_alt', section='features', label='Feature 1 — image alt text', type=TEXT,
         default='Favhost channel manager syncing vacation rental bookings'),

    dict(key='feature_2.title', section='features', label='Feature 2 — title (H3)', type=TEXT, default='Reservations'),
    dict(key='feature_2.description', section='features', label='Feature 2 — description', type=TEXTAREA,
         default='Manage stress-free the short-term rental repetitive tasks for maintenance and cleaning. Track '
                  'cleaning schedules and STR maintenance in a single consolidated calendar.\n\nInstantly '
                  'confirm new bookings, send automated guest communications, and view upcoming check-ins and '
                  'check-outs at a glance.\n\nAssign tasks to your team, set reminders, and keep every '
                  'reservation running smoothly from booking to checkout.'),
    dict(key='feature_2.image', section='features', label='Feature 2 — image', type=IMAGE,
         default='website/img/service-5.jpg'),
    dict(key='feature_2.image_alt', section='features', label='Feature 2 — image alt text', type=TEXT,
         default='Favhost vacation rental reservation management'),

    dict(key='feature_3.title', section='features', label='Feature 3 — title (H3)', type=TEXT,
         default='Direct booking website'),
    dict(key='feature_3.description', section='features', label='Feature 3 — description', type=TEXTAREA,
         default='Favhost is designed specifically for short-term rental owners who want to maximize their ROI '
                  'and own their guest relationships directly.\n\nCommission-Free Bookings: Keep 100% of your '
                  'nightly rate. No more host fees or guest service fees eating into your margins.\n\nLive '
                  'Availability Sync: Your direct booking site is integrated directly with your channel '
                  'calendar, so you never have to worry about manual updates or double bookings.'),
    dict(key='feature_3.image', section='features', label='Feature 3 — image', type=IMAGE,
         default='website/img/service-3.jpg'),
    dict(key='feature_3.image_alt', section='features', label='Feature 3 — image alt text', type=TEXT,
         default='Favhost direct booking website for vacation rental hosts'),

    dict(key='feature_4.title', section='features', label='Feature 4 — title (H3)', type=TEXT, default='Accounting'),
    dict(key='feature_4.description', section='features', label='Feature 4 — description', type=TEXTAREA,
         default='Maximize your short-term rental ROI with our Channel Manager’s advanced accounting and '
                  'revenue report features. Seamlessly track rental income, expenses, and net profits across '
                  'all booking platforms in one centralized report.\n\nOur intelligent property management '
                  'software automates data syncing to deliver real-time metrics, including occupancy rates, '
                  'ADR (Average Daily Rate), and RevPAR (Revenue Per Available Room).\n\nOptimize your pricing '
                  'strategy, streamline vacation rental accounting, and scale your hospitality business '
                  'efficiently.'),
    dict(key='feature_4.image', section='features', label='Feature 4 — image', type=IMAGE,
         default='website/img/service-4.jpg'),
    dict(key='feature_4.image_alt', section='features', label='Feature 4 — image alt text', type=TEXT,
         default='Favhost listings and reservations management'),

    dict(key='feature_5.title', section='features', label='Feature 5 — title (H3)', type=TEXT, default='Manage Tasks'),
    dict(key='feature_5.description', section='features', label='Feature 5 — description', type=TEXTAREA,
         default='Our integrated task management suite automates your team\'s workflow from the moment a '
                  'booking is confirmed, giving you a real-time view of every job status across all your '
                  'properties.\n\nExpense & Receipt Tracking: Snap a photo of a maintenance receipt or log a '
                  'utility bill on the go. Categorize expenses by property to see exactly where your capital is '
                  'going.\n\nROI & Performance Analytics: Track key metrics like revenue for each listing, '
                  'expenses, and net profit to make smarter decisions and grow your business.'),
    dict(key='feature_5.image', section='features', label='Feature 5 — image', type=IMAGE,
         default='website/img/service-6.jpg'),
    dict(key='feature_5.image_alt', section='features', label='Feature 5 — image alt text', type=TEXT,
         default='Favhost task management for vacation rental hosts'),

    dict(key='feature_6.title', section='features', label='Feature 6 — title (H3)', type=TEXT, default='Housekeeping'),
    dict(key='feature_6.description', section='features', label='Feature 6 — description', type=TEXTAREA,
         default='Transform your property\'s turnaround efficiency with real-time housekeeping updates '
                  'instantly synced to your listings across all booking channels.\n\nEnsure every room meets '
                  'your highest standards before arrival, driving seamless check-ins and five-star reviews. '
                  'Assign cleans automatically after each checkout and track completion in real time.\n\n'
                  'Maximize staff productivity and elevate the guest experience with a fully integrated '
                  'housekeeping management solution built for short-term rental hosts.'),
    dict(key='feature_6.image', section='features', label='Feature 6 — image', type=IMAGE,
         default='website/img/service-1.jpg'),
    dict(key='feature_6.image_alt', section='features', label='Feature 6 — image alt text', type=TEXT,
         default='Favhost housekeeping automation for short-term rentals'),

    # ── How it works ───────────────────────────────────────────────────
    dict(key='how.title', section='how', label='Section title (H2)', type=TEXT, default='How it works'),
    dict(key='how_1.title', section='how', label='Step 1 — title (H3)', type=TEXT, default='Property Management'),
    dict(key='how_1.description', section='how', label='Step 1 — description', type=TEXTAREA,
         default='Optimize your property management with Favhost, the ultimate hospitality software for '
                  'real-time channel management for the short-term rental business.'),
    dict(key='how_2.title', section='how', label='Step 2 — title (H3)', type=TEXT, default='Multi-Channel Sync'),
    dict(key='how_2.description', section='how', label='Step 2 — description', type=TEXTAREA,
         default='Our cloud-based channel manager syncs your rates and availability across Booking.com, '
                  'Expedia, Airbnb and many more instantly.'),
    dict(key='how_3.title', section='how', label='Step 3 — title (H3)', type=TEXT, default='Boost Revenue'),
    dict(key='how_3.description', section='how', label='Step 3 — description', type=TEXTAREA,
         default='Eliminate double bookings, maximize profits and occupancies, streamline operations and '
                  'boost your short-term rental and homestay business revenue effortlessly.'),
    dict(key='how.video_url', section='how', label='Demo video (YouTube embed URL)', type=TEXT,
         default='https://www.youtube.com/embed/TW3RT8z5x88'),

    # ── Pricing ────────────────────────────────────────────────────────
    dict(key='pricing.title', section='pricing', label='Pricing title', type=TEXTAREA,
         default='Pricing\nUnlimited listings,\nSimplified pricing'),
    dict(key='pricing.image', section='pricing', label='Pricing image', type=IMAGE,
         default='website/img/about-3.jpg'),
    dict(key='pricing.image_alt', section='pricing', label='Pricing image — alt text', type=TEXT,
         default='Favhost vacation rental software pricing'),

    # ── About us ───────────────────────────────────────────────────────
    dict(key='about.title', section='about', label='Section title (H2)', type=TEXT, default='About us and our Team'),
    dict(key='about.intro', section='about', label='Intro paragraph', type=TEXTAREA,
         default='Favhost was born from a simple observation: the hospitality industry is moving faster than '
                  'ever, but the tools shouldn\'t make your life harder.'),
    dict(key='about.body', section='about', label='Body text', type=TEXTAREA,
         default='We are a team of developers, former hoteliers, and tech enthusiasts dedicated to building '
                  'the most intuitive channel manager web application and the OTA management tool on the '
                  'market.\n\nThere are plenty of vacation rental management tools out there. But we aren\'t '
                  'just a piece of software; we\'re your partner in growth. Our Vacation rental management '
                  'tool prioritize reliability, simplicity, Booking automation to increase occupancy.'),
    dict(key='about.team_body', section='about', label='"Our team" accordion text', type=TEXTAREA,
         default='We met hosts and BNB owners across the globe analyze their requirements and problems and '
                  'decided to build a simplified easy to use affordable platform for Short-term rental '
                  'industry.\n\nFrom our engineering labs to our customer success desk, we are focused on one '
                  'goal: Simple solution to maximize your rental revenue.\n\nOur platform build for speed and '
                  'security for real-time API integrations, 99.9% uptime, and a "mobile-friendly" user '
                  'experience to keep your business running 24/7.\n\nOur support team don\'t just solve '
                  'technical tickets; we provide strategic advice to help you navigate the complexities of the '
                  'STR market.'),
    dict(key='about.image', section='about', label='About image', type=IMAGE,
         default='website/img/aboutt4.jpg'),
    dict(key='about.image_alt', section='about', label='About image — alt text', type=TEXT,
         default='Favhost team managing short-term rental properties'),

    # ── Testimonials ───────────────────────────────────────────────────
    dict(key='testimonials.title', section='testimonials', label='Section title (H2)', type=TEXT,
         default='What People Say About us'),
    dict(key='testimonials.rating', section='testimonials', label='Overview rating', type=TEXT, default='4.9'),
    dict(key='testimonials.overview_quote', section='testimonials', label='Overview quote', type=TEXTAREA,
         default='"After moving 20+ listings over from spreadsheets, the two-way API sync is incredibly '
                  'stable; Solid platform with a great feature set, especially the direct booking engine."'),

    dict(key='testimonial_1.name', section='testimonials', label='Testimonial 1 — name', type=TEXT, default='Manish'),
    dict(key='testimonial_1.quote', section='testimonials', label='Testimonial 1 — quote', type=TEXTAREA,
         default='Running 14 properties used to feel impossible until I found FavHost. This Airbnb channel '
                  'manager software syncs my calendars in real time, so double bookings are a thing of the '
                  'past.\n\nThe built-in task management tools keep my cleaning team on schedule, and my new '
                  'direct booking website gives me a serious edge over competitors. For the price, it\'s the '
                  'most affordable vacation rental management software I\'ve tested, and my profit margins '
                  'have grown nearly 25% since signing up last year.'),
    dict(key='testimonial_1.image', section='testimonials', label='Testimonial 1 — photo', type=IMAGE,
         default='website/img/img3.jpg'),

    dict(key='testimonial_2.name', section='testimonials', label='Testimonial 2 — name', type=TEXT,
         default='Denzel and Emma'),
    dict(key='testimonial_2.quote', section='testimonials', label='Testimonial 2 — quote', type=TEXTAREA,
         default='FavHost is hands down the best property management software I\'ve used for my Airbnb '
                  'business. This channel manager syncs all my listings instantly, completely eliminating '
                  'double bookings during peak season.\n\nI love how the platform handles task automation for '
                  'turnovers, and the direct booking site has already paid for itself twice over. For such an '
                  'affordable monthly cost, my revenue has climbed steadily and my STR profitability is '
                  'finally where I always wanted it to be.'),
    dict(key='testimonial_2.image', section='testimonials', label='Testimonial 2 — photo', type=IMAGE,
         default='website/img/img4.jpg'),

    dict(key='testimonial_3.name', section='testimonials', label='Testimonial 3 — name', type=TEXT, default='Yiran'),
    dict(key='testimonial_3.quote', section='testimonials', label='Testimonial 3 — quote', type=TEXTAREA,
         default='I evaluated five short term rental software platforms before choosing FavHost, and the '
                  'difference is night and day. The OTA sync is instant, the dashboard is genuinely easy to '
                  'use, and the automated checkin and checkout instructions saves me hours every week.\n\nThe '
                  'built-in direct booking website helped me cut Airbnb fees, boosting profitability fast. As '
                  'a vacation rental channel manager, it\'s the best value on the market, and my revenue '
                  'growth has been steady every single month since I onboarded.'),
    dict(key='testimonial_3.image', section='testimonials', label='Testimonial 3 — photo', type=IMAGE,
         default='website/img/img5.jpg'),

    dict(key='testimonial_4.name', section='testimonials', label='Testimonial 4 — name', type=TEXT, default='Madison'),
    dict(key='testimonial_4.quote', section='testimonials', label='Testimonial 4 — quote', type=TEXTAREA,
         default='FavHost has completely transformed how I run my short term rental business. The OTA sync is '
                  'seamless across Airbnb, Vrbo, and Booking.com, and I haven\'t had a single double booking '
                  'since I switched.\n\nAs a vacation rental channel manager, it\'s incredibly easy to use, '
                  'and the direct booking website it built for me has already brought in commission-free '
                  'reservations. My revenue is up 32% this quarter and the affordable pricing makes it a '
                  'no-brainer for any STR host serious about profitability.'),
    dict(key='testimonial_4.image', section='testimonials', label='Testimonial 4 — photo', type=IMAGE,
         default='website/img/img6.jpg'),

    # ── FAQ ────────────────────────────────────────────────────────────
    dict(key='faq.title', section='faq', label='Section title (H2)', type=TEXT, default='Frequently asked questions'),
    dict(key='faq.subtitle', section='faq', label='Section subtitle', type=TEXTAREA,
         default='Everything you need to know about Favhost - from connecting your first OTA to running a '
                  'commission-free direct booking site.'),

    dict(key='faq_1.question', section='faq', label='Q1', type=TEXT,
         default='What is Favhost and how does it work?'),
    dict(key='faq_1.answer', section='faq', label='A1', type=TEXTAREA,
         default='Favhost is a cloud-based channel manager built for short-term rental hosts and property '
                  'managers. It synchronizes your availability, rates, and reservations in real time across '
                  'multiple OTAs such as Airbnb, Vrbo, and Booking.com from a single dashboard.\n\nThat means '
                  'no more juggling separate calendars, no more double bookings, and no more late-night manual '
                  'rate updates - one change in Favhost updates every channel within seconds.'),

    dict(key='faq_2.question', section='faq', label='Q2', type=TEXT,
         default='Which booking channels and OTAs does Favhost integrate with?'),
    dict(key='faq_2.answer', section='faq', label='A2', type=TEXTAREA,
         default='Favhost connects with every major short-term rental platform, including Airbnb, Vrbo, '
                  'Booking.com, Expedia, Agoda, Hotels.com, Tripadvisor, plus direct booking engines and '
                  'several regional OTAs.\n\nNew channel integrations are added regularly based on customer '
                  'demand - if a channel you use isn\'t yet supported, let us know.'),

    dict(key='faq_3.question', section='faq', label='Q3', type=TEXT, default='Is there any direct booking website?'),
    dict(key='faq_3.answer', section='faq', label='A3', type=TEXTAREA,
         default='Yes. Every Favhost account includes a built-in, branded direct booking website where guests '
                  'can browse your listings, check live availability, and reserve commission-free.\n\nThe site '
                  'automatically stays in sync with every connected OTA channel - so a booking on your direct '
                  'site instantly blocks the dates everywhere else.'),

    dict(key='faq_4.question', section='faq', label='Q4', type=TEXT, default='How does Favhost pricing work?'),
    dict(key='faq_4.answer', section='faq', label='A4', type=TEXTAREA,
         default='Favhost uses simple flat monthly pricing, with automatic volume discounts as your portfolio '
                  'grows. There are no commission fees on bookings, no setup costs, and no long-term '
                  'contracts.\n\nYou can upgrade, downgrade, or cancel at any time.'),

    dict(key='faq_5.question', section='faq', label='Q5', type=TEXT,
         default='Do I need credit card info for the free trial?'),
    dict(key='faq_5.answer', section='faq', label='A5', type=TEXTAREA,
         default='No - the Favhost free trial requires no credit card. You can sign up with just an email '
                  'address, connect your channels, and explore every feature with zero risk.\n\nYou only enter '
                  'payment details if and when you choose to continue past the trial period.'),

    dict(key='faq_6.question', section='faq', label='Q6', type=TEXT, default='How do I cancel my subscription?'),
    dict(key='faq_6.answer', section='faq', label='A6', type=TEXTAREA,
         default='You can cancel anytime directly from your profile - no phone calls or retention scripts. '
                  'Your account stays active until the end of your current billing cycle.'),

    dict(key='faq_7.question', section='faq', label='Q7', type=TEXT,
         default='What kind of reports and analytics are included?'),
    dict(key='faq_7.answer', section='faq', label='A7', type=TEXTAREA,
         default='Every plan includes a real-time analytics dashboard covering occupancy, ADR, RevPAR, channel '
                  'mix, booking pace, and revenue by listing.'),

    dict(key='faq_8.question', section='faq', label='Q8', type=TEXT,
         default='What kind of customer support does Favhost offer?'),
    dict(key='faq_8.answer', section='faq', label='A8', type=TEXTAREA,
         default='All paid plans include 24/7 live chat and email support.'),

    # ── Footer ─────────────────────────────────────────────────────────
    dict(key='footer.about_text', section='footer', label='About blurb', type=TEXTAREA,
         default='Centralizes property management by synchronizing availability, reservations across '
                  'multiple channels like Airbnb and Vrbo via real-time integrations.'),
]

SEO_FIELDS_BY_KEY = {f['key']: f for f in SEO_FIELDS}


def resolve_seo_context(preview=None):
    """Build the two nested dicts the /home template reads: text and images.

    Each is keyed ``{section: {field: value}}`` (split from ``"section.field"``)
    so the template can do plain dotted lookups like ``{{ seo.hero.title }}``
    with no custom template tags. A key with no ``SeoContentBlock`` row (the
    common case — most fields are never touched) resolves to its built-in
    default, so the page is byte-for-byte the shipped copy until a co-admin
    changes something.

    ``preview`` — an optional ``{key: value}`` dict of *unsaved* edits (text,
    or a pre-resolved image URL) — wins over both the saved override and the
    default. This is how the "Preview changes" button on ``/console/seo/``
    shows a co-admin their draft without writing anything to the database:
    the values are stashed in their session, never in ``SeoContentBlock``.
    """
    from .models import SeoContentBlock

    preview = preview or {}
    overrides = {b.key: b for b in SeoContentBlock.objects.all()}
    text, images = {}, {}
    for f in SEO_FIELDS:
        section, field = f['key'].split('.', 1)
        block = overrides.get(f['key'])
        draft = preview.get(f['key'])
        if f['type'] == IMAGE:
            images.setdefault(section, {})
            if draft:
                images[section][field] = draft
            else:
                images[section][field] = block.image.url if (block and block.image) else _static(f['default'])
        else:
            text.setdefault(section, {})
            if draft is not None:
                value = draft
            else:
                value = block.text_value if (block and block.text_value) else f['default']
            text[section][field] = value
    return text, images

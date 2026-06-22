
#!/usr/bin/env python
"""Generate a professional PDF report documenting all data flows."""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bookaid.settings")

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether,
)

HEADER_BG = HexColor("#1e293b")
SECTION_BG = HexColor("#f1f5f9")
ACCENT = HexColor("#3b82f6")
ROW_ALT = HexColor("#f8fafc")
BORDER = HexColor("#cbd5e1")
GREEN = HexColor("#10b981")
RED = HexColor("#ef4444")
AMBER = HexColor("#f59e0b")
DARK_TEXT = HexColor("#1e293b")
BODY_TEXT = HexColor("#334155")
MUTED = HexColor("#64748b")

styles = getSampleStyleSheet()

title_style = ParagraphStyle("DocTitle", parent=styles["Title"],
    fontSize=28, leading=34, textColor=white, spaceAfter=4, alignment=TA_CENTER)
subtitle_style = ParagraphStyle("DocSubtitle", parent=styles["Normal"],
    fontSize=13, leading=17, textColor=HexColor("#94a3b8"), alignment=TA_CENTER, spaceAfter=6)
h1 = ParagraphStyle("H1", parent=styles["Heading1"],
    fontSize=20, leading=26, textColor=HEADER_BG, spaceBefore=20, spaceAfter=10, borderPadding=(0, 0, 4, 0))
h2 = ParagraphStyle("H2", parent=styles["Heading2"],
    fontSize=15, leading=19, textColor=ACCENT, spaceBefore=14, spaceAfter=6)
h3 = ParagraphStyle("H3", parent=styles["Heading3"],
    fontSize=12, leading=15, textColor=HEADER_BG, spaceBefore=10, spaceAfter=4)
body = ParagraphStyle("Body", parent=styles["Normal"],
    fontSize=9.5, leading=13.5, textColor=BODY_TEXT, spaceAfter=6, alignment=TA_JUSTIFY)
code_style = ParagraphStyle("Code", parent=styles["Code"],
    fontSize=7.5, leading=10, textColor=HEADER_BG, backColor=SECTION_BG, borderPadding=6, spaceAfter=8)
table_header = ParagraphStyle("TH", parent=styles["Normal"],
    fontSize=8.5, leading=11, textColor=white, alignment=TA_LEFT)
table_cell = ParagraphStyle("TC", parent=styles["Normal"],
    fontSize=8, leading=11, textColor=BODY_TEXT)
table_cell_bold = ParagraphStyle("TCB", parent=table_cell, textColor=DARK_TEXT)
note_style = ParagraphStyle("Note", parent=body,
    fontSize=9, leading=12, textColor=RED, backColor=HexColor("#fef2f2"), borderPadding=6, spaceAfter=8)
toc_style = ParagraphStyle("TOC", parent=body,
    fontSize=11, leading=18, leftIndent=10, spaceBefore=2, spaceAfter=2, textColor=DARK_TEXT)
cover_line = ParagraphStyle("CL", parent=subtitle_style,
    fontSize=10, textColor=MUTED)


def hr():
    return HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=8, spaceBefore=4)


def section_box(title, items, col_widths=None):
    if col_widths is None:
        col_widths = [110, 370]
    rows = [
        [Paragraph(f"<b>{title}</b>", ParagraphStyle("sb", parent=table_cell,
          fontSize=9, textColor=HEADER_BG),)],
    ]
    for label, val in items:
        rows.append([
            Paragraph(f"<b>{label}</b>", ParagraphStyle("sl", parent=table_cell,
              fontSize=8, textColor=MUTED)),
            Paragraph(val, table_cell),
        ])
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SECTION_BG),
        ("SPAN", (0, 0), (-1, 0)),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 1), (-1, -1), 0.3, HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def data_table(headers, rows, col_widths=None):
    hdr = [Paragraph(h, table_header) for h in headers]
    data = [hdr]
    for row in rows:
        data.append([Paragraph(str(c), table_cell) for c in row])
    avail = 480
    if col_widths is None:

        col_widths = [avail // len(headers)] * len(headers)
    else:
        total = sum(col_widths)
        if total != avail:
            col_widths = [int(w * avail / total) for w in col_widths]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    t.setStyle(TableStyle(cmds))
    return t


def note(text):
    return Paragraph(f"<b>[Note]</b> {text}", note_style)


def code(text):
    return Paragraph(text.replace("\n", "<br/>"), code_style)


OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_flow_report.pdf")

doc = SimpleDocTemplate(
    OUTPUT, pagesize=A4,
    topMargin=20*mm, bottomMargin=18*mm,
    leftMargin=18*mm, rightMargin=18*mm,
    title="FavHost - Data Flow Report",
)

story = []

# Cover
story.append(Spacer(1, 100))
cover_t = Table(
    [[Paragraph("FavHost", ParagraphStyle("c1", parent=title_style, fontSize=42, leading=48))],
     [Paragraph("Data Flow &amp; Architecture Report", ParagraphStyle("c2", parent=subtitle_style, fontSize=18, leading=22, textColor=HexColor("#cbd5e1")))],
     [Spacer(1, 20)],
     [Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')}", cover_line)],
     [Paragraph("Covers: Calendar, Booking Details, Tasks, Listing &amp; Registration pages", cover_line)]],
    colWidths=[460])
cover_t.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), HEADER_BG),
    ("TOPPADDING", (0, 0), (-1, -1), 50),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 50),
    ("LEFTPADDING", (0, 0), (-1, -1), 30),
    ("RIGHTPADDING", (0, 0), (-1, -1), 30),
    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("ROUNDEDCORNERS", [8, 8, 8, 8]),
]))
story.append(cover_t)
story.append(PageBreak())

# TOC
story.append(Paragraph("Table of Contents", h1))
story.append(hr())
toc_items = [
    "1. Role System Overview",
    "2. Visibility Engine - get_visible_user_ids() & get_effective_user()",
    "3. Calendar Page (calender.html) - Data Flow",
    "4. Booking Details Page (payment_details.html) - Data Flow",
    "5. Task Pages - Data Flow",
    "6. Listing Page - Data Flow",
    "7. Registration Page - Data Flow",
    "8. Cross-Page Data Alignment Analysis",
    "9. Role-Based Data Differences Per Page",
    "10. Summary",
]
for item in toc_items:
    story.append(Paragraph(item, toc_style))
story.append(PageBreak())

story.append(Paragraph("1. Role System Overview", h1))
story.append(hr())
story.append(data_table(
    ["Role", "Description", "Key Characteristics"],
    [
        ["Host", "Property owner. Creates listings, owns all data.", "Full profile; creates properties; owns bookings, tasks, enquiries."],
        ["Co-host", "Granted access by a host via CoHost model.", "No profile page; creations attributed to host via get_effective_user(); can manage host's data."],
        ["Admin", "Django superuser / staff.", "Only relevant for Django admin panel; not used in frontend views."],
    ],
    [90, 190, 200],
))
story.append(Spacer(1, 6))
story.append(note("Co-hosts are blocked from Profile and Edit Profile pages (accounts/views.py:566, 734)."))

story.append(Paragraph("2. Visibility Engine", h1))
story.append(hr())

story.append(Paragraph("2.1 get_visible_user_ids(user)", h2))
story.append(Paragraph(
    "Core function in <b>accounts/utils.py:4</b>. Returns a list of user IDs whose data the given user can access.", body))
story.append(Spacer(1, 4))
story.append(data_table(
    ["Source", "Logic", "Who is included"],
    [
        ["1. Self", "Always", "The user's own ID"],
        ["2. Hosts who added me", "CoHost.objects.filter(co_host=user)", "Hosts who added this user as a co-host"],
        ["3. Co-hosts I added", "CoHost.objects.filter(host=user)", "Co-hosts this user added as a host"],
    ],
    [120, 180, 180],
))

story.append(Spacer(1, 8))
story.append(Paragraph("2.2 get_effective_user(user)", h2))
story.append(Paragraph(
    "Returns the <b>host</b> if the current user is a co-host, otherwise returns the user themselves. "
    "All data creation (properties, tasks, etc.) is attributed to this effective user.", body))
code_text = """def get_effective_user(user):<br/>    host = CoHost.objects.filter(co_host=user).select_related('host').first()<br/>    if host:<br/>        return host.host<br/>    return user"""
story.append(code(code_text))

story.append(Spacer(1, 6))
story.append(Paragraph("2.3 Visibility Example", h2))
story.append(Paragraph(
    "Host <b>Alice</b> adds <b>Bob</b> as a co-host. "
    "Alice owns <b>Property P1</b> and has <b>10 bookings</b>, <b>5 tasks</b>. "
    "Bob creates <b>3 more tasks</b> on P1.", body))
story.append(Spacer(1, 4))
story.append(data_table(
    ["Query", "Bob's visible IDs", "What Bob sees"],
    [
        ["Property.objects.filter(created_by__in=...)", "{Bob, Alice}", "P1 (Alice's) + any of Bob's own properties"],
        ["Booking.objects.filter(property__created_by__in=...)", "{Bob, Alice}", "Alice's 10 bookings"],
        ["Task.objects.filter(created_by__in=...) [Pattern B]", "{Bob, Alice}", "3 tasks Bob created (NOT Alice's 5)"],
        ["Task.objects.filter(property__created_by__in=...) [Pattern A]", "{Bob, Alice}", "All 8 tasks (Alice's 5 + Bob's 3)"],
    ],
    [160, 120, 200],
))
story.append(Spacer(1, 4))
story.append(note("Core misalignment: Pattern A (by property owner) vs Pattern B (by creator) give different results for co-hosts."))
story.append(PageBreak())

story.append(Paragraph("3. Calendar Page (calender.html)", h1))
story.append(hr())
story.append(section_box("Page Info", [
    ("URL", "/calendar-grid-view/"),
    ("View", "CalenderAPIView - bookaid/views.py:464"),
    ("Template", "templates/frontend/calender/calender.html"),
    ("Auth", "LoginRequiredMixin"),
    ("Data delivery", "Initial context (properties) + AJAX JSON (bookings, tasks, enquiries)"),
]))

story.append(Spacer(1, 4))
story.append(Paragraph("3.1 Initial Page Load - get_context_data()", h2))
story.append(data_table(
    ["Context Key", "Model / Source", "Filter", "Description"],
    [
        ["rooms_data", "Property", "created_by__in=get_visible_user_ids(), status='Active'", "List of property dicts for sidebar"],
        ["bookings_data", "None (empty list)", "Populated via AJAX", "Initial placeholder"],
    ],
    [100, 90, 150, 140],
))

story.append(Spacer(1, 6))
story.append(Paragraph("3.2 AJAX - get_bookings_data()", h2))
story.append(Paragraph(
    "Triggered with <b>x-requested-with: XMLHttpRequest</b>. Accepts <b>start_date</b> and <b>end_date</b> "
    "(YYYY-MM-DD). Returns JSON with 3 keys.", body))
story.append(Spacer(1, 4))
story.append(data_table(
    ["JSON Key", "Model", "Filter Details", "Key Fields Returned"],
    [
        ["bookings", "Booking",
         "property__created_by__in, date range, .exclude(status='cancelled'), select_related(property, channel), prefetch_related(images, payments)",
         "id, propertyId, start_date, end_date, guestName, guestAvatar, color, channelIcon, channelName, bookingId, paymentDates, paymentsInfo, totalPrice, totalPayment, firstInstallment"],
        ["blocked dates", "PropertyBlockDate",
         "property__created_by__in, date range, is_active=True",
         "id, propertyId, start_date, end_date, color, type, reason"],
        ["tasks", "Task",
         "property__created_by__in, date in range, completed=False, select_related(property)",
         "id, propertyId, date, time, task_type, details, assigned_to, phone, completed, repeat, repeat_till, color"],
        ["enquiries", "Enquiry",
         "property__created_by__in, date range, is_archive=False, select_related(property)",
         "id, propertyId, start_date, end_date, guestName, guestAvatar, color, phone, email, adults, children, pets, notes"],
    ],
    [65, 75, 175, 165],
))
story.append(PageBreak())

story.append(Paragraph("4. Booking Details Page (payment_details.html)", h1))
story.append(hr())
story.append(section_box("Page Info", [
    ("URL", "/booking/payment-details/&lt;uuid:pk&gt;/"),
    ("View", "payment_details() - booking/views.py:521"),
    ("Template", "frontend/booking/payment_details.html (full) or payment_details_partial.html (?partial=true)"),
    ("Auth", "@login_required"),
    ("Note", "There is NO template named booking_detail.html. The details page is called 'Payment Details'."),
]))

story.append(Spacer(1, 4))
story.append(Paragraph("4.1 Context Data", h2))
story.append(data_table(
    ["Context Key", "Model / Source", "Description"],
    [
        ["booking", "Booking (pk lookup, property__created_by__in filter)", "Full Booking model instance"],
        ["nights", "booking.total_nights", "Computed nights from check-in/out"],
        ["payment_schedule", "booking.payments.prefetch_related('attachments').all()", "List of dicts: id, name, amount, date, is_paid, notes, attachments"],
        ["subtotal", "booking.price_per_night * nights", "Base price"],
        ["total_price", "subtotal + fees (or monthly if nights &gt;= 30)", "Final price"],
        ["monthly_payment", "booking.price_per_night * 30 if nights &gt;= 30", "Monthly rate"],
        ["time_delta", "Checkout == today", "Boolean"],
        ["booking_status", "Computed: cancelled/past/current/upcoming", "Status label"],
    ],
    [110, 200, 170],
))

story.append(Spacer(1, 6))
story.append(Paragraph("4.2 AJAX Endpoints on this Page", h2))
story.append(data_table(
    ["Endpoint", "Method", "Purpose"],
    [
        ["/booking/ajax/update-payment-status/", "POST", "Toggle payment.is_paid"],
        ["/booking/ajax/add-payment-attachment/", "POST FormData", "Upload file to PaymentAttachment"],
        ["/booking/ajax/delete-payment-attachment/", "POST", "Delete a PaymentAttachment"],
        ["/booking/ajax/update-payment-notes/", "POST", "Save notes on a Payment"],
        ["/booking/ajax/delete-guest-image/", "POST", "Delete a GuestImage"],
        ["/booking/ajax/delete-guest-document/", "POST", "Delete a GuestDocument"],
        ["/booking/cancel/&lt;uuid:pk&gt;/", "POST", "Cancel booking"],
        ["/booking/render-email-form/", "GET", "Load email form modal"],
        ["/booking/send-guest-email/", "POST", "Send email to guest"],
        ["/booking/guest-receipt/&lt;uuid:pk&gt;/", "GET", "Load receipt modal"],
    ],
    [220, 70, 190],
))
story.append(PageBreak())

story.append(Paragraph("5. Task Pages", h1))
story.append(hr())

story.append(Paragraph("5.1 Task List Page", h2))
story.append(section_box("Page Info", [
    ("URL", "/tasks/list/"),
    ("View", "TaskListView - tasks/views.py:20"),
    ("Template", "templates/frontend/tasks/list.html"),
    ("Auth", "LoginRequiredMixin"),
]))

story.append(Spacer(1, 4))
story.append(data_table(
    ["Context Key", "Model / Source", "Filter", "Description"],
    [
        ["tasks", "Task",
         "created_by__in=get_visible_user_ids(), select_related('property'), status=pending|done|all, ?search= filter",
         "Paginated task list (10/page) with is_overdue, days_until_due"],
        ["all_tasks_count", "Task", "created_by__in same base", "Total count"],
        ["pending_tasks_count", "Task", "Same + completed=False", "Pending count"],
        ["done_tasks_count", "Task", "Same + completed=True", "Done count"],
        ["status_filter", "GET param", "Defaults to 'pending'", "Current tab"],
        ["search_query", "GET param", "Searches property__title, task_type, details, assigned_to", "Search term"],
    ],
    [100, 55, 180, 145],
))

story.append(Spacer(1, 6))
story.append(Paragraph("5.2 Task AJAX Endpoints", h2))
story.append(data_table(
    ["Endpoint", "Method", "Request Body", "Response"],
    [
        ["/tasks/update-status/&lt;pk&gt;/", "POST", '{"completed": true/false}', '{"success": bool, "pending_tasks_count": int, "done_tasks_count": int}'],
        ["/tasks/delete/&lt;pk&gt;/", "POST", '{"delete_mode": "single"|"all"}', '{"success": bool, "message": str, counts}'],
    ],
    [140, 50, 130, 160],
))

story.append(Spacer(1, 6))
story.append(Paragraph("5.3 Task Create / Edit", h2))
story.append(data_table(
    ["Action", "URL", "Template", "Models Used"],
    [
        ["Create", "/tasks/create/", "templates/frontend/tasks/create.html", "TaskForm, Property (active, visible for dropdown)"],
        ["Edit", "/tasks/edit/&lt;pk&gt;/", "Same template (is_edit=True)", "Task (pk lookup, created_by__in), Property"],
    ],
    [60, 100, 180, 140],
))
story.append(PageBreak())

story.append(Paragraph("6. Listing Page", h1))
story.append(hr())

story.append(Paragraph("6.1 Public Listing Grid", h2))
story.append(section_box("Page Info", [
    ("URL (public)", "/property/listing/&lt;short_code&gt;/"),
    ("URL (auth)", "/property/listing/"),
    ("View", "ListingPageView - property/views.py:728"),
    ("Template", "templates/frontend/public_host_website/listing.html"),
    ("Pagination", "6 per page"),
]))

story.append(Spacer(1, 4))
story.append(data_table(
    ["Context Key", "Model / Source", "Filter", "Description"],
    [
        ["properties", "Property",
         "short_code lookup (public) or created_by__in (auth), status='Active', optional check_in/check_out/guests filters",
         "Paginated property cards"],
        ["host", "MyUser", "short_code lookup or request.user", "Host profile info (avatar, social, about)"],
        ["check_in / check_out", "GET params", "None", "Date filter values"],
        ["guests_count", "GET param", "Defaults to '1'", "Guest filter"],
        ["num_nights", "Computed", "From check_in/check_out", "Night count"],
        ["paginator / page_obj", "Django ListView built-in", "None", "Pagination"],
    ],
    [100, 65, 190, 125],
))

story.append(Spacer(1, 6))
story.append(Paragraph("6.2 Listing Detail Page", h2))
story.append(section_box("Page Info", [
    ("URL", "/property/listing-details/&lt;short_code&gt;/&lt;slug&gt;/"),
    ("View", "ListingDetailView - property/views.py:818"),
    ("Template", "templates/frontend/public_host_website/listing_details.html"),
]))

story.append(Spacer(1, 4))
story.append(data_table(
    ["Context Key", "Model / Source", "Description"],
    [
        ["property", "Property (slug lookup)", "Full property instance"],
        ["host", "property.created_by (MyUser)", "Host info: phone, whatsapp, profile_picture"],
        ["images", "property.images.all() (PropertyImage)", "Gallery images"],
        ["amenities", "property.amenities.all().order_by('name')", "Amenities list"],
        ["short_code", "URL kwarg", "For links and sharing"],
    ],
    [100, 160, 220],
))
story.append(PageBreak())

story.append(Paragraph("7. Registration Page", h1))
story.append(hr())
story.append(section_box("Page Info", [
    ("URL", "/accounts/register/"),
    ("View", "register_view - accounts/views.py:269"),
    ("Template", "templates/frontend/auth/login.html (combined login + signup)"),
    ("Auth", "No auth required (public)"),
]))

story.append(Spacer(1, 4))
story.append(Paragraph("7.1 Flow", h2))
story.append(data_table(
    ["Step", "Action", "Data Store", "Context"],
    [
        ["1. GET", "Redirects to /accounts/login/", "None", "login.html with signup panel hidden"],
        ["2. POST form", "Validate: first_name, last_name, email, password1, password2", "Checks MyUser for duplicate email/username", "show_signup=True, signup_data={...}"],
        ["3. Valid POST", "Generate 4-digit OTP, store in session", "session['signup_otp'], session['signup_data']", "show_otp_modal=True, otp_email=..."],
        ["4. OTP entered", "POST to /accounts/verify-otp/", "Validate against session, create MyUser", "Redirect to dashboard"],
        ["5. Resend OTP", "POST to /accounts/resend-otp/", "Generate new OTP, update session", "Re-render with OTP modal"],
    ],
    [60, 130, 140, 150],
))

story.append(Spacer(1, 4))
story.append(Paragraph("7.2 Context Data (per step)", h2))
story.append(data_table(
    ["Context Key", "Source", "When Present"],
    [
        ["show_signup", "GET ?mode=signup or POST error", "Steps 2-3"],
        ["signup_data", "Submitted form values", "Steps 2-3 (repopulate form)"],
        ["show_otp_modal", "True after valid POST", "Step 3"],
        ["otp_email", "Submitted email", "Step 3 (display in modal)"],
        ["firebase_*", "Django settings", "Google sign-in config"],
        ["form", "Django LoginView default", "Login form (login panel)"],
    ],
    [100, 150, 230],
))
story.append(PageBreak())

story.append(Paragraph("8. Cross-Page Data Alignment Analysis", h1))
story.append(hr())

story.append(Paragraph("8.1 The Two Filter Patterns", h2))
story.append(data_table(
    ["Pattern", "Filter Field", "Used By"],
    [
        ["A - By property owner", "property__created_by__in=get_visible_user_ids()",
         "Calendar (bookings, tasks, enquiries), Dashboard (bookings, revenue, enquiries), Booking List, Booking Details, Listing Page"],
        ["B - By creator", "created_by__in=get_visible_user_ids()",
         "Task List page, Dashboard (task counts)"],
    ],
    [110, 180, 190],
))

story.append(Spacer(1, 8))
story.append(Paragraph("8.2 Identified Misalignments", h2))

story.append(Paragraph("Misalignment #1 - Task Filtering (Calendar vs Task List)", h3))
story.append(data_table(
    ["", "Calendar (get_bookings_data)", "Task List (TaskListView)"],
    [
        ["Filter field", "property__created_by__in=get_visible_user_ids()", "created_by__in=get_visible_user_ids()"],
        ["File:Line", "bookaid/views.py:583", "tasks/views.py:43"],
        ["Effect on co-host", "Sees tasks on host's properties (by property owner)", "Sees only tasks they personally created"],
    ],
    [90, 195, 195],
))
story.append(Spacer(1, 4))
story.append(note(
    "A co-host can see the host's tasks on the Calendar but NOT on the Task List page. "
    "Conversely, tasks the co-host creates appear on the Task List but are queried differently on the Calendar."
))

story.append(Spacer(1, 8))
story.append(Paragraph("Misalignment #2 - Calendar sidebar only shows active properties", h3))
story.append(Paragraph(
    "get_context_data() filters Property.objects.filter(status='Active') for the left sidebar, "
    "but get_bookings_data() fetches bookings without a property status filter. "
    "Bookings on non-active properties render on the grid but the property is missing from the sidebar.", body))

story.append(Spacer(1, 8))
story.append(Paragraph("Misalignment #3 - Enquiries pattern same as tasks", h3))
story.append(Paragraph(
    "Calendar fetches enquiries using property__created_by__in (Pattern A). "
    "If an Enquiry list page were added later using created_by__in (Pattern B), the same mismatch would occur.", body))
story.append(PageBreak())

story.append(Paragraph("9. Role-Based Data Differences Per Page", h1))
story.append(hr())
story.append(data_table(
    ["Page", "Host (owner)", "Co-host", "Admin"],
    [
        ["Dashboard",
         "All own + co-hosts' properties, bookings, revenue, tasks, enquiries",
         "Host's properties, bookings, revenue, enquiries. Tasks: only own (Pattern B).",
         "Django admin only"],
        ["Calendar",
         "All own + co-hosts' data via property ownership (Pattern A)",
         "All property data from host. Tasks visible. Enquiries visible.",
         "N/A"],
        ["Task List",
         "All tasks they created (Pattern B)",
         "Only tasks they created. Host's tasks NOT visible.",
         "N/A"],
        ["Booking List",
         "All bookings on own + co-hosts' properties (Pattern A)",
         "All bookings on host's properties.",
         "N/A"],
        ["Booking Details",
         "Full booking details with payment schedule",
         "Same as host (by property ownership filter).",
         "N/A"],
        ["Listing (public)",
         "Public view of own properties",
         "N/A (co-host has no public listing page)",
         "N/A"],
        ["Registration",
         "N/A (public page)",
         "N/A",
         "N/A"],
        ["Profile",
         "Full profile view and edit",
         "BLOCKED - redirects to dashboard with error",
         "Django admin"],
    ],
    [85, 135, 160, 100],
))
story.append(PageBreak())

story.append(Paragraph("10. Summary", h1))
story.append(hr())

bullets = [
    ("Two inconsistent filter patterns exist - Pattern A (by property owner) is used for most data "
     "(bookings, payments, enquiries, calendar). Pattern B (by creator) is only used for tasks. "
     "This creates inconsistent visibility for co-hosts.", RED),
    ("Co-hosts have limited profile access - They cannot view or edit their own profile, and all "
     "their actions are attributed to the host via get_effective_user().", AMBER),
    ("Calendar sidebar vs grid mismatch - The sidebar only lists active properties, but the grid "
     "can render bookings on inactive properties.", AMBER),
    ("Booking details lives under 'Payment Details' - There is no booking_detail.html; the details "
     "page is at /booking/payment-details/&lt;pk&gt;/.", ACCENT),
    ("Registration uses OTP flow - Multi-step: form -> OTP email -> OTP verification -> user "
     "creation -> auto-login. No data is fetched for page load.", ACCENT),
    ("All page data is scoped by get_visible_user_ids() - This ensures multi-user visibility while "
     "maintaining data isolation between unrelated hosts.", GREEN),
]

for text, color in bullets:
    bullet_style = ParagraphStyle("summ", parent=body,
        fontSize=9.5, leading=14, leftIndent=14, spaceBefore=4, spaceAfter=4,
        borderPadding=6)
    story.append(Paragraph(f"<b>[*]</b> {text}", bullet_style))
    story.append(Spacer(1, 2))

doc.build(story)
print("PDF generated: " + OUTPUT)

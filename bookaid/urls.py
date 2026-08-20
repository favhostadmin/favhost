"""
URL configuration for bookaid project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from .views import *

urlpatterns = [
    path('admin/', admin.site.urls),

    # Hidden platform-owner console (locked to the single PLATFORM_ADMIN_EMAIL).
    path('console/', include(('controlpanel.urls', 'controlpanel'), namespace='controlpanel')),

    # BILLING URLS
    path('', include(('billing.urls', 'billing'), namespace='billing')),

    # WEBSITE URLS
    path('sitemap.xml', TemplateView.as_view(template_name='sitemap.xml', content_type='application/xml'), name='sitemap'),
    path('robots.txt', robots_txt, name='robots'),

    path('', WebsiteIndexView.as_view(), name='index'),
    # SEO team's dynamic duplicate of the landing page — content edited from /console/seo/.
    path('home/', website_home_dynamic, name='home'),
    # Demo video served with HTTP Range support so the landing-page player can seek.
    path('media/demo-video.mp4', demo_video, name='demo-video'),
    path('resources/', WebsiteBlogView.as_view(), name='blog'),
    path('resources/<slug:slug>/', WebsiteBlogDetailsView.as_view(), name='blog-details'),
    path('tutorials/', TemplateView.as_view(template_name='frontend/tutorials/tutorials.html'), name='tutorials'),
    path('tutorials/<str:article>.html', tutorial_article, name='tutorial-article'),
    path('contact/', WebsiteContactView.as_view(), name='contact'),
    path('terms-and-conditions/', WebsiteTermsView.as_view(), name='terms'),
    path('privacy-policy/', WebsitePrivacyView.as_view(), name='privacy'),

    # BOOKING PORTAL URLS
    path('accounts/', include(('accounts.urls', 'accounts'), namespace='accounts')),
    path('accounts/', include('accounts.urls')),

    path('dashboard/',HostDashboardAPIView.as_view(), name='dashboard'),
    path('revenue/',RevenueByListingView.as_view(), name='revenue-by-listing'),
    path('accounting/', AccountingView.as_view(), name='accounting'),
    path('accounting/expense/add/', add_expense, name='accounting-expense-add'),
    path('accounting/expense/<uuid:pk>/edit/', edit_expense, name='accounting-expense-edit'),
    path('accounting/expense/<uuid:pk>/delete/', delete_expense, name='accounting-expense-delete'),
    path('property/', include(('property.urls', 'property'), namespace='property')),
    path('booking/', include(('booking.urls', 'booking'), namespace='booking')),
    path('tasks/', include(('tasks.urls', 'tasks'), namespace='tasks')),
    path('frontdesk/', include(('frontdesk.urls', 'frontdesk'), namespace='frontdesk')),
    path('global/', include(('global.urls', 'global'), namespace='global')),
    path('shared/', include(('shared.urls', 'shared'), namespace='shared')),
    path('print/', include(('printpanel.urls', 'printpanel'), namespace='printpanel')),
    path('calendar-grid-view/',CalenderAPIView.as_view(),name="calendar-grid-view"),
    path('calendar-timeline-view/',CalendarTimelineView.as_view(),name="calendar-timeline-view"),
    path('calendar-list-view/',CalendarListView.as_view(),name="calendar-list-view"),
    path('calendar-availability-view/',CalendarAvailabilityView.as_view(),name="calendar-availability-view"),

    path('calendar/',CalenderAPIView.as_view(),name="calendar"),
    path('manage/<uuid:property_id>/', channel_integration, name='channel_integration'),
    path('properties/<uuid:property_id>/channels/toggle-status/<int:channel_id>/', toggle_channel_status, name='toggle_channel_status'),
    path('properties/<uuid:property_id>/channels/delete/<int:channel_id>/', delete_channel, name='delete_channel'),
    path('api/manual-sync/', ManualSyncAPIView.as_view(), name='manual-sync'),
    path('contact-host/', contact_host, name='contact-host'),



]



if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

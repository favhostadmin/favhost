from django.urls import path
from .views import *

app_name = 'property'

urlpatterns = [
    path('add/', PropertyCreateView.as_view(), name='property-create'),
    path('edit/<uuid:pk>/', PropertyEditView.as_view(), name='property-edit'),
    path('delete/<uuid:pk>/', PropertyDeleteView.as_view(), name='property-delete'),
    path('list/', PropertyListView.as_view(), name='property-list'),
    path('detail/<slug:slug>/', PropertyDetailView.as_view(), name='property-detail'),
    path('ajax/delete-image/', DeleteImageView.as_view(), name='delete-image'),
    path('ajax/delete-document/', DeleteDocumentView.as_view(), name='delete-document'),
    path('toggle-status/<uuid:pk>/', PropertyToggleStatusView.as_view(), name='property-toggle-status'),
    path('<uuid:pk>/check-availability/', check_property_availability, name='property-check-availability'),
    path('ajax/get-available-properties/', AvailablePropertiesAjaxView.as_view(), name='ajax-get-available-properties'),
    path('ajax/block-dates/', BlockPropertyDateView.as_view(), name='ajax-block-dates'),
    path('ical/<uuid:pk>.ics', export_property_ical, name='ical-export'),
    # Public, signed link used by the guest check-in / check-out emails.
    path('document/<str:token>/', open_document, name='open-document'),
    path('policy/<uuid:pk>/<str:kind>/', property_policy, name='property-policy'),

    path('ajax-unblock-dates/', ajax_unblock_dates, name='ajax-unblock-dates'),



    # Public URLs
    # Airbnb-style public browse page, linked from the landing page navbar.
    path('explore/', ExploreListingView.as_view(), name='explore-listings'),
    path('listing/', ListingPageView.as_view(), name='listing-page'),
    path('listing/<str:short_code>/', ListingPageView.as_view(), name='listing-page-public'),
    # Updated public detail URL for a cleaner API structure
    path('listing-details/<str:short_code>/<slug:slug>/', ListingDetailView.as_view(), name='listing-detail-slug'),


    ### New Section Added by subhankar ####
    path('request-book/<uuid:pk>/', RequestBokPageView.as_view(), name='request-book-page-detail'),
    path('request-book/<slug:slug>/', RequestBokPageView.as_view(), name='request-book-page-slug'),
    path('request-book/', RequestBokPageView.as_view(), name='request-book-page'),

    # Google Places / Geocoding proxy (keeps API key server-side)
    path('ajax/places-autocomplete/', places_autocomplete_proxy, name='places-autocomplete'),
    path('ajax/place-details/', place_details_proxy, name='place-details'),
    path('ajax/geocode/', geocode_proxy, name='geocode'),
    
    


    
]

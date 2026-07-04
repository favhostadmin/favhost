from django.urls import path
from . import views

app_name = 'booking'

urlpatterns = [
    path('list/', views.BookingListView.as_view(), name='booking-list'),
    path('create/', views.BookingCreateView.as_view(), name='booking-create'),
    path('edit/<uuid:pk>/', views.BookingUpdateView.as_view(), name='booking-edit'),
    path('ajax/delete-guest-image/', views.delete_guest_image, name='delete-guest-image'),
    path('ajax/delete-guest-document/', views.delete_guest_document, name='delete-guest-document'),
    path('payment-details/<uuid:pk>/', views.payment_details, name='payment-details'),
    path('ajax/update-payment-status/', views.update_payment_status, name='update-payment-status'),
    path('ajax/add-payment-attachment/', views.add_payment_attachment, name='add-payment-attachment'),
    path('ajax/delete-payment-attachment/', views.delete_payment_attachment, name='delete-payment-attachment'),
    path('ajax/update-payment-notes/', views.update_payment_notes, name='update-payment-notes'),
    path('render-email-form/', views.render_email_form, name='render-email-form'),
    path('send-guest-email/', views.send_guest_email, name='send-guest-email'),
    path('guest-receipt/<uuid:pk>/', views.guest_receipt, name='guest-receipt'),

    path('cancel/<uuid:pk>/', views.CancelBookingView.as_view(), name='cancel-booking'),
    path('no-show/<uuid:pk>/', views.MarkNoShowView.as_view(), name='mark-no-show'),


    # Enquiry API endpoint
    path('enquiry/create/', views.enquiry_create_api, name='enquiry-create'),
    path('enquiry/list/', views.EnquiryListView.as_view(), name='enquiry-list'),
    path('enquiry/detail/<uuid:unique_id>/', views.EnquiryDetailView.as_view(), name='enquiry-detail'),
    path('enquiry/archive/<uuid:unique_id>/', views.archive_enquiry_api, name='enquiry-archive'),

]


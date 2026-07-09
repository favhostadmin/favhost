from django.urls import path
from . import views

app_name = 'frontdesk'

urlpatterns = [
    path('', views.FrontdeskIndexView.as_view(), name='index'),
    path('api/summary/', views.FrontdeskSummaryAPI.as_view(), name='api-summary'),
    path('api/checkins/', views.CheckInsAPI.as_view(), name='api-checkins'),
    path('api/checkouts/', views.CheckOutsAPI.as_view(), name='api-checkouts'),
    path('api/housekeeping/', views.HousekeepingAPI.as_view(), name='api-housekeeping'),
    path('api/cleaners/', views.CleanersAPI.as_view(), name='api-cleaners'),
    path('api/cleaners/<int:cleaner_id>/', views.CleanerDetailAPI.as_view(), name='api-cleaner-detail'),
    path('print/', views.HousekeepingPrintPanelView.as_view(), name='print-panel'),
    path('print/preview/', views.HousekeepingPrintPreviewView.as_view(), name='print-preview'),
    path('print/pdf/', views.HousekeepingPrintPDFView.as_view(), name='print-pdf'),
]

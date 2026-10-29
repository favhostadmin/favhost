from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'aibooster'

urlpatterns = [
    path('photo-enhancer/', views.image_page, name='image'),
    path('photo-enhancer/start/', views.image_start, name='image-start'),
    path('photo-enhancer/checkout/', views.image_checkout, name='image-checkout'),
    path('photo-enhancer/unlock/', views.image_unlock, name='image-unlock'),
    path('photo-enhancer/status/', views.image_status, name='image-status'),
    path('photo-enhancer/reset/', views.image_reset, name='image-reset'),
    path('photo-enhancer/<uuid:job_id>/before/', views.image_before, name='image-before'),
    path('photo-enhancer/<uuid:job_id>/after/', views.image_after, name='image-after'),
    path('download/<str:token>/', views.image_download, name='image-download'),
    path('listing-optimize/', views.report_page, name='report'),
    path('listing-optimize/checkout/', views.report_checkout, name='report-checkout'),
    path('listing-optimize/start/', views.report_start, name='report-start'),
    path('listing-optimize/reset/', views.report_reset, name='report-reset'),
    path('listing-optimize/status/<uuid:report_id>/', views.report_status, name='report-status'),
    path('listing-optimize/<uuid:report_id>/download/', views.report_download, name='report-download'),
    # old addresses keep working
    path('image/', RedirectView.as_view(pattern_name='aibooster:image', permanent=True)),
    path('listing-audit/', RedirectView.as_view(pattern_name='aibooster:report', permanent=True)),
    path('report/', RedirectView.as_view(pattern_name='aibooster:report', permanent=True)),
]

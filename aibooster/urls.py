from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'aibooster'

urlpatterns = [
    path('photo-enhancer/', views.image_page, name='image'),
    path('photo-enhancer/start/', views.image_start, name='image-start'),
    path('photo-enhancer/continue/', views.image_continue, name='image-continue'),
    path('photo-enhancer/unlock/', views.image_unlock, name='image-unlock'),
    path('photo-enhancer/status/', views.image_status, name='image-status'),
    path('photo-enhancer/<uuid:job_id>/before/', views.image_before, name='image-before'),
    path('photo-enhancer/<uuid:job_id>/after/', views.image_after, name='image-after'),
    path('download/<str:token>/', views.image_download, name='image-download'),
    path('listing-audit/', views.report_page, name='report'),
    path('listing-audit/start/', views.report_start, name='report-start'),
    path('listing-audit/status/<uuid:report_id>/', views.report_status, name='report-status'),
    path('listing-audit/<uuid:report_id>/download/', views.report_download, name='report-download'),
    # old addresses keep working
    path('image/', RedirectView.as_view(pattern_name='aibooster:image', permanent=True)),
    path('report/', RedirectView.as_view(pattern_name='aibooster:report', permanent=True)),
]

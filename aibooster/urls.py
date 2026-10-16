from django.urls import path

from . import views

app_name = 'aibooster'

urlpatterns = [
    path('image/', views.image_page, name='image'),
    path('image/start/', views.image_start, name='image-start'),
    path('image/continue/', views.image_continue, name='image-continue'),
    path('image/unlock/', views.image_unlock, name='image-unlock'),
    path('image/status/', views.image_status, name='image-status'),
    path('image/<uuid:job_id>/before/', views.image_before, name='image-before'),
    path('image/<uuid:job_id>/after/', views.image_after, name='image-after'),
    path('download/<str:token>/', views.image_download, name='image-download'),
    path('report/', views.report_page, name='report'),
    path('report/start/', views.report_start, name='report-start'),
    path('report/status/<uuid:report_id>/', views.report_status, name='report-status'),
]

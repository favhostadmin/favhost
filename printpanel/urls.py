from django.urls import path
from . import views

app_name = 'printpanel'

urlpatterns = [
    path('', views.PrintPanelView.as_view(), name='editor'),
    path('preview/', views.PrintPreviewView.as_view(), name='preview'),
    path('pdf/', views.PrintPDFView.as_view(), name='pdf'),
]

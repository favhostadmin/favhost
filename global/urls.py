from django.urls import path
from . import views

app_name = 'global'

urlpatterns = [
    path('api/countries/', views.country_list_api, name='country-list'),
    path('api/states/<str:country_code>/', views.state_list_api, name='state-list'),
]
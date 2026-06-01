from django.urls import path

from .views import (
    TaskCreateView,
    TaskListView,
    TaskEditView,
    TaskDeleteView,
    UpdateTaskStatusView
)

app_name = "tasks"

urlpatterns = [
    path('list/', TaskListView.as_view(), name='task-list'),
    path('create/', TaskCreateView.as_view(), name='task-create'),
    path('edit/<int:pk>/', TaskEditView.as_view(), name='task-edit'),
    path('delete/<int:pk>/', TaskDeleteView.as_view(), name='task-delete'),
    path('update-status/<int:pk>/', UpdateTaskStatusView.as_view(), name='task-update-status'),
]

from django.contrib import admin
from .models import *
# Register your models here.

# admin.site.register(Task)
admin.site.register(TaskImage)

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'property','recurrence_id', 'date')


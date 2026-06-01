from django.contrib import admin
from .models import *

# Register your models here.
@admin.register(MyUser)
class MyUserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'short_code', 'public_uuid', 'is_active', 'is_staff')
    readonly_fields = ('short_code', 'public_uuid', 'created_at', 'updated_at')
    search_fields = ('username', 'email', 'short_code', 'public_uuid')

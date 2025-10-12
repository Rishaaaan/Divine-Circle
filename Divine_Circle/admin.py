from django.contrib import admin
from .models import PoojaEvent, PoojaBooking

# Register your models here.
@admin.register(PoojaEvent)
class PoojaEventAdmin(admin.ModelAdmin):
    list_display = ("title", "pooja_type", "date", "start_time", "end_time", "is_active")
    list_filter = ("pooja_type", "date", "is_active")
    search_fields = ("title", "pooja_type", "description")


@admin.register(PoojaBooking)
class PoojaBookingAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "event", "payment_status", "created_at")
    list_filter = ("payment_status", "created_at")
    search_fields = ("name", "email", "phone", "message")

from django.contrib import admin
from django import forms
from datetime import time
from .models import PoojaEvent, PoojaBooking, PoojaSlot

# Register your models here.
@admin.register(PoojaEvent)
class PoojaEventAdmin(admin.ModelAdmin):
    class PoojaEventForm(forms.ModelForm):
        copy_from = forms.ModelChoiceField(
            queryset=PoojaEvent.objects.all(), required=False, label="Copy fields from event"
        )
        copy_slots_from = forms.ModelChoiceField(
            queryset=PoojaEvent.objects.all(), required=False, label="Copy time slots from event"
        )
        class Meta:
            model = PoojaEvent
            fields = "__all__"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Prefill defaults when creating a new event or when fields empty
            if not self.instance or not self.instance.pk:
                if not self.fields["start_time"].initial:
                    self.fields["start_time"].initial = time(0, 0, 0)
                if not self.fields["end_time"].initial:
                    self.fields["end_time"].initial = time(23, 59, 59)

    list_display = ("title", "pooja_type", "date", "start_time", "end_time", "is_active")
    list_filter = ("pooja_type", "date", "is_active")
    search_fields = ("title", "pooja_type", "description")
    actions = [
        "copy_samagri_description_from_first",
        "copy_details_from_first",
        "copy_slots_from_first_event",
    ]
    form = PoojaEventForm

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Inline copy fields after first save (ensures PK exists)
        src = form.cleaned_data.get("copy_from")
        if src:
            obj.pooja_type = src.pooja_type
            obj.samagri = src.samagri
            obj.description = src.description
            if src.start_time:
                obj.start_time = src.start_time
            if src.end_time:
                obj.end_time = src.end_time
            obj.save(update_fields=["pooja_type", "samagri", "description", "start_time", "end_time"])
            self.message_user(request, f"Copied fields from '{src.title}' into this event.")
        slots_src = form.cleaned_data.get("copy_slots_from")
        if slots_src:
            created = 0
            for s in slots_src.slots.all():
                if not obj.slots.filter(start_time=s.start_time).exists():
                    PoojaSlot.objects.create(
                        event=obj,
                        start_time=s.start_time,
                        end_time=s.end_time,
                        capacity=s.capacity,
                        booked_count=0,
                        is_active=s.is_active,
                    )
                    created += 1
            if created:
                self.message_user(request, f"Copied {created} slots from '{slots_src.title}'.")

    def copy_samagri_description_from_first(self, request, queryset):
        events = list(queryset.order_by("date", "start_time"))
        if not events:
            self.message_user(request, "No events selected.")
            return
        source = events[0]
        updated = 0
        for target in events[1:]:
            target.samagri = source.samagri
            target.description = source.description
            target.save(update_fields=["samagri", "description"])
            updated += 1
        self.message_user(request, f"Imported samagri & description from '{source.title}' into {updated} events.")
    copy_samagri_description_from_first.short_description = "Import samagri & description from first selected into others"

    def copy_details_from_first(self, request, queryset):
        events = list(queryset.order_by("date", "start_time"))
        if not events:
            self.message_user(request, "No events selected.")
            return
        source = events[0]
        updated = 0
        for target in events[1:]:
            target.pooja_type = source.pooja_type
            target.samagri = source.samagri
            target.description = source.description
            if source.start_time:
                target.start_time = source.start_time
            if source.end_time:
                target.end_time = source.end_time
            target.save(update_fields=["pooja_type", "samagri", "description", "start_time", "end_time"])
            updated += 1
        self.message_user(request, f"Copied details (type, times, samagri, description) from '{source.title}' to {updated} events.")
    copy_details_from_first.short_description = "Copy details (type, times, samagri, description) from first selected"

    def copy_slots_from_first_event(self, request, queryset):
        events = list(queryset.order_by("date", "start_time").prefetch_related("slots"))
        if len(events) < 2:
            self.message_user(request, "Select at least two events (first = source, others = targets).")
            return
        source = events[0]
        source_slots = list(source.slots.all())
        created = 0
        for target in events[1:]:
            for s in source_slots:
                # copy times and capacity; booked_count stays 0 by default
                exists = target.slots.filter(start_time=s.start_time).exists()
                if not exists:
                    target.slots.model.objects.create(
                        event=target,
                        start_time=s.start_time,
                        end_time=s.end_time,
                        capacity=s.capacity,
                        booked_count=0,
                        is_active=s.is_active,
                    )
                    created += 1
        self.message_user(request, f"Copied {created} slots from source event '{source.title}' to selected targets (skipped duplicates).")
    copy_slots_from_first_event.short_description = "Copy all time slots from first selected event to others"


@admin.register(PoojaBooking)
class PoojaBookingAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone", "event", "slot", "payment_status", "created_at")
    list_filter = ("payment_status", "created_at")
    search_fields = ("name", "email", "phone", "message")


@admin.register(PoojaSlot)
class PoojaSlotAdmin(admin.ModelAdmin):
    class PoojaSlotForm(forms.ModelForm):
        bulk_copy_from_event = forms.ModelChoiceField(
            queryset=PoojaEvent.objects.all(), required=False, label="Copy all timings from event into selected event"
        )
        class Meta:
            model = PoojaSlot
            fields = "__all__"

    form = PoojaSlotForm
    list_display = ("event", "start_time", "end_time", "capacity", "booked_count", "remaining", "is_active")
    list_filter = ("event", "is_active")
    list_editable = ("capacity", "booked_count", "is_active")
    search_fields = ("event__title",)

    actions = ["fill_to_capacity", "clear_bookings"]

    def fill_to_capacity(self, request, queryset):
        updated = 0
        for slot in queryset:
            if slot.capacity > slot.booked_count:
                slot.booked_count = slot.capacity
                slot.save(update_fields=["booked_count"])
                updated += 1
        self.message_user(request, f"Filled {updated} slots to capacity (dummy bookings).")
    fill_to_capacity.short_description = "Fill selected slots to capacity (dummy bookings)"

    def clear_bookings(self, request, queryset):
        updated = queryset.update(booked_count=0)
        self.message_user(request, f"Cleared booked_count for {updated} slots.")
    clear_bookings.short_description = "Clear booked counts"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        src_event = form.cleaned_data.get("bulk_copy_from_event")
        if src_event and obj.event_id:
            created = 0
            for s in PoojaSlot.objects.filter(event=src_event):
                if not PoojaSlot.objects.filter(event=obj.event, start_time=s.start_time).exists():
                    PoojaSlot.objects.create(
                        event=obj.event,
                        start_time=s.start_time,
                        end_time=s.end_time,
                        capacity=s.capacity,
                        booked_count=0,
                        is_active=s.is_active,
                    )
                    created += 1
            if created:
                self.message_user(request, f"Copied {created} timings from '{src_event.title}' into event '{obj.event.title}'.")

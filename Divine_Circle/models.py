from django.db import models

# Create your models here.

class PoojaEvent(models.Model):
    title = models.CharField(max_length=200)
    pooja_type = models.CharField(max_length=100)
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    samagri = models.TextField(blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["date", "start_time"]
        unique_together = ("pooja_type", "date", "start_time")

    def __str__(self):
        return f"{self.title} on {self.date}"


class PoojaSlot(models.Model):
    event = models.ForeignKey(PoojaEvent, on_delete=models.CASCADE, related_name="slots")
    start_time = models.TimeField()
    end_time = models.TimeField(null=True, blank=True)
    capacity = models.PositiveIntegerField(default=0)
    booked_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["event", "start_time"]
        unique_together = ("event", "start_time")

    def __str__(self):
        return f"{self.event.title} {self.start_time.strftime('%H:%M')} ({self.remaining} left)"

    @property
    def remaining(self) -> int:
        rem = int(self.capacity) - int(self.booked_count)
        return rem if rem > 0 else 0


class PoojaBooking(models.Model):
    event = models.ForeignKey(PoojaEvent, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings")
    slot = models.ForeignKey(PoojaSlot, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings")
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    message = models.TextField(blank=True)
    payment_status = models.CharField(max_length=20, default="no")
    # Razorpay tracking fields
    razorpay_order_id = models.CharField(max_length=100, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    razorpay_signature = models.CharField(max_length=200, blank=True)
    amount_paise = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=10, default="INR")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Booking by {self.name} ({self.email}) - {self.payment_status}"

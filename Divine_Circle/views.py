from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils.dateparse import parse_date
from .models import PoojaEvent, PoojaBooking, PoojaSlot
import json
import datetime
import os
import requests
import logging
from django.db import transaction

from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.logging.configuration.api_logging_configuration import (
    LoggingConfiguration,
    RequestLoggingConfiguration,
    ResponseLoggingConfiguration,
)
from paypalserversdk.configuration import (
    Environment,                        # <-- ADD THIS import
)
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient
from paypalserversdk.controllers.orders_controller import OrdersController
from paypalserversdk.controllers.payments_controller import PaymentsController
from paypalserversdk.models.amount_breakdown import AmountBreakdown
from paypalserversdk.models.amount_with_breakdown import AmountWithBreakdown
from paypalserversdk.models.checkout_payment_intent import CheckoutPaymentIntent
from paypalserversdk.models.order_request import OrderRequest
from paypalserversdk.models.money import Money
from paypalserversdk.models.purchase_unit_request import PurchaseUnitRequest
from paypalserversdk.exceptions.error_exception import ErrorException

def cron_keepalive(request):
    return HttpResponse("OK")
# Create your views here.
def landing(request):
    return render(request, 'landing.html')

def bookings(request):
    return render(request, 'bookings.html', {
        # Use LIVE client id from environment for SDK
        "paypal_client_id": os.environ.get("PAYPAL_CLIENT_ID", "")
    })

@require_http_methods(["GET"])
def events_by_month(request):
    try:
        year = int(request.GET.get("year"))
        month = int(request.GET.get("month"))
    except (TypeError, ValueError):
        today = datetime.date.today()
        year, month = today.year, today.month

    qs = PoojaEvent.objects.filter(is_active=True, date__year=year, date__month=month).order_by("date", "start_time")
    events = []
    remaining_per_date = {}
    for e in qs:
        events.append({
            "id": e.id,
            "date": e.date.isoformat(),
            "title": e.title,
            "pooja_type": e.pooja_type,
            "start_time": e.start_time.strftime('%H:%M') if e.start_time else None,
            "end_time": e.end_time.strftime('%H:%M') if e.end_time else None,
        })
        # sum remaining slots per date
        date_key = e.date.isoformat()
        if date_key not in remaining_per_date:
            remaining_per_date[date_key] = 0
        date_slots = PoojaSlot.objects.filter(event__date=e.date, event__is_active=True, is_active=True)
        for s in date_slots:
            rem = max(int(s.capacity) - int(s.booked_count), 0)
            remaining_per_date[date_key] += rem
    return JsonResponse({"events": events, "remaining_per_date": remaining_per_date})

@require_http_methods(["GET"])
def events_by_date(request, date):
    d = parse_date(date)
    if not d:
        return JsonResponse({"error": "Invalid date"}, status=400)
    qs = PoojaEvent.objects.filter(is_active=True, date=d).order_by("start_time")
    events = []
    for e in qs:
        # include slots with remaining for each event
        slots = []
        for s in e.slots.filter(is_active=True).order_by("start_time"):
            slots.append({
                "id": s.id,
                "start_time": s.start_time.strftime('%H:%M'),
                "end_time": s.end_time.strftime('%H:%M') if s.end_time else None,
                "capacity": s.capacity,
                "booked_count": s.booked_count,
                "remaining": max(int(s.capacity) - int(s.booked_count), 0),
            })
        events.append({
            "id": e.id,
            "title": e.title,
            "pooja_type": e.pooja_type,
            "samagri": e.samagri,
            "description": e.description,
            "start_time": e.start_time.strftime('%H:%M') if e.start_time else None,
            "end_time": e.end_time.strftime('%H:%M') if e.end_time else None,
            "slots": slots,
        })
    return JsonResponse({"date": d.isoformat(), "events": events})

# Initialize PayPal client properly
paypal_client = PaypalServersdkClient(
    client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
        o_auth_client_id=os.getenv("PAYPAL_CLIENT_ID", ""),
        o_auth_client_secret=os.getenv("PAYPAL_CLIENT_SECRET", ""),
    ),
    environment=Environment.PRODUCTION,  # <-- set environment here, not in credentials
    logging_configuration=LoggingConfiguration(
        log_level=logging.INFO,
        mask_sensitive_headers=True,
        request_logging_config=RequestLoggingConfiguration(
            log_headers=True,
            log_body=False
        ),
        response_logging_config=ResponseLoggingConfiguration(
            log_headers=True,
            log_body=False
        ),
    ),
)

# Controllers derived from the initialized PayPal client
orders_controller: OrdersController = paypal_client.orders
payments_controller: PaymentsController = paypal_client.payments

@csrf_exempt
@require_http_methods(["POST"])
def create_booking(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    message = (data.get("message") or "").strip()
    event_id = data.get("event_id")
    slot_id = data.get("slot_id")
    preferred_date = (data.get("preferred_date") or "").strip() or None
    preferred_slot = (data.get("preferred_slot") or "").strip()
    pooja_type = (data.get("pooja_type") or "").strip()
    preferred_date = (data.get("preferred_date") or "").strip() or None
    preferred_slot = (data.get("preferred_slot") or "").strip()
    pooja_type = (data.get("pooja_type") or "").strip()

    if not name or not email:
        return JsonResponse({"error": "Name and email are required"}, status=400)

    event = None
    if event_id:
        event = get_object_or_404(PoojaEvent, pk=event_id)
    slot = None
    if slot_id:
        slot = get_object_or_404(PoojaSlot, pk=slot_id, is_active=True)
        if event and slot.event_id != event.id:
            return JsonResponse({"error": "Slot does not belong to selected event"}, status=400)
        if int(slot.booked_count) >= int(slot.capacity):
            return JsonResponse({"error": "Selected slot is fully booked"}, status=400)

    # Optional slot validation if provided (single coherent block)
    slot = None
    if slot_id:
        slot = get_object_or_404(PoojaSlot, pk=slot_id, is_active=True)
        if event and slot.event_id != event.id:
            return JsonResponse({"error": "Slot does not belong to selected event"}, status=400)
        if int(slot.booked_count) >= int(slot.capacity):
            return JsonResponse({"error": "Selected slot is fully booked"}, status=400)

    booking = PoojaBooking.objects.create(
        event=event,
        slot=slot,
        preferred_date=preferred_date,
        preferred_slot=preferred_slot,
        pooja_type=pooja_type,
        name=name,
        email=email,
        phone=phone,
        message=message,
        payment_status="no",
    )
    return JsonResponse({
        "id": booking.id,
        "payment_status": booking.payment_status,
        "created_at": booking.created_at.isoformat(),
    }, status=201)

@csrf_exempt
@require_http_methods(["POST"])
def create_paypal_order(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Ensure slot exists in scope regardless of later conditions
    slot = None

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    message = (data.get("message") or "").strip()
    event_id = data.get("event_id")
    slot_id = data.get("slot_id")
    # Force all bookings to 99.00 USD
    requested_currency = "USD"
    BASE_USD_AMOUNT = 99.0

    if not name or not email:
        return JsonResponse({"error": "Name and email are required"}, status=400)

    # Always use USD 99.00
    converted_amount = BASE_USD_AMOUNT

    amount_minor = int(round(converted_amount * 100))
    amount_value_str = f"{converted_amount:.2f}"

    currency = requested_currency

    event = None
    if event_id:
        event = get_object_or_404(PoojaEvent, pk=event_id)
    
    # Extract optional custom booking fields
    preferred_date = (data.get("preferred_date") or "").strip() or None
    preferred_slot = (data.get("preferred_slot") or "").strip()
    pooja_type = (data.get("pooja_type") or "").strip()

    # Optional slot validation if provided
    slot = None
    if slot_id:
        slot = get_object_or_404(PoojaSlot, pk=slot_id, is_active=True)
        if event and slot.event_id != event.id:
            return JsonResponse({"error": "Slot does not belong to selected event"}, status=400)
        if int(slot.booked_count) >= int(slot.capacity):
            return JsonResponse({"error": "Selected slot is fully booked"}, status=400)

    booking = PoojaBooking.objects.create(
        event=event,
        slot=slot,
        preferred_date=preferred_date,
        preferred_slot=preferred_slot,
        pooja_type=pooja_type,
        name=name,
        email=email,
        phone=phone,
        message=message,
        payment_status="no",
        amount_paise=amount_minor,
        currency=currency,
    )

    try:
        order = orders_controller.create_order({
            "prefer": "return=representation",
            "body": OrderRequest(
                intent=CheckoutPaymentIntent.CAPTURE,
                purchase_units=[
                    PurchaseUnitRequest(
                        amount=AmountWithBreakdown(
                            currency_code=currency,
                            value=amount_value_str,
                            breakdown=AmountBreakdown(
                                item_total=Money(currency_code=currency, value=amount_value_str)
                            ),
                        ),
                    )
                ],
            )
        })
        order_id = getattr(order.body, "id", None)
        if not order_id:
            return JsonResponse({"error": "Failed to create PayPal order"}, status=500)
    except ErrorException as e:
        return JsonResponse({"error": "PayPal error creating order", "details": str(e)}, status=500)

    return JsonResponse({
        "booking_id": booking.id,
        "order_id": order.body.id,
        "amount": amount_value_str,
        "currency": currency,
    })

@csrf_exempt
@require_http_methods(["POST"])
def contact_submit(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    message = (data.get("message") or "").strip()

    if not name or not email or not message:
        return JsonResponse({"error": "Name, email and message are required"}, status=400)

    from .models import ContactMessage
    cm = ContactMessage.objects.create(name=name, email=email, phone=phone, message=message)
    return JsonResponse({"status": "ok", "id": cm.id, "created_at": cm.created_at.isoformat()})

@csrf_exempt
@require_http_methods(["POST"])
def capture_paypal_order(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    booking_id = data.get("booking_id")
    order_id = data.get("order_id")
    if not (booking_id and order_id):
        return JsonResponse({"error": "Missing booking_id or order_id"}, status=400)

    booking = get_object_or_404(PoojaBooking, pk=booking_id)

    try:
        order = orders_controller.capture_order({"id": order_id, "prefer": "return=representation"})
    except ErrorException as e:
        return JsonResponse({"error": "PayPal error capturing order", "details": str(e)}, status=500)

    status = getattr(order.body, "status", "") or ""
    completed = status.upper() == "COMPLETED"

    if not completed:
        return JsonResponse({"error": "Payment not completed", "status": status}, status=400)

    # finalize slot booking if provided and capacity available
    if booking.slot_id:
        try:
            with transaction.atomic():
                slot = PoojaSlot.objects.select_for_update().get(pk=booking.slot_id)
                if slot.booked_count < slot.capacity:
                    slot.booked_count = slot.booked_count + 1
                    slot.save(update_fields=["booked_count"])
                else:
                    # slot became full between order and capture
                    return JsonResponse({"error": "Slot just became full. Payment captured but booking cannot be assigned. Please contact support."}, status=409)
        except PoojaSlot.DoesNotExist:
            pass
    booking.payment_status = "yes"
    booking.save(update_fields=["payment_status"])

    # Send email notification on successful booking
    try:
        subject = "New Pooja Booking Confirmed"
        body_lines = [
            f"Name: {booking.name}",
            f"Email: {booking.email}",
            f"Phone: {booking.phone}",
            f"Pooja Type: {booking.pooja_type or (booking.event.pooja_type if booking.event else '')}",
            f"Preferred Date: {booking.preferred_date or (booking.event.date if booking.event else '')}",
            f"Preferred Slot: {booking.preferred_slot or (booking.slot.start_time if booking.slot else '')}",
            f"Payment Status: {booking.payment_status}",
            f"Booking ID: {booking.id}",
        ]
        body = "\n".join(["A new booking has been completed:"] + body_lines)
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@circledivine.com')
        send_mail(subject, body, from_email, ["rishangupta857@gmail.com"], fail_silently=True)
    except Exception:
        # Do not fail the capture if email sending fails
        pass

    return JsonResponse({"status": "success", "payment_status": booking.payment_status})
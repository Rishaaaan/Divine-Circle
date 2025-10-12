from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils.dateparse import parse_date
from .models import PoojaEvent, PoojaBooking
import json
import datetime
import os
import razorpay
import requests

def cron_keepalive(request):
    return HttpResponse("OK")
# Create your views here.
def landing(request):
    return render(request, 'landing.html')

def bookings(request):
    return render(request, 'bookings.html')

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
    for e in qs:
        events.append({
            "id": e.id,
            "date": e.date.isoformat(),
            "title": e.title,
            "pooja_type": e.pooja_type,
            "start_time": e.start_time.strftime('%H:%M') if e.start_time else None,
            "end_time": e.end_time.strftime('%H:%M') if e.end_time else None,
        })
    return JsonResponse({"events": events})

@require_http_methods(["GET"])
def events_by_date(request, date):
    d = parse_date(date)
    if not d:
        return JsonResponse({"error": "Invalid date"}, status=400)
    qs = PoojaEvent.objects.filter(is_active=True, date=d).order_by("start_time")
    events = []
    for e in qs:
        events.append({
            "id": e.id,
            "title": e.title,
            "pooja_type": e.pooja_type,
            "samagri": e.samagri,
            "description": e.description,
            "start_time": e.start_time.strftime('%H:%M') if e.start_time else None,
            "end_time": e.end_time.strftime('%H:%M') if e.end_time else None,
        })
    return JsonResponse({"date": d.isoformat(), "events": events})

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

    if not name or not email:
        return JsonResponse({"error": "Name and email are required"}, status=400)

    event = None
    if event_id:
        event = get_object_or_404(PoojaEvent, pk=event_id)

    booking = PoojaBooking.objects.create(
        event=event,
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
def create_razorpay_order(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    message = (data.get("message") or "").strip()
    event_id = data.get("event_id")
    # Pricing: fixed 30 USD converted to selected currency
    requested_currency = (data.get("currency") or "USD").upper()
    BASE_USD_AMOUNT = 30.0

    # Fetch FX rate USD->requested_currency
    fx_rate = 1.0
    if requested_currency != "USD":
        try:
            r = requests.get(
                "https://api.exchangerate.host/convert",
                params={"from": "USD", "to": requested_currency, "amount": BASE_USD_AMOUNT},
                timeout=8,
            )
            if r.ok:
                conv = r.json()
                # conv["result"] is the converted amount in target currency
                converted_amount = float(conv.get("result") or 0)
            else:
                converted_amount = 0
        except Exception:
            converted_amount = 0
        if converted_amount <= 0:
            # fallback with simple heuristic 1 USD ~ 85 INR for INR or ~1 for majors
            if requested_currency == "INR":
                converted_amount = BASE_USD_AMOUNT * 85.0
            else:
                converted_amount = BASE_USD_AMOUNT * 1.0
    else:
        converted_amount = BASE_USD_AMOUNT

    # Razorpay amounts are in minor units for most currencies; zero-decimal list below
    ZERO_DECIMAL = {"JPY", "KRW", "VND"}
    if requested_currency in ZERO_DECIMAL:
        amount_minor = int(round(converted_amount))
    else:
        amount_minor = int(round(converted_amount * 100))

    amount_paise = amount_minor
    currency = requested_currency

    if not name or not email:
        return JsonResponse({"error": "Name and email are required"}, status=400)

    event = None
    if event_id:
        event = get_object_or_404(PoojaEvent, pk=event_id)

    booking = PoojaBooking.objects.create(
        event=event,
        name=name,
        email=email,
        phone=phone,
        message=message,
        payment_status="no",
        amount_paise=amount_paise,
        currency=currency,
    )

    key_id = "rzp_test_RS9J9ggdkOFrEm" #os.environ.get("RAZORPAY_KEY_ID")
    key_secret = "Y8j4FuDSakAActc8BjBLnxri" #os.environ.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        return JsonResponse({"error": "Razorpay keys not configured"}, status=500)

    client = razorpay.Client(auth=(key_id, key_secret))
    notes = {
        "booking_id": str(booking.id),
        "name": booking.name,
        "email": booking.email,
        "phone": booking.phone,
        "pooja_type": event.pooja_type if event else "",
        "pooja_title": event.title if event else "",
        "pooja_date": event.date.isoformat() if event else "",
    }
    order = client.order.create({
        "amount": amount_paise,
        "currency": currency,
        "payment_capture": 1,
        "notes": notes,
        "receipt": f"DCBK-{booking.id}",
    })

    booking.razorpay_order_id = order.get("id", "")
    booking.save(update_fields=["razorpay_order_id"])

    return JsonResponse({
        "booking_id": booking.id,
        "order_id": booking.razorpay_order_id,
        "amount": amount_paise,
        "currency": currency,
        "key_id": key_id,
        "customer": {
            "name": booking.name,
            "email": booking.email,
            "contact": booking.phone,
        },
        "display": {
            "title": event.title if event else "Divine Circle Pooja Booking",
            "description": (event.pooja_type if event else "Pooja") + (f" on {event.date.isoformat()}" if event else ""),
        },
        "notes": notes,
    })

@csrf_exempt
@require_http_methods(["POST"])
def verify_razorpay_payment(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    booking_id = data.get("booking_id")
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_signature = data.get("razorpay_signature")

    if not (booking_id and razorpay_payment_id and razorpay_order_id and razorpay_signature):
        return JsonResponse({"error": "Missing fields"}, status=400)

    booking = get_object_or_404(PoojaBooking, pk=booking_id)

    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        return JsonResponse({"error": "Razorpay keys not configured"}, status=500)

    client = razorpay.Client(auth=(key_id, key_secret))
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        })
    except razorpay.errors.SignatureVerificationError:
        return JsonResponse({"error": "Signature verification failed"}, status=400)

    booking.razorpay_payment_id = razorpay_payment_id
    booking.razorpay_signature = razorpay_signature
    booking.payment_status = "yes"
    booking.save(update_fields=["razorpay_payment_id", "razorpay_signature", "payment_status"])

    return JsonResponse({"status": "success", "payment_status": booking.payment_status})
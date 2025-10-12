from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing, name='landing'),
    path('cron-keepalive/', views.cron_keepalive, name='cron_keepalive'),
    path('bookings/', views.bookings, name='bookings'),
    path('api/events/', views.events_by_month, name='events_by_month'),
    path('api/events/<str:date>/', views.events_by_date, name='events_by_date'),
    path('api/bookings/', views.create_booking, name='create_booking'),
    path('api/payments/razorpay/order/', views.create_razorpay_order, name='create_razorpay_order'),
    path('api/payments/razorpay/verify/', views.verify_razorpay_payment, name='verify_razorpay_payment'),
]

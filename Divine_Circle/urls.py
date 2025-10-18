from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing, name='landing'),
    path('cron-keepalive/', views.cron_keepalive, name='cron_keepalive'),
    path('bookings/', views.bookings, name='bookings'),
    path('api/events/', views.events_by_month, name='events_by_month'),
    path('api/events/<str:date>/', views.events_by_date, name='events_by_date'),
    path('api/bookings/', views.create_booking, name='create_booking'),
    path('api/payments/paypal/order/', views.create_paypal_order, name='create_paypal_order'),
    path('api/payments/paypal/capture/', views.capture_paypal_order, name='capture_paypal_order'),
    path('api/contact/submit/', views.contact_submit, name='contact_submit'),
]

from django.shortcuts import render
from django.http import HttpResponse

def cron_keepalive(request):
    return HttpResponse("OK")
# Create your views here.
def landing(request):
    return render(request, 'landing.html')
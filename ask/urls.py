from django.urls import path
from . import views

app_name = 'ask'

urlpatterns = [
    path('', views.home, name='home'),
    path('api/<path:path>', views.api_forwarder, name='api_forwarder'),
]
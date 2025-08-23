from django.urls import path
from . import views

app_name = 'ask'

urlpatterns = [
    path('', views.home, name='home'),
    path('api/profit-loss-overview/', views.api_profit_loss_overview, name='api_profit_loss_overview'),
]
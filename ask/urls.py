from django.urls import path
from . import views

app_name = "ask"

urlpatterns = [
    path("", views.test_intent, name="home"),
    path("chat", views.ai_chat, name="ai_chat"),
    path("api/<path:path>", views.api_forwarder, name="api_forwarder"),
]

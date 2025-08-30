from django.urls import path
from . import views

app_name = "ask"

urlpatterns = [
    path("", views.home, name="home"),
    path("chat-message/", views.chat_message, name="chat_message"),
    path("chat", views.ai_chat, name="ai_chat"),
    path("api/<path:path>", views.api_forwarder, name="api_forwarder"),
]

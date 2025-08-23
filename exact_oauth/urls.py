from django.urls import path
from . import views

app_name = "exact_oauth"

urlpatterns = [
    path("", views.status, name="status"),
    path("authorize/", views.authorize, name="authorize"),
    path("callback/", views.callback, name="callback"),
    path("refresh/", views.refresh_token, name="refresh_token"),
    path("revoke/", views.revoke, name="revoke"),
    path("test/", views.test_api, name="test_api"),
]

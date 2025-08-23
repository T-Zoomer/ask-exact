from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
import requests
import secrets
import urllib.parse

from .models import (
    ExactOnlineToken,
    ExactOnlineAuthState,
    get_exact_config,
    get_auth_base_url,
)
from .services import ExactOnlineService


def get_session_key(request):
    """Ensure session has a key and return it"""
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def authorize(request):
    """Start OAuth authorization flow"""
    config = get_exact_config()

    # Validate config
    if not config["client_id"] or not config["client_secret"]:
        messages.error(
            request,
            "Exact Online not configured. Set EXACT_CLIENT_ID and EXACT_CLIENT_SECRET environment variables.",
        )
        return redirect("exact_oauth:status")

    session_key = get_session_key(request)

    state = secrets.token_urlsafe(32)
    ExactOnlineAuthState.objects.create(session_key=session_key, state=state)

    auth_params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "state": state,
        "force_login": "0",
    }

    base_url = get_auth_base_url(config["country"])
    auth_url = f"{base_url}/api/oauth2/auth?" + urllib.parse.urlencode(auth_params)

    return redirect(auth_url)


def callback(request):
    """Handle OAuth callback"""
    code = request.GET.get("code")
    state = request.GET.get("state")
    error = request.GET.get("error")

    if error:
        messages.error(request, f"OAuth error: {error}")
        return redirect("exact_oauth:status")

    if not code or not state:
        messages.error(request, "Missing authorization code or state")
        return redirect("exact_oauth:status")

    try:
        # Find the auth state (user agnostic)
        auth_state = ExactOnlineAuthState.objects.get(state=state, is_used=False)
        if not auth_state.is_valid():
            messages.error(request, "OAuth state expired")
            return redirect("exact_oauth:status")

        auth_state.is_used = True
        auth_state.save()

        config = get_exact_config()

        # Exchange code for token
        token_data = {
            "grant_type": "authorization_code",
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "code": code,
            "redirect_uri": config["redirect_uri"],
        }

        base_url = get_auth_base_url(config["country"])
        response = requests.post(f"{base_url}/api/oauth2/token", data=token_data)

        if response.status_code == 200:
            token_response = response.json()

            token, created = ExactOnlineToken.objects.get_or_create(
                session_key=auth_state.session_key
            )
            token.set_token_data(token_response)

            messages.success(request, "Successfully authorized!")
            return redirect("exact_oauth:status")
        else:
            messages.error(request, f"Failed to get token: {response.text}")

    except ExactOnlineAuthState.DoesNotExist:
        messages.error(request, "Invalid OAuth state")
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")

    return redirect("exact_oauth:status")


def status(request):
    """Show authorization status and token info"""
    config = get_exact_config()

    # Check if app is configured
    configured = bool(config["client_id"] and config["client_secret"])

    # Get session's token
    session_key = get_session_key(request)
    try:
        token = ExactOnlineToken.objects.get(session_key=session_key)
        has_token = True
        is_expired = token.is_expired()
        expires_soon = token.expires_soon()
    except ExactOnlineToken.DoesNotExist:
        token = None
        has_token = False
        is_expired = True
        expires_soon = False

    context = {
        "configured": configured,
        "config": config,
        "has_token": has_token,
        "token": token,
        "is_expired": is_expired,
        "expires_soon": expires_soon,
    }

    return render(request, "exact_oauth/status.html", context)


def refresh_token(request):
    """Refresh the OAuth token"""
    session_key = get_session_key(request)
    try:
        token = ExactOnlineToken.objects.get(session_key=session_key)
        config = get_exact_config()

        refresh_data = {
            "grant_type": "refresh_token",
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "refresh_token": token.refresh_token,
        }

        base_url = get_auth_base_url(config["country"])
        response = requests.post(f"{base_url}/api/oauth2/token", data=refresh_data)

        if response.status_code == 200:
            token_response = response.json()
            token.set_token_data(token_response)
            messages.success(request, "Token refreshed!")
        else:
            messages.error(request, f"Failed to refresh token: {response.text}")

    except ExactOnlineToken.DoesNotExist:
        messages.error(request, "No token to refresh")
    except Exception as e:
        messages.error(request, f"Error refreshing token: {str(e)}")

    return redirect("exact_oauth:status")


def revoke(request):
    """Revoke OAuth authorization"""
    if request.method == "POST":
        session_key = get_session_key(request)
        try:
            token = ExactOnlineToken.objects.get(session_key=session_key)
            token.delete()
            messages.success(request, "Authorization revoked")
        except ExactOnlineToken.DoesNotExist:
            messages.error(request, "No authorization to revoke")

    return redirect("exact_oauth:status")


def test_api(request):
    """Test API call"""
    session_key = get_session_key(request)

    # Check if token exists
    try:
        token = ExactOnlineToken.objects.get(session_key=session_key)
        if token.is_expired():
            return JsonResponse(
                {
                    "status": "error",
                    "message": "Token expired. Please authorize first.",
                },
                status=401,
            )
    except ExactOnlineToken.DoesNotExist:
        return JsonResponse(
            {"status": "error", "message": "No token found. Please authorize first."},
            status=404,
        )

    # Make API call and return consistent JSON response
    try:
        service = ExactOnlineService(session_key)
        response = service.get("system/Me")

        if response.status_code == 200:
            try:
                data = response.json()
                return JsonResponse({"status": "success", "data": data})
            except ValueError:
                return JsonResponse({"status": "success", "data": response.text})
        else:
            return JsonResponse(
                {
                    "status": "error",
                    "message": f"API returned {response.status_code}: {response.text}",
                },
                status=response.status_code,
            )
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

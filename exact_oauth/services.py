from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import requests
import json

from .models import ExactOnlineToken, get_exact_config, get_auth_base_url


class ExactOnlineService:
    def __init__(self, session_key):
        self.session_key = session_key
        self.config = get_exact_config()
        self.base_url = get_auth_base_url(
            self.config["country"]
        )  # https://start.exactonline.nl
        self.token = self._get_or_refresh_token()

    def _get_or_refresh_token(self):
        try:
            token = ExactOnlineToken.objects.get(session_key=self.session_key)
            return token.ensure_valid_token()
        except ExactOnlineToken.DoesNotExist:
            raise ValueError("No valid token found. Please authorize first.")

    def _handle_auth_error_and_retry(self, url, request_method, **request_kwargs):
        """Handle authentication errors by refreshing token and retrying the request"""
        print(f"DEBUG - Got auth error in {request_method}(), attempting token refresh")
        try:
            self.token.refresh_access_token()
            headers = request_kwargs.get("headers", {})
            headers["Authorization"] = (
                f"{self.token.token_type} {self.token.access_token}"
            )
            request_kwargs["headers"] = headers
            response = getattr(requests, request_method)(url, **request_kwargs)
            print(f"DEBUG - Retry response status: {response.status_code}")
            return response
        except ValueError as e:
            print(f"DEBUG - Token refresh failed: {e}")
            # If refresh fails, return None to indicate retry failed
            return None

    def _ensure_user_info(self):
        self._get_or_refresh_token()

        if not self.token.current_division:
            me_url = f"{self.base_url}/api/v1/current/Me"
            headers = {
                "Authorization": f"{self.token.token_type} {self.token.access_token}",
                "Accept": "application/json",
            }
            response = requests.get(me_url, headers=headers)

            # Handle authentication failures by refreshing token and retrying
            if response.status_code == 401 or response.status_code == 404:
                retry_response = self._handle_auth_error_and_retry(
                    me_url, "get", headers=headers
                )
                if retry_response is not None:
                    response = retry_response

            if response.status_code == 200:
                me_data = response.json()
                if me_data.get("d", {}).get("results"):
                    user_info = me_data["d"]["results"][0]
                    self.token.current_division = user_info.get("CurrentDivision")
                    self.token.save()
            else:
                raise ValueError(f"Failed to get user info: {response.text}")

    def get(self, endpoint, params=None):
        self._ensure_user_info()

        url = f"{self.base_url}/api/v1/{self.token.current_division}/{endpoint}"
        print(f"DOING get with url: {url}")

        headers = {
            "Authorization": f"{self.token.token_type} {self.token.access_token}",
            "Accept": "application/json",
        }
        request_kwargs = {"headers": headers, "params": params}
        response = getattr(requests, "get")(url, **request_kwargs)

        # Handle authentication failures by refreshing token and retrying
        if response.status_code == 401 or response.status_code == 404:
            retry_response = self._handle_auth_error_and_retry(
                url, "get", **request_kwargs
            )
            if retry_response is not None:
                response = retry_response

        if response.status_code == 200:
            print(f"RESPONSE: succesfull")
        else:
            print(f"ERROR RESPONSE: {response.text}")

        return response


# Simple helper functions
def get_service(session_key):
    """Get an ExactOnlineService instance for the session"""
    return ExactOnlineService(session_key)

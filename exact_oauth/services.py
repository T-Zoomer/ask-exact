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

            # Only refresh if token is actually expired, not just expires soon
            if token.is_expired():
                self._refresh_token(token)

            return token
        except ExactOnlineToken.DoesNotExist:
            raise ValueError("No valid token found. Please authorize first.")

    def _refresh_token(self, token):
        print("DEBUG - _refresh_token called")
        refresh_data = {
            "grant_type": "refresh_token",
            "client_id": self.config["client_id"],
            "client_secret": self.config["client_secret"],
            "refresh_token": token.refresh_token,
        }

        print(f"BASE: {self.base_url}")
        try:
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            token_url = f"{self.base_url}/oauth2/token"
            response = requests.post(token_url, data=refresh_data, headers=headers)
            print(f"DEBUG - _refresh_token response status: {response.status_code}")
            print(f"DEBUG - _refresh_token response text: {response.text}")

            if response.status_code == 200:
                token_response = response.json()
                token.set_token_data(token_response)
                # Reload the token instance to get the updated data
                token.refresh_from_db()
            elif response.status_code == 400:
                # Refresh token is likely expired or invalid
                token.delete()
                raise ValueError(
                    "Refresh token expired or invalid. Please reauthorize."
                )
            else:
                raise ValueError(
                    f"Failed to refresh token (HTTP {response.status_code}): {response.text}"
                )
        except requests.RequestException as e:
            raise ValueError(f"Network error during token refresh: {str(e)}")

    def _ensure_user_info(self):
        print("DEBUG - _ensure_user_info called")
        if not self.token.current_division:
            me_url = f"{self.base_url}/api/v1/current/Me"
            headers = {
                "Authorization": f"{self.token.token_type} {self.token.access_token}",
                "Accept": "application/json",
            }

            print(f"DEBUG - Making request to: {me_url}")
            response = requests.get(me_url, headers=headers)
            print(f"DEBUG - _ensure_user_info response status: {response.status_code}")
            print(f"DEBUG - _ensure_user_info response text: {response.text}")

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

        print(f"DEBUG - headers: {headers}")

        request_kwargs = {"headers": headers, "params": params}

        response = getattr(requests, "get")(url, **request_kwargs)

        print(f"RESPONSE STATUS code: {response.status_code}")

        print(f"RESPONSE: {response.json()}")

        if response.status_code == 401:
            # Only retry with refresh if token is actually expired
            if self.token.is_expired():
                self._refresh_token(self.token)
                headers["Authorization"] = (
                    f"{self.token.token_type} {self.token.access_token}"
                )
                request_kwargs["headers"] = headers
                response = getattr(requests, "get")(url, **request_kwargs)
            else:
                print("Token not expired but getting 401 - might be permissions issue")
                pass

        return response

    def get_accounts(self, top=100, skip=0):
        params = {"$top": top, "$skip": skip}
        response = self.get("crm/Accounts", params=params)
        return response.json() if response.status_code == 200 else None

    def get_items(self, top=100, skip=0):
        params = {"$top": top, "$skip": skip}
        response = self.get("logistics/Items", params=params)
        return response.json() if response.status_code == 200 else None

    def get_sales_invoices(self, top=100, skip=0):
        params = {"$top": top, "$skip": skip}
        response = self.get("salesinvoice/SalesInvoices", params=params)
        return response.json() if response.status_code == 200 else None

    def get_divisions(self):
        response = self.get("system/Divisions")
        return response.json() if response.status_code == 200 else None

    def get_me(self):
        response = self.get("system/Me")
        return response.json() if response.status_code == 200 else None

    def get_profit_loss_overview(
        self,
        current_year=None,
        current_period=None,
        previous_year=None,
        previous_year_period=None,
        currency_code=None,
    ):
        params = {}
        if current_year:
            params["CurrentYear"] = current_year
        if current_period:
            params["CurrentPeriod"] = current_period
        if previous_year:
            params["PreviousYear"] = previous_year
        if previous_year_period:
            params["PreviousYearPeriod"] = previous_year_period
        if currency_code:
            params["CurrencyCode"] = currency_code

        response = self.get("read/financial/ProfitLossOverview", params=params)
        return response.json() if response.status_code == 200 else None


# Simple helper functions
def get_service(session_key):
    """Get an ExactOnlineService instance for the session"""
    return ExactOnlineService(session_key)

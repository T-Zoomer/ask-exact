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
        self.token = self._get_or_refresh_token()
    
    def _get_or_refresh_token(self):
        try:
            token = ExactOnlineToken.objects.get(session_key=self.session_key)
            
            if token.expires_soon():
                self._refresh_token(token)
            
            return token
        except ExactOnlineToken.DoesNotExist:
            raise ValueError("No valid token found. Please authorize first.")
    
    def _refresh_token(self, token):
        refresh_data = {
            'grant_type': 'refresh_token',
            'client_id': self.config['client_id'],
            'client_secret': self.config['client_secret'],
            'refresh_token': token.refresh_token
        }
        
        base_url = get_auth_base_url(self.config['country'])
        response = requests.post(f"{base_url}/api/oauth2/token", data=refresh_data)
        
        if response.status_code == 200:
            token_response = response.json()
            token.set_token_data(token_response)
        else:
            raise ValueError(f"Failed to refresh token: {response.text}")
    
    def _ensure_user_info(self):
        if not self.token.base_server_uri or not self.token.division:
            country_suffix = '.nl' if self.config['country'] == 'NL' else '.com'
            me_url = f"https://start.exactonline{country_suffix}/api/v1/current/Me"
            headers = {'Authorization': f'{self.token.token_type} {self.token.access_token}'}
            
            response = requests.get(me_url, headers=headers)
            
            if response.status_code == 200:
                me_data = response.json()
                if me_data.get('d', {}).get('results'):
                    user_info = me_data['d']['results'][0]
                    self.token.base_server_uri = user_info.get('CurrentDivision')
                    self.token.division = user_info.get('Division')
                    self.token.save()
            else:
                raise ValueError(f"Failed to get user info: {response.text}")
    
    def make_request(self, endpoint, method='GET', data=None, params=None):
        self._ensure_user_info()
        
        if not self.token.base_server_uri:
            raise ValueError("Could not determine base server URI")
        
        url = f"{self.token.base_server_uri}/api/v1/{self.token.division}/{endpoint}"
        headers = {'Authorization': f'{self.token.token_type} {self.token.access_token}'}
        
        if method.upper() in ['POST', 'PUT']:
            headers['Content-Type'] = 'application/json'
        
        request_kwargs = {
            'headers': headers,
            'params': params
        }
        
        if data and method.upper() in ['POST', 'PUT']:
            request_kwargs['json'] = data
        
        response = getattr(requests, method.lower())(url, **request_kwargs)
        
        if response.status_code == 401:
            self._refresh_token(self.token)
            headers['Authorization'] = f'{self.token.token_type} {self.token.access_token}'
            request_kwargs['headers'] = headers
            response = getattr(requests, method.lower())(url, **request_kwargs)
        
        return response
    
    def get(self, endpoint, params=None):
        return self.make_request(endpoint, 'GET', params=params)
    
    def post(self, endpoint, data):
        return self.make_request(endpoint, 'POST', data=data)
    
    def put(self, endpoint, data):
        return self.make_request(endpoint, 'PUT', data=data)
    
    def delete(self, endpoint):
        return self.make_request(endpoint, 'DELETE')
    
    def get_accounts(self, top=100, skip=0):
        params = {'$top': top, '$skip': skip}
        response = self.get('crm/Accounts', params=params)
        return response.json() if response.status_code == 200 else None
    
    def get_items(self, top=100, skip=0):
        params = {'$top': top, '$skip': skip}
        response = self.get('logistics/Items', params=params)
        return response.json() if response.status_code == 200 else None
    
    def get_sales_invoices(self, top=100, skip=0):
        params = {'$top': top, '$skip': skip}
        response = self.get('salesinvoice/SalesInvoices', params=params)
        return response.json() if response.status_code == 200 else None
    
    def create_account(self, account_data):
        response = self.post('crm/Accounts', account_data)
        return response.json() if response.status_code == 201 else None
    
    def get_divisions(self):
        response = self.get('system/Divisions')
        return response.json() if response.status_code == 200 else None
    
    def get_me(self):
        response = self.get('system/Me')
        return response.json() if response.status_code == 200 else None


# Simple helper functions
def get_service(session_key):
    """Get an ExactOnlineService instance for the session"""
    return ExactOnlineService(session_key)
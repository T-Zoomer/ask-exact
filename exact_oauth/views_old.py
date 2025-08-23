from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
import requests
import secrets
import json
import urllib.parse

from .models import ExactOnlineToken, ExactOnlineAuthState, get_exact_config, get_auth_base_url


@login_required
def authorize_app(request):
    config = get_exact_config()
    
    # Validate config
    if not config['client_id'] or not config['client_secret']:
        messages.error(request, 'Exact Online app not configured. Please set EXACT_CLIENT_ID and EXACT_CLIENT_SECRET environment variables.')
        return redirect('exact_oauth:app_list')
    
    state = secrets.token_urlsafe(32)
    ExactOnlineAuthState.objects.create(
        user=request.user,
        state=state
    )
    
    auth_params = {
        'client_id': config['client_id'],
        'redirect_uri': config['redirect_uri'],
        'response_type': 'code',
        'state': state,
        'force_login': '0'
    }
    
    base_url = get_auth_base_url(config['country'])
    auth_url = f"{base_url}/api/oauth2/auth?" + urllib.parse.urlencode(auth_params)
    
    return redirect(auth_url)


@login_required 
def oauth_callback(request):
    code = request.GET.get('code')
    state = request.GET.get('state')
    error = request.GET.get('error')
    
    if error:
        messages.error(request, f'OAuth error: {error}')
        return redirect('exact_oauth:app_list')
    
    if not code or not state:
        messages.error(request, 'Missing authorization code or state parameter')
        return redirect('exact_oauth:app_list')
    
    try:
        auth_state = ExactOnlineAuthState.objects.get(state=state, user=request.user, is_used=False)
        if not auth_state.is_valid():
            messages.error(request, 'OAuth state expired or invalid')
            return redirect('exact_oauth:app_list')
        
        auth_state.is_used = True
        auth_state.save()
        
        config = get_exact_config()
        
        token_data = {
            'grant_type': 'authorization_code',
            'client_id': config['client_id'],
            'client_secret': config['client_secret'],
            'code': code,
            'redirect_uri': config['redirect_uri']
        }
        
        base_url = get_auth_base_url(config['country'])
        token_url = f"{base_url}/api/oauth2/token"
        response = requests.post(token_url, data=token_data)
        
        if response.status_code == 200:
            token_response = response.json()
            
            token, created = ExactOnlineToken.objects.get_or_create(
                user=request.user,
                defaults={}
            )
            token.set_token_data(token_response)
            
            messages.success(request, 'Successfully authorized Exact Online!')
            return redirect('exact_oauth:token_detail')
        else:
            messages.error(request, f'Failed to exchange code for token: {response.text}')
            return redirect('exact_oauth:app_list')
            
    except ExactOnlineAuthState.DoesNotExist:
        messages.error(request, 'Invalid OAuth state')
        return redirect('exact_oauth:app_list')
    except Exception as e:
        messages.error(request, f'OAuth callback error: {str(e)}')
        return redirect('exact_oauth:app_list')


@login_required
def app_list(request):
    apps = ExactOnlineApp.objects.filter(is_active=True)
    user_tokens = ExactOnlineToken.objects.filter(user=request.user).select_related('app')
    
    app_status = {}
    for token in user_tokens:
        app_status[token.app.id] = {
            'authorized': True,
            'expired': token.is_expired(),
            'token': token
        }
    
    context = {
        'apps': apps,
        'app_status': app_status
    }
    return render(request, 'exact_oauth/app_list.html', context)


@login_required
def token_detail(request, token_id):
    token = get_object_or_404(ExactOnlineToken, id=token_id, user=request.user)
    
    context = {
        'token': token,
        'is_expired': token.is_expired(),
        'expires_soon': token.expires_soon()
    }
    return render(request, 'exact_oauth/token_detail.html', context)


@login_required
def refresh_token_view(request, token_id):
    token = get_object_or_404(ExactOnlineToken, id=token_id, user=request.user)
    
    try:
        refresh_data = {
            'grant_type': 'refresh_token',
            'client_id': token.app.client_id,
            'client_secret': token.app.client_secret,
            'refresh_token': token.refresh_token
        }
        
        token_url = f"{token.app.auth_base_url}/api/oauth2/token"
        response = requests.post(token_url, data=refresh_data)
        
        if response.status_code == 200:
            token_response = response.json()
            token.set_token_data(token_response)
            messages.success(request, 'Token refreshed successfully!')
        else:
            messages.error(request, f'Failed to refresh token: {response.text}')
            
    except Exception as e:
        messages.error(request, f'Error refreshing token: {str(e)}')
    
    return redirect('exact_oauth:token_detail', token_id=token.id)


@login_required
def revoke_token(request, token_id):
    token = get_object_or_404(ExactOnlineToken, id=token_id, user=request.user)
    
    if request.method == 'POST':
        app_name = token.app.name
        token.delete()
        messages.success(request, f'Authorization for {app_name} has been revoked.')
        return redirect('exact_oauth:app_list')
    
    context = {'token': token}
    return render(request, 'exact_oauth/revoke_token.html', context)


class ExactAPIView(View):
    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)
    
    def get_token(self, app_id):
        try:
            app = ExactOnlineApp.objects.get(id=app_id, is_active=True)
            token = ExactOnlineToken.objects.get(user=self.request.user, app=app)
            
            if token.expires_soon():
                self._refresh_token(token)
            
            return token
        except (ExactOnlineApp.DoesNotExist, ExactOnlineToken.DoesNotExist):
            return None
    
    def _refresh_token(self, token):
        refresh_data = {
            'grant_type': 'refresh_token',
            'client_id': token.app.client_id,
            'client_secret': token.app.client_secret,
            'refresh_token': token.refresh_token
        }
        
        token_url = f"{token.app.auth_base_url}/api/oauth2/token"
        response = requests.post(token_url, data=refresh_data)
        
        if response.status_code == 200:
            token_response = response.json()
            token.set_token_data(token_response)
    
    def make_api_request(self, token, endpoint, method='GET', data=None):
        if not token.base_server_uri:
            me_url = f"https://start.exactonline{'.nl' if token.app.country == 'NL' else '.com'}/api/v1/current/Me"
            headers = {'Authorization': f'{token.token_type} {token.access_token}'}
            me_response = requests.get(me_url, headers=headers)
            
            if me_response.status_code == 200:
                me_data = me_response.json()
                if me_data.get('d', {}).get('results'):
                    user_info = me_data['d']['results'][0]
                    token.base_server_uri = user_info.get('CurrentDivision')
                    token.division = user_info.get('Division')
                    token.save()
        
        if not token.base_server_uri:
            return None
        
        url = f"{token.base_server_uri}/api/v1/{token.division}/{endpoint}"
        headers = {'Authorization': f'{token.token_type} {token.access_token}'}
        
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers)
        elif method.upper() == 'POST':
            headers['Content-Type'] = 'application/json'
            response = requests.post(url, headers=headers, json=data)
        elif method.upper() == 'PUT':
            headers['Content-Type'] = 'application/json'
            response = requests.put(url, headers=headers, json=data)
        elif method.upper() == 'DELETE':
            response = requests.delete(url, headers=headers)
        else:
            return None
        
        return response

from django.db import models
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
import os


def get_exact_config():
    """Get Exact Online configuration from settings or environment"""
    config = getattr(settings, 'EXACT_OAUTH_SETTINGS', {})
    
    return {
        'client_id': config.get('CLIENT_ID') or os.getenv('EXACT_CLIENT_ID'),
        'client_secret': config.get('CLIENT_SECRET') or os.getenv('EXACT_CLIENT_SECRET'),
        'country': config.get('COUNTRY', os.getenv('EXACT_COUNTRY', 'NL')),
        'redirect_uri': config.get('REDIRECT_URI', os.getenv('EXACT_REDIRECT_URI', 'http://127.0.0.1:8000/oauth/callback/')),
    }


def get_auth_base_url(country='NL'):
    """Get the auth base URL for a country"""
    country_urls = {
        'NL': 'https://start.exactonline.nl',
        'BE': 'https://start.exactonline.be',
        'UK': 'https://start.exactonline.co.uk',
        'FR': 'https://start.exactonline.fr',
        'DE': 'https://start.exactonline.de',
        'US': 'https://start.exactonline.com',
    }
    return country_urls.get(country.upper(), country_urls['NL'])


class ExactOnlineToken(models.Model):
    session_key = models.CharField(max_length=40, unique=True, null=True)
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_type = models.CharField(max_length=50, default='Bearer')
    expires_at = models.DateTimeField(null=True)
    division = models.IntegerField(null=True, blank=True)
    base_server_uri = models.URLField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Exact Online Token"
        verbose_name_plural = "Exact Online Tokens"
    
    def __str__(self):
        return f"Token for session {self.session_key}"
    
    def is_expired(self):
        return timezone.now() >= self.expires_at
    
    def expires_soon(self, minutes=5):
        return timezone.now() + timedelta(minutes=minutes) >= self.expires_at
    
    def set_token_data(self, token_data):
        self.access_token = token_data.get('access_token', '')
        self.refresh_token = token_data.get('refresh_token', '')
        self.token_type = token_data.get('token_type', 'Bearer')
        
        expires_in = token_data.get('expires_in', 600)  # Default 10 minutes
        self.expires_at = timezone.now() + timedelta(seconds=int(expires_in))
        
        self.save()


class ExactOnlineAuthState(models.Model):
    session_key = models.CharField(max_length=40, null=True)
    state = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)
    
    class Meta:
        verbose_name = "OAuth State"
        verbose_name_plural = "OAuth States"
    
    def __str__(self):
        return f"OAuth state for session {self.session_key}"
    
    def is_valid(self, max_age_minutes=10):
        age = timezone.now() - self.created_at
        return not self.is_used and age.total_seconds() <= max_age_minutes * 60

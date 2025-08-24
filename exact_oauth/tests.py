from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.sessions.models import Session
from unittest.mock import patch, Mock, MagicMock
from datetime import timedelta
import json
import secrets

from .models import (
    ExactOnlineToken, 
    ExactOnlineAuthState, 
    get_exact_config, 
    get_auth_base_url
)
from .services import ExactOnlineService, get_service
from .views import get_session_key


class ConfigTest(TestCase):
    @override_settings(EXACT_OAUTH_SETTINGS={
        'CLIENT_ID': 'test_client_id',
        'CLIENT_SECRET': 'test_client_secret',
        'COUNTRY': 'NL',
        'REDIRECT_URI': 'http://test.example.com/callback/'
    })
    def test_get_exact_config_from_settings(self):
        config = get_exact_config()
        self.assertEqual(config['client_id'], 'test_client_id')
        self.assertEqual(config['client_secret'], 'test_client_secret')
        self.assertEqual(config['country'], 'NL')
        self.assertEqual(config['redirect_uri'], 'http://test.example.com/callback/')

    @patch.dict('os.environ', {
        'EXACT_CLIENT_ID': 'env_client_id',
        'EXACT_CLIENT_SECRET': 'env_client_secret',
        'EXACT_COUNTRY': 'BE',
        'EXACT_REDIRECT_URI': 'http://env.example.com/callback/'
    })
    def test_get_exact_config_from_env(self):
        config = get_exact_config()
        self.assertEqual(config['client_id'], 'env_client_id')
        self.assertEqual(config['client_secret'], 'env_client_secret')
        self.assertEqual(config['country'], 'BE')
        self.assertEqual(config['redirect_uri'], 'http://env.example.com/callback/')

    def test_get_auth_base_url(self):
        self.assertEqual(get_auth_base_url('NL'), 'https://start.exactonline.nl')
        self.assertEqual(get_auth_base_url('BE'), 'https://start.exactonline.be')
        self.assertEqual(get_auth_base_url('UK'), 'https://start.exactonline.co.uk')
        self.assertEqual(get_auth_base_url('FR'), 'https://start.exactonline.fr')
        self.assertEqual(get_auth_base_url('DE'), 'https://start.exactonline.de')
        self.assertEqual(get_auth_base_url('US'), 'https://start.exactonline.com')
        # Test default fallback
        self.assertEqual(get_auth_base_url('UNKNOWN'), 'https://start.exactonline.nl')


class ExactOnlineTokenTest(TestCase):
    def setUp(self):
        self.session_key = 'test_session_123'
        self.token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_in': 600
        }

    def test_create_token(self):
        token = ExactOnlineToken.objects.create(
            session_key=self.session_key,
            access_token='test_token',
            refresh_token='test_refresh',
            current_division=123456
        )
        self.assertEqual(token.session_key, self.session_key)
        self.assertEqual(token.access_token, 'test_token')
        self.assertEqual(token.current_division, 123456)

    def test_is_expired(self):
        # Create token that expires in past
        past_time = timezone.now() - timedelta(minutes=10)
        token = ExactOnlineToken.objects.create(
            session_key=self.session_key,
            access_token='test_token',
            refresh_token='test_refresh',
            expires_at=past_time
        )
        self.assertTrue(token.is_expired())

        # Create token that expires in future
        future_time = timezone.now() + timedelta(minutes=10)
        token.expires_at = future_time
        token.save()
        self.assertFalse(token.is_expired())

    def test_expires_soon(self):
        # Token expires in 3 minutes (less than default 5)
        near_future = timezone.now() + timedelta(minutes=3)
        token = ExactOnlineToken.objects.create(
            session_key=self.session_key,
            access_token='test_token',
            refresh_token='test_refresh',
            expires_at=near_future
        )
        self.assertTrue(token.expires_soon())

        # Token expires in 10 minutes (more than default 5)
        far_future = timezone.now() + timedelta(minutes=10)
        token.expires_at = far_future
        token.save()
        self.assertFalse(token.expires_soon())

    def test_set_token_data(self):
        token = ExactOnlineToken.objects.create(session_key=self.session_key)
        token.set_token_data(self.token_data)
        
        self.assertEqual(token.access_token, 'test_access_token')
        self.assertEqual(token.refresh_token, 'test_refresh_token')
        self.assertEqual(token.token_type, 'Bearer')
        self.assertIsNotNone(token.expires_at)
        
        # Check that expires_at is approximately 600 seconds from now
        expected_expiry = timezone.now() + timedelta(seconds=600)
        self.assertAlmostEqual(
            token.expires_at.timestamp(), 
            expected_expiry.timestamp(), 
            delta=5
        )

    @patch('exact_oauth.models.requests.post')
    @patch('exact_oauth.models.get_exact_config')
    def test_refresh_access_token_success(self, mock_config, mock_post):
        # Setup
        mock_config.return_value = {
            'client_id': 'test_id',
            'client_secret': 'test_secret',
            'country': 'NL'
        }
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'access_token': 'new_access_token',
            'refresh_token': 'new_refresh_token',
            'token_type': 'Bearer',
            'expires_in': 3600
        }
        mock_post.return_value = mock_response

        token = ExactOnlineToken.objects.create(
            session_key=self.session_key,
            refresh_token='old_refresh_token'
        )
        
        result = token.refresh_access_token()
        
        self.assertTrue(result)
        self.assertEqual(token.access_token, 'new_access_token')
        self.assertEqual(token.refresh_token, 'new_refresh_token')

    @patch('exact_oauth.models.requests.post')
    @patch('exact_oauth.models.get_exact_config')
    def test_refresh_access_token_expired(self, mock_config, mock_post):
        mock_config.return_value = {
            'client_id': 'test_id',
            'client_secret': 'test_secret',
            'country': 'NL'
        }
        mock_response = Mock()
        mock_response.status_code = 400
        mock_post.return_value = mock_response

        token = ExactOnlineToken.objects.create(
            session_key=self.session_key,
            refresh_token='expired_refresh_token'
        )
        
        with self.assertRaises(ValueError) as cm:
            token.refresh_access_token()
        
        self.assertIn('Refresh token expired', str(cm.exception))

    def test_ensure_valid_token_expired(self):
        # Create expired token
        past_time = timezone.now() - timedelta(minutes=10)
        token = ExactOnlineToken.objects.create(
            session_key=self.session_key,
            expires_at=past_time
        )
        
        with patch.object(token, 'refresh_access_token') as mock_refresh:
            token.ensure_valid_token()
            mock_refresh.assert_called_once()

    def test_ensure_valid_token_valid(self):
        # Create valid token
        future_time = timezone.now() + timedelta(minutes=10)
        token = ExactOnlineToken.objects.create(
            session_key=self.session_key,
            expires_at=future_time
        )
        
        with patch.object(token, 'refresh_access_token') as mock_refresh:
            result = token.ensure_valid_token()
            mock_refresh.assert_not_called()
            self.assertEqual(result, token)


class ExactOnlineAuthStateTest(TestCase):
    def setUp(self):
        self.session_key = 'test_session_123'
        self.state = 'test_state_xyz'

    def test_create_auth_state(self):
        auth_state = ExactOnlineAuthState.objects.create(
            session_key=self.session_key,
            state=self.state
        )
        self.assertEqual(auth_state.session_key, self.session_key)
        self.assertEqual(auth_state.state, self.state)
        self.assertFalse(auth_state.is_used)

    def test_is_valid_fresh_unused(self):
        auth_state = ExactOnlineAuthState.objects.create(
            session_key=self.session_key,
            state=self.state
        )
        self.assertTrue(auth_state.is_valid())

    def test_is_valid_used(self):
        auth_state = ExactOnlineAuthState.objects.create(
            session_key=self.session_key,
            state=self.state,
            is_used=True
        )
        self.assertFalse(auth_state.is_valid())

    def test_is_valid_expired(self):
        # Create auth state that's older than max age
        past_time = timezone.now() - timedelta(minutes=15)
        auth_state = ExactOnlineAuthState.objects.create(
            session_key=self.session_key,
            state=self.state
        )
        auth_state.created_at = past_time
        auth_state.save()
        
        self.assertFalse(auth_state.is_valid())


class ViewTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_get_session_key(self):
        # Mock request without session key
        request = Mock()
        request.session.session_key = None
        request.session.create = Mock()
        
        get_session_key(request)
        request.session.create.assert_called_once()

        # Mock request with existing session key
        request.session.session_key = 'existing_key'
        request.session.create = Mock()
        
        result = get_session_key(request)
        self.assertEqual(result, 'existing_key')
        request.session.create.assert_not_called()

    @override_settings(EXACT_OAUTH_SETTINGS={
        'CLIENT_ID': 'test_client_id',
        'CLIENT_SECRET': 'test_client_secret',
        'COUNTRY': 'NL',
        'REDIRECT_URI': 'http://test.example.com/callback/'
    })
    def test_status_configured(self):
        response = self.client.get(reverse('exact_oauth:status'))
        self.assertEqual(response.status_code, 200)
        # The client_id might not be displayed in the template for security
        # Instead, just check that it's configured
        self.assertIn('configured', response.context)
        self.assertTrue(response.context['configured'])
        self.assertContains(response, 'Configured')

    @override_settings(EXACT_OAUTH_SETTINGS={})
    @patch.dict('os.environ', {}, clear=True)
    def test_status_not_configured(self):
        response = self.client.get(reverse('exact_oauth:status'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('configured', response.context)
        self.assertFalse(response.context['configured'])

    @override_settings(EXACT_OAUTH_SETTINGS={})
    @patch.dict('os.environ', {}, clear=True)
    def test_authorize_not_configured(self):
        response = self.client.get(reverse('exact_oauth:authorize'))
        # Should redirect to status page when not configured
        self.assertRedirects(response, reverse('exact_oauth:status'))

    @override_settings(EXACT_OAUTH_SETTINGS={
        'CLIENT_ID': 'test_client_id',
        'CLIENT_SECRET': 'test_client_secret',
        'COUNTRY': 'NL',
        'REDIRECT_URI': 'http://test.example.com/callback/'
    })
    def test_authorize_configured(self):
        response = self.client.get(reverse('exact_oauth:authorize'))
        self.assertEqual(response.status_code, 302)
        
        # Check that auth state was created
        self.assertTrue(ExactOnlineAuthState.objects.filter(is_used=False).exists())
        
        # Check redirect URL contains expected parameters
        redirect_url = response.url
        self.assertIn('start.exactonline.nl', redirect_url)
        self.assertIn('client_id=test_client_id', redirect_url)
        self.assertIn('response_type=code', redirect_url)

    def test_callback_missing_params(self):
        # Test missing code
        response = self.client.get(reverse('exact_oauth:callback'), {'state': 'test_state'})
        self.assertEqual(response.status_code, 302)
        
        # Test missing state
        response = self.client.get(reverse('exact_oauth:callback'), {'code': 'test_code'})
        self.assertEqual(response.status_code, 302)

    def test_callback_error_param(self):
        response = self.client.get(reverse('exact_oauth:callback'), {
            'error': 'access_denied',
            'state': 'test_state'
        })
        self.assertEqual(response.status_code, 302)

    def test_callback_invalid_state(self):
        response = self.client.get(reverse('exact_oauth:callback'), {
            'code': 'test_code',
            'state': 'invalid_state'
        })
        self.assertEqual(response.status_code, 302)

    @override_settings(EXACT_OAUTH_SETTINGS={
        'CLIENT_ID': 'test_client_id',
        'CLIENT_SECRET': 'test_client_secret',
        'COUNTRY': 'NL',
        'REDIRECT_URI': 'http://test.example.com/callback/'
    })
    @patch('exact_oauth.views.requests.post')
    def test_callback_successful_token_exchange(self, mock_post):
        # Mock successful token response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'access_token': 'new_access_token',
            'refresh_token': 'new_refresh_token',
            'token_type': 'Bearer',
            'expires_in': 3600
        }
        mock_post.return_value = mock_response
        
        # Create auth state - get session key from client session
        session = self.client.session
        session.save()  # This creates the session and assigns a key
        session_key = session.session_key
        
        state = 'test_state_123'
        auth_state = ExactOnlineAuthState.objects.create(
            session_key=session_key,
            state=state
        )
        
        response = self.client.get(reverse('exact_oauth:callback'), {
            'code': 'test_code',
            'state': state
        })
        
        self.assertEqual(response.status_code, 302)
        
        # Check token was created
        self.assertTrue(ExactOnlineToken.objects.filter(session_key=session_key).exists())
        
        # Check auth state was marked as used
        auth_state.refresh_from_db()
        self.assertTrue(auth_state.is_used)

    def test_revoke_no_token(self):
        response = self.client.post(reverse('exact_oauth:revoke'))
        self.assertEqual(response.status_code, 302)

    def test_revoke_with_token(self):
        # Create token for session
        session_key = self.client.session.session_key or 'test_session'
        if not self.client.session.session_key:
            session = self.client.session
            session.create()
            session_key = session.session_key
            
        token = ExactOnlineToken.objects.create(
            session_key=session_key,
            access_token='test_token'
        )
        
        response = self.client.post(reverse('exact_oauth:revoke'))
        self.assertEqual(response.status_code, 302)
        
        # Check token was deleted
        self.assertFalse(ExactOnlineToken.objects.filter(id=token.id).exists())

    def test_test_api_no_token(self):
        response = self.client.get('/oauth/api/test/')  # Assuming this URL exists
        # Since test_api isn't in URLs, let's test the view function directly
        from .views import test_api
        
        request = Mock()
        request.session.session_key = 'test_session'
        
        with patch('exact_oauth.views.get_session_key', return_value='test_session'):
            response = test_api(request)
            
        response_data = json.loads(response.content)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response_data['status'], 'error')


class ExactOnlineServiceTest(TestCase):
    def setUp(self):
        self.session_key = 'test_session_123'
        # Create a valid token
        future_time = timezone.now() + timedelta(hours=1)
        self.token = ExactOnlineToken.objects.create(
            session_key=self.session_key,
            access_token='test_access_token',
            refresh_token='test_refresh_token',
            expires_at=future_time,
            current_division=123456
        )

    @patch('exact_oauth.services.get_exact_config')
    def test_service_initialization(self, mock_config):
        mock_config.return_value = {
            'client_id': 'test_id',
            'client_secret': 'test_secret',
            'country': 'NL'
        }
        
        service = ExactOnlineService(self.session_key)
        self.assertEqual(service.session_key, self.session_key)
        self.assertEqual(service.base_url, 'https://start.exactonline.nl')
        self.assertIsNotNone(service.token)

    def test_service_no_token(self):
        with self.assertRaises(ValueError) as cm:
            ExactOnlineService('non_existent_session')
        
        self.assertIn('No valid token found', str(cm.exception))

    @patch('exact_oauth.services.requests.get')
    @patch('exact_oauth.services.get_exact_config')
    def test_ensure_user_info_missing_division(self, mock_config, mock_get):
        mock_config.return_value = {
            'client_id': 'test_id',
            'client_secret': 'test_secret',
            'country': 'NL'
        }
        
        # Remove division from token
        self.token.current_division = None
        self.token.save()
        
        # Mock responses: first for Me API call, then for actual API call
        me_response = Mock()
        me_response.status_code = 200
        me_response.json.return_value = {
            'd': {
                'results': [{'CurrentDivision': 987654}]
            }
        }
        
        api_response = Mock()
        api_response.status_code = 200
        api_response.json.return_value = {'d': {'results': []}}
        
        # Configure mock to return different responses for different calls
        mock_get.side_effect = [me_response, api_response]
        
        service = ExactOnlineService(self.session_key)
        
        # Call get() method to trigger _ensure_user_info
        response = service.get('items/Items')
        
        # Check that current_division was set
        self.token.refresh_from_db()
        self.assertEqual(self.token.current_division, 987654)

    @patch('exact_oauth.services.requests.get')
    @patch('exact_oauth.services.get_exact_config')
    def test_get_api_call(self, mock_config, mock_get):
        mock_config.return_value = {
            'client_id': 'test_id',
            'client_secret': 'test_secret',
            'country': 'NL'
        }
        
        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'d': {'results': []}}
        mock_get.return_value = mock_response
        
        service = ExactOnlineService(self.session_key)
        response = service.get('items/Items')
        
        self.assertEqual(response.status_code, 200)
        mock_get.assert_called()

    def test_get_service_helper(self):
        with patch('exact_oauth.services.ExactOnlineService') as mock_service_class:
            mock_instance = Mock()
            mock_service_class.return_value = mock_instance
            
            result = get_service(self.session_key)
            
            mock_service_class.assert_called_once_with(self.session_key)
            self.assertEqual(result, mock_instance)

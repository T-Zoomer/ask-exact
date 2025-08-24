from django.test import TestCase, Client
from django.urls import reverse
from unittest.mock import Mock, patch
from exact_oauth.models import ExactOnlineToken
import json


class ApiForwarderTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.session.create()
        self.session_key = self.client.session.session_key

    def test_api_forwarder_no_session(self):
        """Test API forwarder without session returns 401"""
        client_no_session = Client()
        response = client_no_session.get(reverse('ask:api_forwarder', args=['test/endpoint']))
        
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], 'No session available')

    @patch('ask.views.get_service')
    def test_api_forwarder_success(self, mock_get_service):
        """Test successful API forwarding with system/Me endpoint"""
        mock_service = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'd': {
                'results': [{
                    'CurrentDivision': 123456,
                    'UserID': 'test-user-id',
                    'FullName': 'Test User'
                }]
            }
        }
        mock_service.get.return_value = mock_response
        mock_get_service.return_value = mock_service

        response = self.client.get(reverse('ask:api_forwarder', args=['system/Me']))
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn('d', response_data)
        self.assertIn('results', response_data['d'])
        mock_service.get.assert_called_once_with('system/Me', params={})

    @patch('ask.views.get_service')
    def test_api_forwarder_items_with_filters(self, mock_get_service):
        """Test API forwarding with Items endpoint and query parameters"""
        mock_service = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'd': {
                'results': [{
                    'ID': 'item-123',
                    'Code': 'ITEM001',
                    'Description': 'Test Item',
                    'IsSalesItem': True
                }]
            }
        }
        mock_service.get.return_value = mock_response
        mock_get_service.return_value = mock_service

        response = self.client.get(
            reverse('ask:api_forwarder', args=['logistics/Items']) + 
            '?$filter=IsSalesItem eq true&$select=ID,Code,Description'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn('d', response_data)
        self.assertIn('results', response_data['d'])
        mock_service.get.assert_called_once_with(
            'logistics/Items', 
            params={
                '$filter': 'IsSalesItem eq true',
                '$select': 'ID,Code,Description'
            }
        )

    @patch('ask.views.get_service')
    def test_api_forwarder_accounts_endpoint(self, mock_get_service):
        """Test API forwarding with Accounts endpoint"""
        mock_service = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'd': {
                'results': [{
                    'ID': 'account-123',
                    'Code': 'CUST001',
                    'Name': 'Test Customer',
                    'Status': 'C'
                }]
            }
        }
        mock_service.get.return_value = mock_response
        mock_get_service.return_value = mock_service

        response = self.client.get(reverse('ask:api_forwarder', args=['crm/Accounts']))
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn('d', response_data)
        self.assertEqual(len(response_data['d']['results']), 1)
        self.assertEqual(response_data['d']['results'][0]['Code'], 'CUST001')
        mock_service.get.assert_called_once_with('crm/Accounts', params={})

    @patch('ask.views.get_service')
    def test_api_forwarder_api_error(self, mock_get_service):
        """Test API forwarder when Exact API returns error"""
        mock_service = Mock()
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = 'Endpoint not found'
        mock_service.get.return_value = mock_response
        mock_get_service.return_value = mock_service

        response = self.client.get(reverse('ask:api_forwarder', args=['nonexistent/endpoint']))
        
        self.assertEqual(response.status_code, 404)
        response_data = response.json()
        self.assertEqual(response_data['error'], 'Exact API returned status 404')
        self.assertEqual(response_data['details'], 'Endpoint not found')

    @patch('ask.views.get_service')
    def test_api_forwarder_service_exception(self, mock_get_service):
        """Test API forwarder when service raises ValueError"""
        mock_get_service.side_effect = ValueError('No valid token found')

        response = self.client.get(reverse('ask:api_forwarder', args=['test/endpoint']))
        
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'No valid token found')

    @patch('ask.views.get_service')
    def test_api_forwarder_general_exception(self, mock_get_service):
        """Test API forwarder when unexpected exception occurs"""
        mock_get_service.side_effect = Exception('Unexpected error')

        response = self.client.get(reverse('ask:api_forwarder', args=['test/endpoint']))
        
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['error'], 'Internal server error')

    def test_api_forwarder_post_method_not_allowed(self):
        """Test that POST method is not allowed on API forwarder"""
        response = self.client.post(reverse('ask:api_forwarder', args=['system/Me']))
        
        self.assertEqual(response.status_code, 405)

    @patch('ask.views.get_service')
    def test_api_forwarder_sales_invoices(self, mock_get_service):
        """Test API forwarding with SalesInvoices endpoint"""
        mock_service = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'd': {
                'results': [{
                    'InvoiceID': 'inv-123',
                    'InvoiceNumber': 2024001,
                    'OrderedBy': 'customer-123',
                    'AmountFC': 1000.00,
                    'Status': 20
                }]
            }
        }
        mock_service.get.return_value = mock_response
        mock_get_service.return_value = mock_service

        response = self.client.get(
            reverse('ask:api_forwarder', args=['salesinvoice/SalesInvoices']) +
            '?$filter=Status eq 20&$orderby=InvoiceNumber desc'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn('d', response_data)
        self.assertEqual(response_data['d']['results'][0]['Status'], 20)
        mock_service.get.assert_called_once_with(
            'salesinvoice/SalesInvoices',
            params={
                '$filter': 'Status eq 20',
                '$orderby': 'InvoiceNumber desc'
            }
        )

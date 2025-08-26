from django.test import TestCase, Client
from django.urls import reverse
from unittest.mock import Mock, patch, MagicMock
from exact_oauth.models import ExactOnlineToken
import json
import os
from .openai_mcp_client import exact_toolbox


class ToolRegistryTestCase(TestCase):
    """Test the tool registry functionality."""

    def test_tool_generation(self):
        """Test that tools are generated correctly from config."""
        tools = exact_toolbox.get_openai_tools()

        # Should have discovery tools + API endpoint tools
        self.assertGreater(len(tools), 65)  # At least 67 endpoints + 2 discovery tools

        # Check that all tools have required structure
        for tool in tools:
            self.assertEqual(tool["type"], "function")
            self.assertIn("function", tool)
            self.assertIn("name", tool["function"])
            self.assertIn("description", tool["function"])
            self.assertIn("parameters", tool["function"])

    def test_discovery_tools(self):
        """Test discovery tool functionality."""
        # Test list_available_endpoints
        endpoints = exact_toolbox._list_endpoints()
        self.assertIn("total_endpoints", endpoints)
        self.assertIn("endpoints", endpoints)
        self.assertEqual(endpoints["total_endpoints"], len(endpoints["endpoints"]))

        # Test search_endpoints_by_keyword
        search_result = exact_toolbox._search_endpoints("invoice")
        self.assertIn("search_keyword", search_result)
        self.assertIn("matches_found", search_result)
        self.assertIn("endpoints", search_result)
        self.assertGreater(search_result["matches_found"], 0)

        # Test case-insensitive search
        search_result_upper = exact_toolbox._search_endpoints("INVOICE")
        self.assertEqual(
            search_result["matches_found"], search_result_upper["matches_found"]
        )

    def test_tool_execution_discovery(self):
        """Test executing discovery tools."""
        # Test list_available_endpoints execution
        result = exact_toolbox.execute_tool(
            "list_available_endpoints", {}, "dummy_session"
        )
        self.assertIn("total_endpoints", result)
        self.assertIsInstance(result["total_endpoints"], int)

        # Test search_endpoints_by_keyword execution
        result = exact_toolbox.execute_tool(
            "search_endpoints_by_keyword", {"keyword": "sales"}, "dummy_session"
        )
        self.assertIn("search_keyword", result)
        self.assertIn("matches_found", result)
        self.assertEqual(result["search_keyword"], "sales")

    def test_invalid_tool_execution(self):
        """Test executing invalid tools returns error."""
        result = exact_toolbox.execute_tool("invalid_tool", {}, "dummy_session")
        self.assertIn("error", result)
        self.assertIn("function", result)


class AIChatViewTestCase(TestCase):
    """Test the AI chat Django view."""

    def setUp(self):
        self.client = Client()
        # Force session creation
        session = self.client.session
        session.save()

    def test_ai_chat_no_session(self):
        """Test AI chat without session returns 401."""
        # Create client without session
        client = Client()
        response = client.post(
            reverse("ask:ai_chat"),
            data=json.dumps({"message": "test"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertIn("error", data)
        self.assertIn("session", data["error"].lower())

    def test_ai_chat_no_openai_key(self):
        """Test AI chat without OpenAI API key returns 500."""
        with patch.dict("os.environ", {}, clear=True):
            response = self.client.post(
                reverse("ask:ai_chat"),
                data=json.dumps({"message": "test"}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 500)
            data = response.json()
            self.assertIn("error", data)
            self.assertIn("OpenAI", data["error"])

    def test_ai_chat_invalid_json(self):
        """Test AI chat with invalid JSON returns 400."""
        response = self.client.post(
            reverse("ask:ai_chat"), data="invalid json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)
        self.assertIn("JSON", data["error"])

    def test_ai_chat_no_message(self):
        """Test AI chat without message returns 400."""
        response = self.client.post(
            reverse("ask:ai_chat"),
            data=json.dumps({"message": ""}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)
        self.assertIn("required", data["error"].lower())

    @patch("ask.services.IntentParser")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "fake-key"})
    def test_ai_chat_success(self, mock_client_class):
        """Test successful AI chat."""
        # Mock the AI client
        mock_client = MagicMock()
        mock_client.chat.return_value = "This is a test response"
        mock_client_class.return_value = mock_client

        response = self.client.post(
            reverse("ask:ai_chat"),
            data=json.dumps({"message": "What endpoints are available?"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("response", data)
        self.assertIn("message", data)
        self.assertEqual(data["message"], "What endpoints are available?")
        self.assertEqual(data["response"], "This is a test response")

        # Verify client was called correctly
        mock_client_class.assert_called_once()
        mock_client.chat.assert_called_once_with("What endpoints are available?")


class ApiForwarderTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.session.create()
        self.session_key = self.client.session.session_key

    def test_api_forwarder_no_session(self):
        """Test API forwarder without session returns 401"""
        client_no_session = Client()
        response = client_no_session.get(
            reverse("ask:api_forwarder", args=["test/endpoint"])
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "No session available")

    @patch("ask.views.get_service")
    def test_api_forwarder_success(self, mock_get_service):
        """Test successful API forwarding with system/Me endpoint"""
        mock_service = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "d": {
                "results": [
                    {
                        "CurrentDivision": 123456,
                        "UserID": "test-user-id",
                        "FullName": "Test User",
                    }
                ]
            }
        }
        mock_service.get.return_value = mock_response
        mock_get_service.return_value = mock_service

        response = self.client.get(reverse("ask:api_forwarder", args=["system/Me"]))

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn("d", response_data)
        self.assertIn("results", response_data["d"])
        mock_service.get.assert_called_once_with("system/Me", params={})

    @patch("ask.views.get_service")
    def test_api_forwarder_items_with_filters(self, mock_get_service):
        """Test API forwarding with Items endpoint and query parameters"""
        mock_service = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "d": {
                "results": [
                    {
                        "ID": "item-123",
                        "Code": "ITEM001",
                        "Description": "Test Item",
                        "IsSalesItem": True,
                    }
                ]
            }
        }
        mock_service.get.return_value = mock_response
        mock_get_service.return_value = mock_service

        response = self.client.get(
            reverse("ask:api_forwarder", args=["logistics/Items"])
            + "?$filter=IsSalesItem eq true&$select=ID,Code,Description"
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn("d", response_data)
        self.assertIn("results", response_data["d"])
        mock_service.get.assert_called_once_with(
            "logistics/Items",
            params={"$filter": "IsSalesItem eq true", "$select": "ID,Code,Description"},
        )

    @patch("ask.views.get_service")
    def test_api_forwarder_accounts_endpoint(self, mock_get_service):
        """Test API forwarding with Accounts endpoint"""
        mock_service = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "d": {
                "results": [
                    {
                        "ID": "account-123",
                        "Code": "CUST001",
                        "Name": "Test Customer",
                        "Status": "C",
                    }
                ]
            }
        }
        mock_service.get.return_value = mock_response
        mock_get_service.return_value = mock_service

        response = self.client.get(reverse("ask:api_forwarder", args=["crm/Accounts"]))

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn("d", response_data)
        self.assertEqual(len(response_data["d"]["results"]), 1)
        self.assertEqual(response_data["d"]["results"][0]["Code"], "CUST001")
        mock_service.get.assert_called_once_with("crm/Accounts", params={})

    @patch("ask.views.get_service")
    def test_api_forwarder_api_error(self, mock_get_service):
        """Test API forwarder when Exact API returns error"""
        mock_service = Mock()
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Endpoint not found"
        mock_service.get.return_value = mock_response
        mock_get_service.return_value = mock_service

        response = self.client.get(
            reverse("ask:api_forwarder", args=["nonexistent/endpoint"])
        )

        self.assertEqual(response.status_code, 404)
        response_data = response.json()
        self.assertEqual(response_data["error"], "Exact API returned status 404")
        self.assertEqual(response_data["details"], "Endpoint not found")

    @patch("ask.views.get_service")
    def test_api_forwarder_service_exception(self, mock_get_service):
        """Test API forwarder when service raises ValueError"""
        mock_get_service.side_effect = ValueError("No valid token found")

        response = self.client.get(reverse("ask:api_forwarder", args=["test/endpoint"]))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "No valid token found")

    @patch("ask.views.get_service")
    def test_api_forwarder_general_exception(self, mock_get_service):
        """Test API forwarder when unexpected exception occurs"""
        mock_get_service.side_effect = Exception("Unexpected error")

        response = self.client.get(reverse("ask:api_forwarder", args=["test/endpoint"]))

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"], "Internal server error")


class IntegrationTestCase(TestCase):
    """Integration tests for the complete AI system."""

    def test_exact_toolbox_has_expected_endpoints(self):
        """Test that tool registry contains expected endpoint tools."""
        tools = exact_toolbox.get_openai_tools()
        tool_names = [tool["function"]["name"] for tool in tools]

        # Should have discovery tools
        self.assertIn("list_available_endpoints", tool_names)
        self.assertIn("search_endpoints_by_keyword", tool_names)

        # Should have some expected API endpoint tools
        self.assertIn("get_salesinvoices", tool_names)
        self.assertIn("get_salesorders", tool_names)
        self.assertIn("get_syncaccounts", tool_names)  # Customer/CRM accounts
        self.assertIn("get_glaccounts", tool_names)

    def test_home_page_loads(self):
        """Test that the home page with AI interface loads."""
        response = self.client.get(reverse("ask:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI Assistant for Exact Online")
        self.assertContains(response, "Ask a question")
        self.assertContains(response, "/chat")

    def test_exact_toolbox_covers_all_config_endpoints(self):
        """Test that tool registry generates tools for all configured endpoints."""
        # Load the tool config to compare
        import json

        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "exact_specs", "api_specs", "cleaned", "TOOL_DOCUMENTATION.json"
        )
        with open(config_path, "r") as f:
            config = json.load(f)

        config_endpoints = list(config.keys())
        tools = exact_toolbox.get_openai_tools()
        tool_names = [tool["function"]["name"] for tool in tools]

        # Check each endpoint has a corresponding tool
        for endpoint in config_endpoints:
            expected_tool_name = f"get_{endpoint.lower()}"
            self.assertIn(
                expected_tool_name, tool_names, f"Missing tool for endpoint: {endpoint}"
            )

    def test_ai_endpoints_integration(self):
        """Test the URLs are correctly configured for AI endpoints."""
        # Test that the AI chat URL exists
        try:
            url = reverse("ask:ai_chat")
            self.assertEqual(url, "/chat")
        except:
            self.fail("ai_chat URL not configured correctly")

        # Test that the API forwarder URL exists
        try:
            url = reverse("ask:api_forwarder", args=["test"])
            self.assertEqual(url, "/api/test")
        except:
            self.fail("api_forwarder URL not configured correctly")

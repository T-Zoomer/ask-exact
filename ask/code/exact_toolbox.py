import json
import os
from typing import Any, Dict, List
from exact_oauth.services import get_service
from .intent import Intent


class ExactToolbox:
    """Toolbox that converts Exact Online APIs into OpenAI function calling tools."""

    def __init__(self):
        self.tools = self._generate_tools()

    def _generate_tools(self) -> List[Dict[str, Any]]:
        """Generate OpenAI function schemas from TOOL_DOCUMENTATION.json"""

        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "exact_specs", "api_specs", "cleaned", "TOOL_DOCUMENTATION.json"
        )
        with open(config_path, "r") as f:
            TOOL_DOCS = json.load(f)

        tools = []

        # Generate tools for each API endpoint
        for endpoint_name, endpoint_config in TOOL_DOCS.items():
            fields = endpoint_config.get('fields')
            documentation = endpoint_config.get('documentation')
            description = documentation.get('llm_description')
            keywords = documentation.get('llm_keywords')
            data_info = documentation.get('llm_data_info')
            endpoint_info = documentation.get('endpoint_info', {})

            
            tool = {
                "name": endpoint_name.lower(),
                "description": f"{description}\n\nKeywords: {', '.join(keywords or [])}",
                "data_summary": data_info,
                "fields": fields,
                "endpoint_info": endpoint_info
            }
            tools.append(tool)

        return tools


    def get_tool_descriptions_for_llm(self) -> List[Dict[str, Any]]:
        """Get tools formatted for OpenAI function calling, excluding fields and endpoint_info."""
        return [
            {k: v for k, v in tool.items() if k not in ["fields", "endpoint_info"]}
            for tool in self.tools
        ]


    def get_tool_details_for_llm(self, tool_name: str) -> dict:
        """Return the tool dict matching the tool name."""
        for tool in self.tools:
            if tool["name"] == tool_name:
                return tool
        return "Tool not found."
    

    def get_clean_endpoint(self, intent: Intent) -> str:
        """
        Get the cleaned API endpoint for the given intent's tool_call.
        
        Args:
            intent: Intent object containing tool_call
            
        Returns:
            Cleaned endpoint path without /api/v1/{division}/ prefix
        """
        # Find the tool configuration
        tool_config = None
        for tool in self.tools:
            if tool["name"] == intent.tool_call:
                tool_config = tool
                break
        
        if not tool_config:
            raise ValueError(f"Tool '{intent.tool_call}' not found")
        
        # Get the API URI from tool configuration
        endpoint_info = tool_config.get("endpoint_info", {})
        api_uri = endpoint_info.get("uri")
        
        if not api_uri:
            raise ValueError(f"API URI not found for endpoint: {intent.tool_call}")
        
        # Remove the /api/v1/{division}/ prefix since ExactOnlineService adds it
        if api_uri.startswith("/api/v1/{division}/"):
            return api_uri[len("/api/v1/{division}/"):]
        else:
            return api_uri.lstrip("/")

    def get_url(self, intent: Intent) -> str:
        """
        Get the complete API endpoint URL with OData query for the given intent.
        
        Args:
            intent: Intent object containing tool_call and filters
            
        Returns:
            Complete endpoint URL with OData query string
        """
        # Get cleaned endpoint
        api_endpoint = self.get_clean_endpoint(intent)
        
        # Append OData filter URL if we have filters
        filter_url = intent.to_odata_filter_url()
        if filter_url:
            api_endpoint = f"{api_endpoint}{filter_url}"
        
        return api_endpoint


    def execute(self, intent: Intent, session_key: str) -> Dict[str, Any]:
        """
        Execute user intent by calling the appropriate tool and corresponding API.
        
        Args:
            intent: Intent object containing tool_call, description, and filters
            session_key: Django session key for Exact Online authentication
            
        Returns:
            Dict containing API response data
        """
        # Validate intent first
        # Later we should move the validation to parser and retry if its bad. 
        validation_error = intent.validate(self)
        if validation_error:
            return validation_error
        
        try:
            # Get complete URL from toolbox
            api_endpoint = self.get_url(intent)
            
            # Get ExactOnline service instance
            service = get_service(session_key)
            
            # Make the API call
            response = service.get(api_endpoint)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": data,
                    "intent": intent.to_dict(),
                    "endpoint": api_endpoint,
                    "filters_applied": len(intent.filters) > 0
                }
            else:
                return {
                    "error": f"API call failed with status {response.status_code}",
                    "details": response.text,
                    "endpoint": api_endpoint
                }
                
        except Exception as e:
            return {
                "error": f"Execution failed: {str(e)}",
                "intent": intent.to_dict(),
                "endpoint": api_endpoint if 'api_endpoint' in locals() else None
            }



# Global toolbox instance
exact_toolbox = ExactToolbox()
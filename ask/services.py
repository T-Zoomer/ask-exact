import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from datetime import date, datetime
from openai import OpenAI
from exact_oauth.services import get_service
from django.conf import settings

# Load the tool documentation globally
config_path = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "exact_specs", "api_specs", "cleaned", "TOOL_DOCUMENTATION.json"
)
with open(config_path, "r") as f:
    TOOL_DOCS = json.load(f)


# --------------------------
# Intent
# --------------------------

Primitive = Union[str, int, float, bool, date, datetime]


class Op(str, Enum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GE = "ge"
    LT = "lt"
    LE = "le"
    IN = "in"
    CONTAINS = "contains"
    STARTSWITH = "startswith"
    ENDSWITH = "endswith"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


@dataclass
class Filter:
    field: str
    op: Op
    value: Optional[Primitive] = None
    values: Optional[List[Primitive]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {"field": self.field, "op": self.op.value}
        if self.value is not None:
            result["value"] = self.value
        if self.values is not None:
            result["values"] = self.values
        return result


class Intent:
    """
    Machine-readable representation of user intent.
    Holds tool_call, description, and filters, and can render OData.
    """

    def __init__(
        self,
        tool_call: Optional[str] = None,
        description: Optional[str] = None,
        filters: Optional[List[Filter]] = None,
        use_in: bool = True,
    ):
        self.tool_call = tool_call
        self.description = description
        self.filters = filters or []
        self._use_in = use_in  # for OData rendering

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_call": self.tool_call,
            "description": self.description,
            "filters": [f.to_dict() for f in self.filters],
            "odata_filter": self.to_odata(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Intent":
        filters = []
        for f in data.get("filters", []):
            filters.append(
                Filter(
                    field=f["field"],
                    op=Op(f["op"]),
                    value=f.get("value"),
                    values=f.get("values"),
                )
            )
        return cls(
            tool_call=data.get("tool_call"),
            description=data.get("description"),
            filters=filters,
        )

    @classmethod
    def from_json(cls, json_str: str) -> "Intent":
        return cls.from_dict(json.loads(json_str))


    def validate(self, tool_config: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """
        Validate the intent against available tools and fields.
        
        Args:
            tool_config: Optional tool configuration dict, uses global TOOL_CONFIG if not provided
        
        Returns:
            Error dict if validation fails, None if valid
        """
        if tool_config is None:
            tool_config = TOOL_DOCS
        
        # Validate tool_call
        if not self.tool_call:
            return {"error": "Intent is missing tool_call"}
        
        if not self.tool_call.startswith("get_"):
            return {"error": f"Invalid tool call format: {self.tool_call}. Must start with 'get_'"}
        
        # Check if tool exists
        endpoint_key = self.tool_call[4:]  # Remove 'get_' prefix
        available_tools = [f"get_{key.lower()}" for key in tool_config.keys()]
        
        if self.tool_call not in available_tools:
            return {
                "error": f"Tool '{self.tool_call}' not found. Available tools are: {', '.join(available_tools)}",
                "available_tools": available_tools,
                "requested_tool": self.tool_call
            }
        
        # Find endpoint config for field validation
        endpoint_config = None
        for key, config in TOOL_CONFIG.items():
            if key.lower() == endpoint_key.lower():
                endpoint_config = config
                break
        
        # Validate filter fields
        if self.filters and endpoint_config:
            available_fields = endpoint_config.get("fields", {})
            available_field_names = set(available_fields.keys())
            
            invalid_fields = []
            for filter_obj in self.filters:
                if filter_obj.field not in available_field_names:
                    invalid_fields.append(filter_obj.field)
            
            if invalid_fields:
                return {
                    "error": f"Invalid field name(s): {', '.join(invalid_fields)}. Available fields for this endpoint are: {', '.join(sorted(available_field_names))}",
                    "invalid_fields": invalid_fields,
                    "available_fields": sorted(available_field_names),
                    "endpoint": endpoint_config.get("name", "unknown")
                }
        
        return None

    def to_odata(self) -> str:
        """
        Converts current filters into an OData $filter string.
        Always joins multiple filters with AND.
        """
        if not self.filters:
            return ""
        parts = [self._render_filter(f) for f in self.filters]
        return " and ".join(f"({p})" for p in parts)


    def _render_filter(self, f: Filter) -> str:
        def _q(value: Primitive) -> str:
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, (int, float)):
                return str(value)
            if isinstance(value, (date, datetime)):
                return value.isoformat().replace("+00:00", "Z")
            escaped_value = str(value).replace("'", "''")
            return f"'{escaped_value}'"

        if f.op in {Op.EQ, Op.NE, Op.GT, Op.GE, Op.LT, Op.LE}:
            return f"{f.field} {f.op.value} {_q(f.value)}"
        if f.op == Op.IN:
            if self._use_in:
                vals = ", ".join(_q(v) for v in f.values)
                return f"{f.field} in ({vals})"
            else:
                parts = [f"{f.field} eq {_q(v)}" for v in f.values]
                return "(" + " or ".join(parts) + ")"
        if f.op in {Op.CONTAINS, Op.STARTSWITH, Op.ENDSWITH}:
            return f"{f.op.value}({f.field}, {_q(f.value)})"
        if f.op == Op.IS_NULL:
            return f"{f.field} eq null"
        if f.op == Op.IS_NOT_NULL:
            return f"{f.field} ne null"
        raise ValueError(f"Unsupported operator: {f.op}")


# --------------------------
# ExactToolbox
# --------------------------



class ExactToolbox:
    """Toolbox that converts Exact Online APIs into OpenAI function calling tools."""

    def __init__(self):
        self.tools = self._generate_tools()

    def _generate_tools(self) -> List[Dict[str, Any]]:
        """Generate OpenAI function schemas from TOOL_DOCUMENTATION.json"""
        tools = []

        # Generate tools for each API endpoint
        for endpoint_name, endpoint_config in TOOL_DOCS.items():
            fields = endpoint_config.get('fields')
            documentation = endpoint_config.get('documentation')
            description = documentation.get('llm_description')
            keywords = documentation.get('llm_keywords')
            data_info = documentation.get('llm_data_info')

            
            tool = {
                "name": f"get_{endpoint_name.lower()}",
                "description": f"{description}\n\nKeywords: {', '.join(keywords or [])}",
                "data_summary": data_info,
                "fields": fields
            }
            tools.append(tool)

        return tools

    def get_tool_descriptions_for_llm(self) -> List[Dict[str, Any]]:
        """Get tools formatted for OpenAI function calling, excluding fields."""
        return [
            {k: v for k, v in tool.items() if k != "fields"}
            for tool in self.tools
        ]
    
    def get_tool_details_for_llm(self, tool_name: str) -> str:
        """Get endpoint details for a single tool including documentation and fields for LLM consumption."""
        # Find the tool by name
        for tool in self.tools:
            if tool["name"] == tool_name:
                result_parts = []
                
                # Add documentation if available
                if tool.get("description"):
                    result_parts.append(f"Description: {tool['description']}")
                
                if tool.get("data_summary"):
                    result_parts.append(f"Data Summary: {tool['data_summary']}")
                
                # Add fields information
                fields = tool.get("fields")
                if fields:
                    result_parts.append("\nAvailable Fields:")
                    field_descriptions = []
                    for field_name, field_info in fields.items():
                        description = field_info.get("description", "No description")
                        field_type = field_info.get("type", "Unknown type")
                        field_descriptions.append(f"- {field_name} ({field_type}): {description}")
                    result_parts.append("\n".join(field_descriptions))
                else:
                    result_parts.append("No field information available for this endpoint.")
                
                return "\n\n".join(result_parts)
        
        return "Tool not found."
    

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
        validation_error = intent.validate()
        if validation_error:
            return validation_error
        
        endpoint_key = intent.tool_call[4:]  # Remove 'get_' prefix
        
        # Find the endpoint configuration (should exist after validation)
        endpoint_config = None
        for key, config in TOOL_DOCS.items():
            if key.lower() == endpoint_key.lower():
                endpoint_config = config
                break
        
        # Get the API URI from documentation
        documentation = endpoint_config.get("documentation", {})
        endpoint_info = documentation.get("endpoint_info", {})
        api_uri = endpoint_info.get("uri")
        
        if not api_uri:
            return {"error": f"API URI not found for endpoint: {endpoint_key}"}
        
        # Remove the /api/v1/{division}/ prefix since ExactOnlineService adds it
        if api_uri.startswith("/api/v1/{division}/"):
            api_endpoint = api_uri[len("/api/v1/{division}/"):]
        else:
            api_endpoint = api_uri.lstrip("/")
        
        try:
            # Get ExactOnline service instance
            service = get_service(session_key)
            
            # Build query parameters from intent filters
            params = {}
            if intent.filters:
                odata_filter = intent.to_odata()
                if odata_filter:
                    params["$filter"] = odata_filter
            
            # Make the API call
            response = service.get(api_endpoint, params=params)
            
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


# --------------------------
# IntentParser
# --------------------------



class IntentParser:
    """Parses user input into Intent objects using two-step LLM calls."""

    def __init__(self):
        """
        Initialize the AI client.
        """
        openai_api_key = getattr(settings, 'OPENAI_API_KEY', None)
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY not configured in settings")
        
        self.openai_client = OpenAI(api_key=openai_api_key)
        self.conversation_history = []

    def parse_intent(self, message: str) -> Intent:
        """
        Parse user input into Intent using two-step LLM approach.
        
        Step 1: Determine the appropriate tool
        Step 2: Determine the filters for the Intent
        
        Args:
            message: User message
            
        Returns:
            Intent object
        """
        # Step 1: Tool determination
        tool_call = self._determine_tool(message)
        
        # Step 2: Filter determination
        filters = self._determine_filters(message, tool_call)
        
        
        return Intent(
            tool_call=tool_call,
            description=message,
            filters=filters
        )
    
    def _determine_tool(self, message: str) -> str:
        """First LLM call to determine which tool to use."""
        # Get available tools from toolbox
        available_tools = exact_toolbox.get_tool_descriptions_for_llm()
        
        # Format tools for the LLM
        tool_descriptions = []
        for tool in available_tools:
            tool_descriptions.append(f"- {tool['name']}: {tool['description']}")
        
        tools_text = "\n".join(tool_descriptions)
        
        tool_system_prompt = f"""You are a tool selector for Exact Online ERP/accounting APIs.

Available tools:
{tools_text}

Analyze the user message and respond with ONLY the tool name (e.g. "get_salesinvoices").
Do not include any other text or explanation."""

        messages = [
            {"role": "system", "content": tool_system_prompt},
            {"role": "user", "content": message}
        ]
        
        print(f"🔍 IntentParser: Step 1 - Determining tool for: {message}")
        print(f"🛠️ IntentParser: Loaded {len(available_tools)} available tools")
        response = self.openai_client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0
        )
        
        tool_call = response.choices[0].message.content.strip()
        print(f"🛠️ IntentParser: Selected tool: {tool_call}")
        return tool_call
    
    def _determine_filters(self, message: str, tool_call: str) -> List[Filter]:
        """Second LLM call to determine filters based on the message and selected tool."""
        # Get formatted endpoint details from toolbox
        tool_details = exact_toolbox.get_tool_details_for_llm(tool_call)

        # Get current date for context
        current_date = datetime.now()
        current_year = current_date.year
        current_month = current_date.month
        
        filter_system_prompt = f"""You are a filter generator for Exact Online API calls.

Current date context: {current_date.strftime('%Y-%m-%d')} (Year: {current_year}, Month: {current_month})

The user wants to call: {tool_call}

Available fields for this endpoint:
{tool_details}

Available filter operators:
- eq, ne, gt, ge, lt, le (comparison)
- in (list of values)  
- contains, startswith, endswith (text search)
- is_null, is_not_null (null checks)

IMPORTANT: Use the correct data types for field values based on the field definitions above:
- Edm.Int16, Edm.Int32: Use integers (e.g., 2024, not "2024")  
- Edm.Double: Use numbers (e.g., 100.50, not "100.50")
- Edm.DateTime: Use ISO 8601 format (e.g., "2024-01-01T00:00:00Z")
- Edm.Boolean: Use true/false (not "true"/"false")
- Edm.Guid: Use string format (e.g., "12345678-1234-1234-1234-123456789abc")
- Edm.String: Use string values
- For relative dates, convert using current date context:
  * "this year" → {current_year}
  * "this month" → {current_month} 
  * "last year" → {current_year - 1}
  * "last month" → {current_month - 1} (handle year rollover appropriately)
  * Example: FinancialYear should be {current_year}, not "this year"

Analyze the user message and extract any filters they want to apply using the available fields.
Only use field names that exist in the available fields list above.
Respond with ONLY a JSON array of filter objects in this format:
[
  {{"field": "field_name", "op": "operator", "value": "value"}},
  {{"field": "field_name", "op": "in", "values": ["val1", "val2"]}}
]

If no specific filters are mentioned, return an empty array: []
Do not include any other text or explanation."""

        messages = [
            {"role": "system", "content": filter_system_prompt},
            {"role": "user", "content": message}
        ]
        
        print(f"🔧 IntentParser: Step 2 - Determining filters for: {message}")
        field_count = len(tool_details.split('\n')) if tool_details != "No field information available for this endpoint." else 0
        print(f"📊 IntentParser: Loaded {field_count} fields for tool: {tool_call}")
        response = self.openai_client.chat.completions.create(
            model="gpt-4", 
            messages=messages,
            temperature=0
        )
        
        response_content = response.choices[0].message.content.strip()
        print(f"📋 IntentParser: Raw filter response: {response_content}")
        
        try:
            filter_data = json.loads(response_content)
            filters = []
            for f in filter_data:
                filters.append(Filter(
                    field=f["field"],
                    op=Op(f["op"]),
                    value=f.get("value"),
                    values=f.get("values")
                ))
            print(f"🎯 IntentParser: Parsed {len(filters)} filters")
            return filters
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"❌ IntentParser: Failed to parse filters: {e}")
            return []
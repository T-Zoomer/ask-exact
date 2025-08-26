import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from datetime import date, datetime
from openai import OpenAI
from exact_oauth.services import get_service


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

    def is_valid(self) -> bool:
        return bool(self.tool_call and self.description)

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

# Load the tool configuration
config_path = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "exact_specs", "api_specs", "cleaned", "TOOL_DOCUMENTATION.json"
)
with open(config_path, "r") as f:
    TOOL_CONFIG = json.load(f)


class ExactToolbox:
    """Toolbox that converts Exact Online APIs into OpenAI function calling tools."""

    def __init__(self):
        self.tools = self._generate_tools()

    def _generate_tools(self) -> List[Dict[str, Any]]:
        """Generate OpenAI function schemas from TOOL_DOCUMENTATION.json"""
        tools = []

        # Generate tools for each API endpoint
        for endpoint_name, endpoint_config in TOOL_CONFIG.items():
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
    
    def get_endpoint_details_for_llm(self, tool_name: str) -> str:
        """Get endpoint details including documentation and fields for LLM consumption."""
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

    def execute_tool(
        self, function_name: str, arguments: Dict[str, Any], session_key: str
    ) -> Dict[str, Any]:
        """Execute a tool and return the result."""
        print(
            f"🔧 Tool Registry: Executing tool '{function_name}' with args: {arguments}"
        )

        try:
            if function_name.startswith("get_"):
                # Extract endpoint name from function name
                endpoint_name = function_name[4:]  # Remove "get_" prefix
                print(f"📡 Tool Registry: Looking for endpoint '{endpoint_name}'")
                # Find the original endpoint name (case-sensitive)
                for name in TOOL_CONFIG.keys():
                    if name.lower() == endpoint_name:
                        print(
                            f"✅ Tool Registry: Found endpoint '{name}', calling API..."
                        )
                        return self._call_exact_api(name, arguments, session_key)
                raise ValueError(f"Unknown endpoint: {endpoint_name}")
            else:
                raise ValueError(f"Unknown function: {function_name}")

        except Exception as e:
            print(f"❌ Tool Registry: Error executing '{function_name}': {str(e)}")
            return {"error": str(e), "function": function_name}

    def execute_user_intent(self, user_intent, session_key: str) -> Dict[str, Any]:
        """Execute an Intent by calling the specified tool with arguments."""
        if not user_intent.is_valid():
            raise ValueError(f"Intent is not valid: missing tool_call or description")

        print(
            f"🎯 ExactToolbox: Executing Intent '{user_intent.tool_call}' - {user_intent.description}"
        )
        print(f"🔧 ExactToolbox: Filters: {user_intent.filters}")

        try:
            # Convert filters to arguments for the tool
            arguments = (
                {"filter": user_intent.to_odata()} if user_intent.filters else {}
            )
            result = self.execute_tool(user_intent.tool_call, arguments, session_key)
            print(
                f"✅ ExactToolbox: Successfully executed Intent '{user_intent.tool_call}'"
            )
            return result
        except Exception as e:
            print(
                f"❌ ExactToolbox: Failed to execute Intent '{user_intent.tool_call}': {e}"
            )
            raise ValueError(f"Intent execution failed: {e}")

    def _call_exact_api(
        self, endpoint_name: str, arguments: Dict[str, Any], session_key: str
    ) -> Dict[str, Any]:
        """Call the Exact Online API via the service."""
        endpoint_config = TOOL_CONFIG[endpoint_name]
        
        # Get the API path from documentation
        endpoint_info = endpoint_config.get('documentation', {}).get('endpoint_info', {})
        uri = endpoint_info.get('uri', f'/api/v1/{{division}}/{endpoint_name}')
        
        # Get the API path (remove base URL and division placeholder)
        path = uri.split("/{division}/")[-1]
        print(f"🌐 Tool Registry: API path: {path}")

        # Build query parameters
        params = {}
        for key, value in arguments.items():
            if value is not None:
                if key == "filter":
                    params["$filter"] = value
                elif key == "select":
                    params["$select"] = value
                elif key == "orderby":
                    params["$orderby"] = value
                elif key == "top":
                    params["$top"] = value
                elif key == "skip":
                    params["$skip"] = value

        print(f"🔗 Tool Registry: Query params: {params}")

        # Use the Exact Online service
        print(f"🔑 Tool Registry: Getting service for session: {session_key[:8]}...")
        service = get_service(session_key)

        print(f"📞 Tool Registry: Making API call to: {path}")
        response = service.get(path, params=params)

        print(f"📨 Tool Registry: API response status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            result_count = (
                len(data.get("d", {}).get("results", [])) if "d" in data else 0
            )
            print(f"✅ Tool Registry: Successfully retrieved {result_count} records")
            return data
        else:
            error_msg = f"API call failed: {response.status_code} - {response.text}"
            print(f"❌ Tool Registry: {error_msg}")
            raise Exception(error_msg)



# Global toolbox instance
exact_toolbox = ExactToolbox()


# --------------------------
# IntentFormer
# --------------------------



class IntentFormer:
    """Parses user input into Intent objects using two-step LLM calls."""

    def __init__(self, openai_api_key: str, session_key: str):
        """
        Initialize the AI client.

        Args:
            openai_api_key: OpenAI API key
            session_key: Django session key for Exact Online authentication
        """
        self.openai_client = OpenAI(api_key=openai_api_key)
        self.session_key = session_key
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
        
        print(f"🔍 IntentFormer: Step 1 - Determining tool for: {message}")
        print(f"🛠️ IntentFormer: Loaded {len(available_tools)} available tools")
        response = self.openai_client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0
        )
        
        tool_call = response.choices[0].message.content.strip()
        print(f"🛠️ IntentFormer: Selected tool: {tool_call}")
        return tool_call
    
    def _determine_filters(self, message: str, tool_call: str) -> List[Filter]:
        """Second LLM call to determine filters based on the message and selected tool."""
        # Get formatted endpoint details from toolbox
        tool_details = exact_toolbox.get_endpoint_details_for_llm(tool_call)

        print("FIELDS TEXT")
        print(tool_details)
        
        filter_system_prompt = f"""You are a filter generator for Exact Online API calls.

The user wants to call: {tool_call}

Available fields for this endpoint:
{tool_details}

Available filter operators:
- eq, ne, gt, ge, lt, le (comparison)
- in (list of values)  
- contains, startswith, endswith (text search)
- is_null, is_not_null (null checks)

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
        
        print(f"🔧 IntentFormer: Step 2 - Determining filters for: {message}")
        field_count = len(tool_details.split('\n')) if tool_details != "No field information available for this endpoint." else 0
        print(f"📊 IntentFormer: Loaded {field_count} fields for tool: {tool_call}")
        response = self.openai_client.chat.completions.create(
            model="gpt-4", 
            messages=messages,
            temperature=0
        )
        
        response_content = response.choices[0].message.content.strip()
        print(f"📋 IntentFormer: Raw filter response: {response_content}")
        
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
            print(f"🎯 IntentFormer: Parsed {len(filters)} filters")
            return filters
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"❌ IntentFormer: Failed to parse filters: {e}")
            return []
    
    def chat(self, message: str) -> str:
        """
        Chat interface that uses the two-step Intent parsing approach.
        
        Args:
            message: User message
            
        Returns:
            AI response
        """
        try:
            # Parse user input into Intent using two-step approach
            user_intent = self.parse_intent(message)
            
            if not user_intent.is_valid():
                return "I couldn't understand what you want me to do. Please try rephrasing your request."

            # Execute the Intent
            print(f"⚡ IntentFormer: Executing Intent...")
            tool_result = exact_toolbox.execute_user_intent(
                user_intent, self.session_key
            )

            # Generate a human-friendly response based on the result
            response_messages = [
                {
                    "role": "system", 
                    "content": "You are a helpful assistant that explains API results in a friendly way. Format the data nicely for the user.",
                },
                {"role": "user", "content": f"The user asked: {message}"},
                {
                    "role": "user",
                    "content": f"Here's the API result: {json.dumps(tool_result)[:2000]}",
                },
            ]

            final_response = self.openai_client.chat.completions.create(
                model="gpt-4", messages=response_messages
            )

            final_message = final_response.choices[0].message.content
            print(f"📝 IntentFormer: Generated response, length: {len(final_message)}")
            return final_message

        except Exception as e:
            print(f"❌ IntentFormer: Error processing request: {e}")
            return "I had trouble processing your request. Could you please try again?"

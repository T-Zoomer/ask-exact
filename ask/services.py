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

# TODO: Make better general tool overview.
# TODO: Add the individual tool API data here.

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
            documentation = endpoint_config.get('documentation', {})
            description = documentation.get('llm_description', f'Access {endpoint_name} data')
            keywords = documentation.get('keywords', [])
            
            tool = {
                "type": "function",
                "function": {
                    "name": f"get_{endpoint_name.lower()}",
                    "description": f"{description}\n\nKeywords: {', '.join(keywords)}",
                },
            }
            tools.append(tool)

        return tools

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Get tools formatted for OpenAI function calling."""
        return self.tools

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

# TODO: Rename ExactOnlineAIClient into IntentFormer
# TODO: make a new intentFormer class that makes the Intent Data. First LLM call should determine the tool, second LLM call should determinte the Intent filters.
# TODO: It can use the


class ExactOnlineAIClient:
    """OpenAI client that can use Exact Online APIs as function calling tools."""

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

    def chat(self, message: str, system_prompt: Optional[str] = None) -> str:
        """
        Chat with the AI by parsing messages into UserIntent objects and executing them.

        Args:
            message: User message
            system_prompt: Optional system prompt

        Returns:
            AI response
        """
        # Default system prompt for parsing user intent
        system_prompt = """You are an AI assistant that parses user messages into structured Intent objects for Exact Online ERP/accounting APIs.

Your job is to analyze user messages and create an Intent object with:
1. tool_call: The specific API tool/function the user wants (e.g., "get_salesinvoices")
2. filters: List of filter objects for the API call
3. description: Short text describing what the user wants

Available tools include:
- get_salesinvoices, get_purchaseinvoices (invoice data)
- get_salesorders, get_purchaseorders (order data)
- get_suppliers, get_customers (contact data)
- get_bankentries, get_cashentries (financial transactions)
- get_profitlossoverview, get_balancesheetoverview (financial reports)
- list_available_endpoints, search_endpoints_by_keyword (discovery)

Respond ONLY with a valid JSON Intent object in this format:
{
  "tool_call": "function_name",
  "filters": [],
  "description": "What the user wants"
}

Do not include any other text or explanation.
"""

        # Prepare messages for Intent parsing
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation_history)
        messages.append({"role": "user", "content": message})

        # Parse message into Intent using LLM
        print(f"🧠 AI Client: Parsing user message into Intent")
        response = self.openai_client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0,  # More deterministic for parsing
        )

        response_content = response.choices[0].message.content.strip()
        print(f"📋 AI Client: Raw LLM response: {response_content[:200]}...")

        try:
            # Parse the response as Intent JSON
            user_intent = Intent.from_json(response_content)
            print(f"🎯 AI Client: Parsed Intent: {user_intent}")

            if not user_intent.is_valid():
                return "I couldn't understand what you want me to do. Please try rephrasing your request."

            # Execute the Intent
            print(f"⚡ AI Client: Executing Intent...")
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
            print(f"📝 AI Client: Generated response, length: {len(final_message)}")

        except (json.JSONDecodeError, ValueError) as e:
            print(f"❌ AI Client: Failed to parse Intent: {e}")
            final_message = "I had trouble understanding your request. Could you please rephrase it?"

        # Update conversation history
        self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append(
            {"role": "assistant", "content": final_message}
        )

        # Keep conversation history manageable
        if len(self.conversation_history) > 10:
            self.conversation_history = self.conversation_history[-10:]

        return final_message

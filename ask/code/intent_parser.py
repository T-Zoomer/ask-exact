import json
from datetime import datetime
from typing import List
from openai import OpenAI
from django.conf import settings
from .intent import Intent, Filter, Op
from .exact_toolbox import exact_toolbox


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

Analyze the user message and respond with ONLY the tool name (e.g. "bankentries").
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
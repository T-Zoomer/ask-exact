import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from datetime import date, datetime


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
            "odata_filter": self.to_odata_filter_url(),
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


    def validate(self, toolbox: 'ExactToolbox' = None) -> Optional[Dict[str, Any]]:
        """
        Validate the intent against available tools and fields.
        
        Returns:
            Error dict if validation fails, None if valid
        """
        # Use provided toolbox or global toolbox
        if toolbox is None:
            # Import here to avoid circular import
            from .exact_toolbox import exact_toolbox
            toolbox = exact_toolbox
            
        # Validate tool_call
        if not self.tool_call:
            return {"error": "Intent is missing tool_call"}
        
        # Check if tool exists
        available_tools = [tool["name"] for tool in toolbox.tools]
        
        if self.tool_call not in available_tools:
            return {
                "error": f"Tool '{self.tool_call}' not found. Available tools are: {', '.join(available_tools)}",
                "available_tools": available_tools,
                "requested_tool": self.tool_call
            }
        
        # Find tool config for field validation
        tool_config = None
        for tool in toolbox.tools:
            if tool["name"] == self.tool_call:
                tool_config = tool
                break
        
        # Validate filter fields
        if self.filters and tool_config:
            available_fields = tool_config.get("fields", {})
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
                    "endpoint": tool_config.get("name", "unknown")
                }
        
        return None


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


    def to_odata_filter_url(self) -> str:
        """
        Converts current filters into an OData $filter string, to be appended to url.
        Always joins multiple filters with AND.
        """
        if not self.filters:
            return ""
        
        parts = [self._render_filter(f) for f in self.filters]
        odata_filter = " and ".join(f"({p})" for p in parts)
        
        # URL encode the filter and return as query parameter
        from urllib.parse import quote
        encoded_filter = quote(odata_filter)
        return f"?$filter={encoded_filter}"
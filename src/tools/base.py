"""
Base types for the tool system.

Every tool in the assistant implements a simple contract:
  - Metadata (name, description, parameters, permission level)
  - An async execute function: arguments → ToolResult

These types are shared across the registry, the agent core, and tool
implementations to keep interfaces stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PermissionLevel(Enum):
    """How much trust a tool requires before execution."""

    SAFE = "safe"
    """Auto-execute without asking the user."""

    CONFIRMATION_REQUIRED = "confirmation"
    """Ask the user for explicit confirmation before executing."""

    DANGEROUS = "dangerous"
    """Require explicit approval, log heavily, warn the user."""


@dataclass
class ToolParameter:
    """Describes one parameter of a tool."""

    name: str
    type: str  # "string", "integer", "float", "boolean"
    description: str
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


@dataclass
class ToolResult:
    """
    The structured result of a tool execution.

    Every tool returns this, whether it succeeds or fails.
    """

    success: bool
    message: str = ""
    data: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": self.success,
            "message": self.message,
        }
        if self.data is not None:
            result["data"] = self.data
        if self.error is not None:
            result["error"] = self.error
        return result


@dataclass
class ToolDefinition:
    """
    Full metadata for a registered tool.

    This is what the agent core and Laya question definitions see.
    The execute callable is stored in the registry, not exposed to the model.
    """

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    permission: PermissionLevel = PermissionLevel.SAFE
    category: str = "general"
    enabled: bool = True

    def to_schema(self) -> dict[str, Any]:
        """Return a compact schema for Laya question criteria."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                p.name: {"type": p.type, "description": p.description}
                for p in self.parameters
            },
        }

    def to_criteria_entry(self) -> str:
        """One-line description for use as a Laya choice criterion."""
        return self.description

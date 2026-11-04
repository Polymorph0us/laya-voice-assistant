"""
Central tool registry.

Tools register themselves via the @register decorator. The registry provides:
  - Tool lookup by name
  - Tool definitions for Laya question schemas
  - Permission checks
  - Execution with structured logging

Design rule: the registry is the ONLY path to tool execution.
Nothing bypasses it.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Callable, Coroutine

from src.tools.base import (
    PermissionLevel,
    ToolDefinition,
    ToolParameter,
    ToolResult,
)
from src.utils.logger import get_logger, log_event

logger = get_logger("tools.registry")


# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------

_TOOLS: dict[str, _RegisteredTool] = {}


class _RegisteredTool:
    """Internal wrapper around a tool function + its metadata."""

    __slots__ = ("definition", "func")

    def __init__(self, definition: ToolDefinition, func: Callable[..., Any]):
        self.definition = definition
        self.func = func

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool function, adapting sync functions to async."""
        try:
            if asyncio.iscoroutinefunction(self.func):
                return await self.func(**kwargs)
            else:
                # Run sync functions in a thread to avoid blocking
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, lambda: self.func(**kwargs))
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
                message=f"Tool '{self.definition.name}' failed",
            )


# ---------------------------------------------------------------------------
# Registration decorator
# ---------------------------------------------------------------------------

def register(
    name: str,
    description: str,
    permission: PermissionLevel = PermissionLevel.SAFE,
    category: str = "general",
    parameters: list[ToolParameter] | None = None,
) -> Callable:
    """
    Decorator to register a function as a tool.

    Usage:
        @register(
            name="open_app",
            description="Open an installed application",
            permission=PermissionLevel.SAFE,
            category="apps",
            parameters=[
                ToolParameter(name="app_name", type="string",
                              description="Name of the application to open"),
            ],
        )
        def open_app(app_name: str) -> ToolResult:
            ...
    """
    def decorator(func: Callable) -> Callable:
        params = parameters or _extract_parameters(func)
        definition = ToolDefinition(
            name=name,
            description=description,
            parameters=params,
            permission=permission,
            category=category,
        )
        _TOOLS[name] = _RegisteredTool(definition, func)
        return func

    return decorator


def register_tool_instance(definition: ToolDefinition, func: Callable) -> None:
    """
    Register a dynamically constructed tool definition and callable.
    Used by MCP (Model Context Protocol) client and runtime plugins.
    """
    _TOOLS[definition.name] = _RegisteredTool(definition, func)
    logger.info(f"Registered dynamic tool: '{definition.name}' ({definition.category})")


def _extract_parameters(func: Callable) -> list[ToolParameter]:
    """Auto-extract parameters from function signature and type hints."""
    sig = inspect.signature(func)
    params: list[ToolParameter] = []

    type_map = {
        str: "string",
        int: "integer",
        float: "float",
        bool: "boolean",
    }

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        param_type = "string"
        if param.annotation != inspect.Parameter.empty:
            param_type = type_map.get(param.annotation, "string")

        params.append(
            ToolParameter(
                name=param_name,
                type=param_type,
                description=param_name.replace("_", " "),
                required=param.default == inspect.Parameter.empty,
                default=(
                    param.default
                    if param.default != inspect.Parameter.empty
                    else None
                ),
            )
        )

    return params


_TOOLS_LOADED = False


def ensure_tools_loaded() -> None:
    """Ensure all default tool modules are imported and registered."""
    global _TOOLS_LOADED
    if _TOOLS_LOADED:
        return
    _TOOLS_LOADED = True
    try:
        import src.tools.app_tools
        import src.tools.system_tools
        import src.tools.web_tools
        import src.tools.browser_tools
        import src.tools.media_tools
        import src.tools.productivity_tools
        import src.tools.github_tools
        import src.tools.perception_tools
        import src.core.memory
        import src.tools.scaffold_tools
        import src.tools.shell_tools
        import src.tools.disk_analysis_tools
    except Exception as e:
        logger.error(f"Failed to auto-import tools: {e}")


# ---------------------------------------------------------------------------
# Registry access
# ---------------------------------------------------------------------------

def get_tool(name: str) -> _RegisteredTool | None:
    """Look up a registered tool by name."""
    ensure_tools_loaded()
    return _TOOLS.get(name)


def get_all_tools() -> dict[str, ToolDefinition]:
    """Return definitions of all registered tools."""
    ensure_tools_loaded()
    return {name: t.definition for name, t in _TOOLS.items() if t.definition.enabled}


def get_tool_names() -> list[str]:
    """Return names of all enabled tools."""
    ensure_tools_loaded()
    return [name for name, t in _TOOLS.items() if t.definition.enabled]


def get_tool_criteria() -> dict[str, str]:
    """
    Build a criteria dict for a Laya 'choice' question.

    Returns:
        {"open_app": "Open an installed application", ...}
    """
    ensure_tools_loaded()
    return {
        name: t.definition.to_criteria_entry()
        for name, t in _TOOLS.items()
        if t.definition.enabled
    }


async def execute_tool(name: str, arguments: dict[str, Any]) -> ToolResult:
    """
    Execute a tool by name with the given arguments.

    This is the ONLY sanctioned path to tool execution.
    All calls are logged.
    """
    ensure_tools_loaded()
    tool = _TOOLS.get(name)
    if tool is None:
        return ToolResult(
            success=False,
            error=f"Unknown tool: {name}",
            message=f"No tool named '{name}' is registered",
        )

    if not tool.definition.enabled:
        return ToolResult(
            success=False,
            error=f"Tool '{name}' is disabled",
            message=f"Tool '{name}' is currently disabled",
        )

    start = time.perf_counter()
    log_event(
        logger,
        f"Executing tool: {name}",
        tool=name,
        arguments=arguments,
        permission=tool.definition.permission.value,
    )

    result = await tool.execute(**arguments)
    elapsed_ms = (time.perf_counter() - start) * 1000

    log_event(
        logger,
        f"Tool result: {name}",
        tool=name,
        status="success" if result.success else "failure",
        latency_ms=round(elapsed_ms, 1),
        result=result.to_dict(),
    )

    return result


def get_permission(name: str) -> PermissionLevel | None:
    """Get the permission level for a tool."""
    tool = _TOOLS.get(name)
    return tool.definition.permission if tool else None

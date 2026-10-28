"""
Model Context Protocol (MCP) Client Manager — Laya Assistant.

Implements the official Model Context Protocol (v2024-11-05) client over STDIO.
Connects to local or external MCP servers (e.g. Filesystem, GitHub, Calendar, Notion, Postgres),
automatically queries their tool definitions via `tools/list`, and dynamically registers
them directly into Laya's tool registry.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.tools.base import PermissionLevel, ToolDefinition, ToolParameter, ToolResult
from src.tools.registry import register_tool_instance
from src.utils.logger import get_logger

logger = get_logger("core.mcp")


class McpServerConnection:
    """Manages an active STDIO connection to a single MCP server subprocess."""

    def __init__(self, name: str, command: str, args: list[str], env: dict[str, str] | None = None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env or {}
        self.process: Optional[asyncio.subprocess.Process] = None
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._next_id = 1
        self._reader_task: Optional[asyncio.Task] = None
        self.discovered_tools: list[str] = []

    async def start(self) -> bool:
        """Spawn the server process and complete the MCP initialization handshake."""
        # Check command executable existence
        cmd_path = shutil.which(self.command)
        if not cmd_path:
            logger.warning(f"MCP server '{self.name}' command '{self.command}' not found on system PATH.")
            return False

        full_env = os.environ.copy()
        full_env.update(self.env)

        try:
            logger.info(f"Starting MCP server '{self.name}' ({self.command} {' '.join(self.args)})...")
            self.process = await asyncio.create_subprocess_exec(
                cmd_path,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=full_env,
            )

            # Start background stdout reader
            self._reader_task = asyncio.create_task(self._read_stdout_loop())

            # Start background stderr logger
            asyncio.create_task(self._log_stderr_loop())

            # 1. Handshake: initialize
            init_res = await self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "LayaAssistant", "version": "1.0.0"},
                },
                timeout=10.0,
            )
            if not init_res:
                logger.warning(f"MCP server '{self.name}' failed initialization handshake.")
                return False

            # 2. Handshake: notifications/initialized
            await self._send_notification("notifications/initialized", {})

            # 3. Discover available tools
            await self._discover_and_register_tools()
            logger.info(
                f"MCP server '{self.name}' connected successfully with {len(self.discovered_tools)} tools: "
                f"{self.discovered_tools}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start MCP server '{self.name}': {e}")
            await self.stop()
            return False

    async def _send_request(self, method: str, params: dict, timeout: float = 15.0) -> Any:
        """Send a JSON-RPC request and await response."""
        if not self.process or not self.process.stdin:
            return None

        req_id = self._next_id
        self._next_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_requests[req_id] = future

        msg = json.dumps(payload) + "\n"
        self.process.stdin.write(msg.encode("utf-8"))
        await self.process.stdin.drain()

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            logger.warning(f"MCP server '{self.name}' request '{method}' timed out after {timeout}s.")
            return None
        except Exception as e:
            self._pending_requests.pop(req_id, None)
            logger.error(f"MCP server '{self.name}' request error: {e}")
            return None

    async def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        if not self.process or not self.process.stdin:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        msg = json.dumps(payload) + "\n"
        self.process.stdin.write(msg.encode("utf-8"))
        await self.process.stdin.drain()

    async def _read_stdout_loop(self) -> None:
        """Read newline-delimited JSON-RPC messages from server stdout."""
        while self.process and self.process.stdout and not self.process.stdout.at_eof():
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break
                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                req_id = data.get("id")
                if req_id in self._pending_requests:
                    future = self._pending_requests.pop(req_id)
                    if "error" in data:
                        future.set_exception(RuntimeError(data["error"].get("message", "MCP error")))
                    else:
                        future.set_result(data.get("result"))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"MCP reader exception: {e}")
                break

    async def _log_stderr_loop(self) -> None:
        """Log stderr output from server for diagnostics."""
        while self.process and self.process.stderr and not self.process.stderr.at_eof():
            try:
                line = await self.process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    logger.debug(f"[MCP:{self.name}:stderr] {text}")
            except Exception:
                break

    async def _discover_and_register_tools(self) -> None:
        """Fetch server tools and dynamically mount them into Laya's registry."""
        res = await self._send_request("tools/list", {})
        if not res or "tools" not in res:
            return

        for tool_info in res["tools"]:
            raw_name = tool_info.get("name", "")
            description = tool_info.get("description", "")
            input_schema = tool_info.get("inputSchema", {})

            # Prefix tool name with server name to avoid collision (e.g. mcp_filesystem_read_file)
            prefixed_name = f"mcp_{self.name}_{raw_name}"

            # Convert JSON schema properties to ToolParameter list
            parameters: list[ToolParameter] = []
            properties = input_schema.get("properties", {})
            required_fields = set(input_schema.get("required", []))

            for prop_name, prop_def in properties.items():
                p_type = prop_def.get("type", "string")
                if p_type == "number":
                    p_type = "float"
                elif p_type not in ("string", "integer", "boolean", "float"):
                    p_type = "string"

                parameters.append(
                    ToolParameter(
                        name=prop_name,
                        type=p_type,
                        description=prop_def.get("description", prop_name),
                        required=prop_name in required_fields,
                    )
                )

            # Determine permission: destructive actions require confirmation
            is_destructive = any(
                kw in raw_name.lower()
                for kw in ["delete", "remove", "write", "overwrite", "drop", "terminate"]
            )
            perm = PermissionLevel.DANGEROUS if is_destructive else PermissionLevel.SAFE

            definition = ToolDefinition(
                name=prefixed_name,
                description=f"[{self.name.upper()} MCP] {description}",
                parameters=parameters,
                permission=perm,
                category="mcp",
            )

            # Create closure for tool execution
            async def _make_caller(server=self, t_name=raw_name, p_name=prefixed_name, **kwargs) -> ToolResult:
                logger.info(f"Calling MCP tool '{t_name}' on server '{server.name}' with args {kwargs}")
                call_res = await server._send_request(
                    "tools/call",
                    {"name": t_name, "arguments": kwargs},
                    timeout=30.0,
                )
                if not call_res:
                    return ToolResult(
                        success=False,
                        error="No response from MCP server",
                        message=f"MCP tool '{t_name}' failed to execute.",
                    )

                content_list = call_res.get("content", [])
                text_outputs = []
                for item in content_list:
                    if item.get("type") == "text":
                        text_outputs.append(item.get("text", ""))

                combined_text = "\n".join(text_outputs) if text_outputs else "Operation completed."
                is_error = call_res.get("isError", False)
                return ToolResult(
                    success=not is_error,
                    message=combined_text[:500],
                    data={"mcp_server": server.name, "tool": t_name, "raw": call_res},
                )

            # Register dynamic tool into global Laya registry
            register_tool_instance(definition, _make_caller)
            self.discovered_tools.append(prefixed_name)

    async def stop(self) -> None:
        """Cleanly terminate the server subprocess."""
        if self._reader_task:
            self._reader_task.cancel()
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None


class McpClientManager:
    """Singleton manager that discovers and orchestrates all MCP server connections."""

    def __init__(self, config_path: Path | str = "config/mcp_servers.json"):
        self.config_path = Path(config_path)
        self.servers: dict[str, McpServerConnection] = {}

    def load_config(self) -> dict:
        """Read MCP server configurations from file."""
        if not self.config_path.exists():
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load MCP config '{self.config_path}': {e}")
            return {}

    async def start_all(self) -> int:
        """Start and initialize all configured MCP servers."""
        config_data = self.load_config()
        server_defs = config_data.get("mcpServers", {})
        if not server_defs:
            logger.info("No MCP servers configured in mcp_servers.json.")
            return 0

        connected_count = 0
        for name, s_cfg in server_defs.items():
            if not s_cfg.get("enabled", True):
                logger.info(f"MCP server '{name}' is disabled in configuration. Skipping.")
                continue

            command = s_cfg.get("command", "")
            args = s_cfg.get("args", [])
            env = s_cfg.get("env", {})
            if not command:
                continue

            conn = McpServerConnection(name, command, args, env)
            success = await conn.start()
            if success:
                self.servers[name] = conn
                connected_count += 1

        logger.info(f"MCP Manager: {connected_count}/{len(server_defs)} servers connected.")
        return connected_count

    async def stop_all(self) -> None:
        """Stop all running MCP servers."""
        for name, conn in self.servers.items():
            await conn.stop()
        self.servers.clear()

    def get_all_tools(self) -> list[str]:
        """Return all active MCP tool names."""
        all_tools = []
        for conn in self.servers.values():
            all_tools.extend(conn.discovered_tools)
        return all_tools


# Global singleton instance
mcp_manager = McpClientManager()

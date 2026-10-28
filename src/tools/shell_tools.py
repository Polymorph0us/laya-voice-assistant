"""
Shell execution tool: run_shell_command.

Provides Laya with the capability to execute shell/terminal commands (e.g. git,
npm, pip, python scripts, system diagnostics) on behalf of the user.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from src.tools.base import PermissionLevel, ToolParameter, ToolResult
from src.tools.registry import register
from src.utils.logger import get_logger

logger = get_logger("tools.shell")


@register(
    name="run_shell_command",
    description="Execute a shell or terminal command (e.g. git status, git commit, python scripts, diagnostics)",
    permission=PermissionLevel.SAFE,
    category="developer",
    parameters=[
        ToolParameter(
            name="command",
            type="string",
            description="The command line string to execute (e.g. 'git status', 'git add .', 'dir')",
        ),
        ToolParameter(
            name="cwd",
            type="string",
            description="Optional working directory to run the command in. Defaults to the project root.",
            required=False,
            default="",
        ),
        ToolParameter(
            name="timeout",
            type="integer",
            description="Maximum execution time in seconds (default 30, max 120)",
            required=False,
            default=30,
        ),
    ],
)
def run_shell_command(command: str, cwd: str = "", timeout: int = 30, **kwargs: Any) -> ToolResult:
    """Execute a shell command safely with timeout and output capture."""
    cmd_clean = command.strip()
    if not cmd_clean:
        return ToolResult(
            success=False,
            error="Empty command",
            message="No command specified to execute.",
        )

    # Determine working directory
    work_dir = Path.cwd()
    if cwd:
        custom_dir = Path(cwd.strip().strip("'\""))
        if custom_dir.is_dir():
            work_dir = custom_dir

    # Cap timeout
    timeout_val = max(1, min(int(timeout), 120))

    try:
        logger.info(f"Executing shell command: '{cmd_clean}' in '{work_dir}'")
        res = subprocess.run(
            cmd_clean,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(work_dir),
            timeout=timeout_val,
        )

        stdout = (res.stdout or "").strip()
        stderr = (res.stderr or "").strip()
        exit_code = res.returncode

        # Format readable summary
        output_snippet = stdout if stdout else (stderr if stderr else "(no output)")
        if len(output_snippet) > 800:
            output_snippet = output_snippet[:800] + "... [truncated]"

        if exit_code == 0:
            msg = f"Command succeeded (code 0):\n{output_snippet}"
        else:
            msg = f"Command exited with code {exit_code}:\n{output_snippet}"

        return ToolResult(
            success=(exit_code == 0),
            message=msg,
            data={
                "command": cmd_clean,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "cwd": str(work_dir),
            },
            error=stderr if exit_code != 0 else None,
        )

    except subprocess.TimeoutExpired:
        logger.warning(f"Shell command timed out after {timeout_val}s: '{cmd_clean}'")
        return ToolResult(
            success=False,
            error="Command timed out",
            message=f"Command '{cmd_clean}' timed out after {timeout_val} seconds.",
        )
    except Exception as e:
        logger.error(f"Error running shell command: {e}")
        return ToolResult(
            success=False,
            error=str(e),
            message=f"Failed to execute command '{cmd_clean}': {e}",
        )

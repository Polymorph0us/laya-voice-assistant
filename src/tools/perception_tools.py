"""
Perception & Computer Control Tools.

Provides sensory awareness and desktop automation:
- Active focused window detection (title & process name)
- Clipboard reading & writing (text inspection & copy)
- Active window typing / dictation
- Screen capture
- Lock PC
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.tools.base import PermissionLevel, ToolParameter, ToolResult
from src.tools.registry import register
from src.utils.logger import get_logger

logger = get_logger("tools.perception")

_SCREENSHOTS_DIR = Path("logs/screenshots")


def _get_active_window_info() -> dict[str, str]:
    """Retrieve active window title and process name via Win32 API."""
    import ctypes
    from ctypes import wintypes
    import psutil

    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return {"title": "Unknown", "process": "Unknown"}

    # Get title
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if length > 0:
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
    else:
        title = "Untitled Window"

    # Get process ID and name
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process_name = "Unknown"
    try:
        if pid.value:
            proc = psutil.Process(pid.value)
            process_name = proc.name()
    except Exception:
        pass

    return {"title": title, "process": process_name}


@register(
    name="get_active_window",
    description="Get the title and application name of the currently focused window on the desktop",
    permission=PermissionLevel.SAFE,
    category="perception",
)
def get_active_window() -> ToolResult:
    """Identify which app or window the user is currently working in."""
    try:
        info = _get_active_window_info()
        title = info["title"]
        proc = info["process"]
        return ToolResult(
            success=True,
            message=f"You are currently in {proc} with the window titled '{title}'.",
            data=info,
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=str(e),
            message="Could not detect active window.",
        )


@register(
    name="get_clipboard_text",
    description="Read and inspect the current text stored in the Windows clipboard",
    permission=PermissionLevel.SAFE,
    category="perception",
)
def get_clipboard_text() -> ToolResult:
    """Get clipboard text contents."""
    try:
        import pyperclip
        text = pyperclip.paste()
        if not text:
            return ToolResult(
                success=True,
                message="Your clipboard is currently empty.",
                data={"text": ""},
            )

        preview = text.strip()
        if len(preview) > 300:
            preview = preview[:297] + "..."

        return ToolResult(
            success=True,
            message=f"Clipboard content: {preview}",
            data={"text": text, "preview": preview, "length": len(text)},
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=str(e),
            message="Failed to read clipboard.",
        )


@register(
    name="copy_to_clipboard",
    description="Copy text to the Windows clipboard",
    permission=PermissionLevel.SAFE,
    category="perception",
    parameters=[
        ToolParameter(
            name="text",
            type="string",
            description="The text to copy to the clipboard",
        ),
    ],
)
def copy_to_clipboard(text: str) -> ToolResult:
    """Copy text to clipboard."""
    try:
        import pyperclip
        pyperclip.copy(text)
        preview = text.strip()
        if len(preview) > 60:
            preview = preview[:57] + "..."
        return ToolResult(
            success=True,
            message=f"Copied '{preview}' to clipboard.",
            data={"text": text},
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=str(e),
            message="Failed to copy to clipboard.",
        )


@register(
    name="type_into_active_window",
    description="Type or dictate text into the currently active focused application window",
    permission=PermissionLevel.SAFE,
    category="perception",
    parameters=[
        ToolParameter(
            name="text",
            type="string",
            description="The text to type into the focused window",
        ),
    ],
)
def type_into_active_window(text: str) -> ToolResult:
    """Type text into active focused application window."""
    try:
        import keyboard
        time.sleep(0.2)  # Short pause to ensure focus
        keyboard.write(text)
        return ToolResult(
            success=True,
            message=f"Typed text into active window.",
            data={"text": text},
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=str(e),
            message="Failed to type text into active window.",
        )


@register(
    name="take_screenshot",
    description="Take a screenshot of the computer screen and save it to the logs directory",
    permission=PermissionLevel.SAFE,
    category="perception",
    parameters=[
        ToolParameter(
            name="filename",
            type="string",
            description="Optional filename for the screenshot",
            required=False,
        ),
    ],
)
def take_screenshot(filename: str = "") -> ToolResult:
    """Capture full screen image."""
    try:
        from PIL import ImageGrab
        _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
        elif not filename.endswith(".png"):
            filename = f"{filename}.png"

        save_path = _SCREENSHOTS_DIR / filename
        img = ImageGrab.grab()
        img.save(str(save_path))
        return ToolResult(
            success=True,
            message=f"Screenshot captured and saved to {filename}.",
            data={"path": str(save_path)},
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=str(e),
            message="Failed to take screenshot.",
        )


@register(
    name="lock_pc",
    description="Lock the computer immediately (Windows Lock Workstation)",
    permission=PermissionLevel.SAFE,
    category="system",
)
def lock_pc() -> ToolResult:
    """Lock Windows PC."""
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return ToolResult(
            success=True,
            message="Locking your PC.",
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=str(e),
            message="Failed to lock workstation.",
        )

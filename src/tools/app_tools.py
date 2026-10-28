"""
Application management tools: open_app, close_app.

These are SAFE-permission tools that launch or terminate desktop applications.
App names are resolved through a configurable alias map.
"""

from __future__ import annotations

import shutil
import subprocess
import platform
import difflib

from src.tools.base import PermissionLevel, ToolParameter, ToolResult
from src.tools.registry import register


# ---------------------------------------------------------------------------
# App alias map — canonical name → launch commands by platform
# Windows-first, with Linux placeholders for future cross-platform support.
# ---------------------------------------------------------------------------

_APP_ALIASES: dict[str, dict[str, list[str]]] = {
    "vscode": {
        "Windows": ["code"],
        "Linux": ["code"],
    },
    "visual studio code": {
        "Windows": ["code"],
        "Linux": ["code"],
    },
    "chrome": {
        "Windows": ["start", "chrome"],
        "Linux": ["google-chrome"],
    },
    "google chrome": {
        "Windows": ["start", "chrome"],
        "Linux": ["google-chrome"],
    },
    "firefox": {
        "Windows": ["start", "firefox"],
        "Linux": ["firefox"],
    },
    "notepad": {
        "Windows": ["notepad"],
        "Linux": ["gedit"],
    },
    "calculator": {
        "Windows": ["calc"],
        "Linux": ["gnome-calculator"],
    },
    "file explorer": {
        "Windows": ["explorer"],
        "Linux": ["nautilus"],
    },
    "explorer": {
        "Windows": ["explorer"],
        "Linux": ["nautilus"],
    },
    "task manager": {
        "Windows": ["taskmgr"],
        "Linux": ["gnome-system-monitor"],
    },
    "terminal": {
        "Windows": ["wt"],
        "Linux": ["gnome-terminal"],
    },
    "powershell": {
        "Windows": ["powershell"],
        "Linux": ["pwsh"],
    },
    "cmd": {
        "Windows": ["cmd"],
        "Linux": ["bash"],
    },
    "spotify": {
        "Windows": ["start", "spotify:"],
        "Linux": ["spotify"],
    },
    "discord": {
        "Windows": ["start", "", "discord"],  # start "" "discord" for UWP
        "Linux": ["discord"],
    },
    "settings": {
        "Windows": ["start", "ms-settings:"],
        "Linux": ["gnome-control-center"],
    },
    "edge": {
        "Windows": ["start", "msedge"],
        "Linux": ["microsoft-edge"],
    },
    "microsoft edge": {
        "Windows": ["start", "msedge"],
        "Linux": ["microsoft-edge"],
    },
    "brave": {
        "Windows": ["start", "brave"],
        "Linux": ["brave-browser"],
    },
    "brave browser": {
        "Windows": ["start", "brave"],
        "Linux": ["brave-browser"],
    },
}


def _find_windows_app(name: str) -> str | None:
    """Find installed application via Start Menu shortcuts or registry App Paths."""
    import os
    from pathlib import Path

    name_clean = name.lower().strip()

    # 1. Start Menu shortcuts
    start_dirs = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]
    for sdir in start_dirs:
        if sdir.exists():
            for lnk in sdir.rglob("*.lnk"):
                if name_clean in lnk.stem.lower():
                    return str(lnk)

    # 2. Registry App Paths
    try:
        import winreg
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as key:
                    count = winreg.QueryInfoKey(key)[0]
                    for i in range(count):
                        subkey_name = winreg.EnumKey(key, i)
                        if name_clean in subkey_name.lower():
                            with winreg.OpenKey(key, subkey_name) as sub:
                                val, _ = winreg.QueryValueEx(sub, "")
                                if val and os.path.exists(val):
                                    return val
            except Exception:
                pass
    except Exception:
        pass

    # 3. LocalAppData programs directory (e.g. Discord, Slack, etc.)
    local_app = Path(os.environ.get("LOCALAPPDATA", ""))
    for candidate in [
        local_app / "Discord" / "Discord.exe",
        local_app / name_clean / f"{name_clean}.exe",
        local_app / "Programs" / name_clean / f"{name_clean}.exe",
    ]:
        if candidate.exists():
            return str(candidate)

    return None


def _resolve_app(app_name: str) -> list[str] | str | None:
    """
    Resolve an application name to a launch command or file path.

    Tries, in order:
      1. Exact match in alias map (case-insensitive)
      2. Windows Start Menu and App Paths auto-discovery
      3. Direct executable check (on PATH)
      4. Fuzzy match against aliases
      5. Return None if unresolvable
    """
    import os
    system = platform.system()
    key = app_name.lower().strip()

    # 1. Alias map
    if key in _APP_ALIASES:
        cmd = _APP_ALIASES[key].get(system)
        if cmd:
            # Special check for discord on Windows: verify executable or shortcut
            if key == "discord" and system == "Windows":
                found = _find_windows_app("discord")
                if found:
                    return found
            return cmd

    # 1.5 Windows auto-discovery for any installed desktop app
    if system == "Windows":
        found = _find_windows_app(key)
        if found:
            return found

    # 2. Direct executable check
    if shutil.which(key):
        return [key]

    # 3. Fuzzy match against aliases (e.g. handles typos like "dicord" -> "discord")
    matches = difflib.get_close_matches(key, _APP_ALIASES.keys(), n=1, cutoff=0.6)
    if matches:
        return _APP_ALIASES[matches[0]].get(system)

    return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@register(
    name="open_app",
    description="Open or launch an installed application on the computer",
    permission=PermissionLevel.SAFE,
    category="apps",
    parameters=[
        ToolParameter(
            name="app_name",
            type="string",
            description="Name of the application to open (e.g., 'vscode', 'chrome', 'notepad', 'discord')",
        ),
    ],
)
def open_app(app_name: str) -> ToolResult:
    """Open an application by its common name."""
    import os
    target = _resolve_app(app_name)

    if target is None:
        return ToolResult(
            success=False,
            error=f"Could not resolve application: '{app_name}'",
            message=f"I don't know how to open '{app_name}'. "
                    f"You can add it to the app aliases in your settings.",
        )

    try:
        # If it's a specific file path or shortcut (.lnk), use native os.startfile on Windows
        if isinstance(target, str) and (target.endswith(".lnk") or os.path.exists(target)):
            if hasattr(os, "startfile"):
                os.startfile(target)
            else:
                subprocess.Popen([target])
            return ToolResult(
                success=True,
                message=f"Opening {app_name}...",
                data={"app": app_name, "path": target},
            )

        # If it's a command list (e.g. ['calc'], ['code'])
        command = [target] if isinstance(target, str) else target
        use_shell = platform.system() == "Windows"
        subprocess.Popen(command, shell=use_shell)
        return ToolResult(
            success=True,
            message=f"Opening {app_name}...",
            data={"app": app_name, "command": command},
        )
    except FileNotFoundError:
        return ToolResult(
            success=False,
            error=f"Executable not found for '{app_name}'",
            message=f"The command for '{app_name}' was not found on this system.",
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"{type(e).__name__}: {e}",
            message=f"Failed to open '{app_name}'.",
        )


@register(
    name="close_app",
    description="Close or terminate a running application",
    permission=PermissionLevel.CONFIRMATION_REQUIRED,
    category="apps",
    parameters=[
        ToolParameter(
            name="app_name",
            type="string",
            description="Name of the application to close",
        ),
    ],
)
def close_app(app_name: str) -> ToolResult:
    """Close a running application by name (Windows: taskkill, Linux: pkill)."""
    system = platform.system()

    # Map common names to process names
    process_map: dict[str, str] = {
        "vscode": "Code.exe" if system == "Windows" else "code",
        "visual studio code": "Code.exe" if system == "Windows" else "code",
        "chrome": "chrome.exe" if system == "Windows" else "chrome",
        "google chrome": "chrome.exe" if system == "Windows" else "chrome",
        "firefox": "firefox.exe" if system == "Windows" else "firefox",
        "notepad": "notepad.exe" if system == "Windows" else "gedit",
        "spotify": "Spotify.exe" if system == "Windows" else "spotify",
        "discord": "Discord.exe" if system == "Windows" else "discord",
    }

    key = app_name.lower().strip()
    process_name = process_map.get(key, key)

    try:
        if system == "Windows":
            subprocess.run(
                ["taskkill", "/IM", process_name, "/F"],
                capture_output=True,
                text=True,
                check=True,
            )
        else:
            subprocess.run(
                ["pkill", "-f", process_name],
                capture_output=True,
                text=True,
                check=True,
            )

        return ToolResult(
            success=True,
            message=f"Closed {app_name}.",
            data={"app": app_name, "process": process_name},
        )
    except subprocess.CalledProcessError:
        return ToolResult(
            success=False,
            error=f"Process '{process_name}' not found or could not be killed",
            message=f"Could not close '{app_name}'. It may not be running.",
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"{type(e).__name__}: {e}",
            message=f"Failed to close '{app_name}'.",
        )

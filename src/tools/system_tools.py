"""
System tools: get_system_info, change_volume.

SAFE-permission tools that query or adjust system state.
"""

from __future__ import annotations

import platform
import subprocess
import psutil

from src.tools.base import PermissionLevel, ToolParameter, ToolResult
from src.tools.registry import register


@register(
    name="get_system_info",
    description="Get current system information including CPU, memory, disk, and OS details",
    permission=PermissionLevel.SAFE,
    category="system",
)
def get_system_info() -> ToolResult:
    """Gather system information without any external dependencies beyond psutil."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        battery = psutil.sensors_battery()

        info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_usage_percent": cpu_percent,
            "memory": {
                "total_gb": round(memory.total / (1024**3), 1),
                "used_gb": round(memory.used / (1024**3), 1),
                "available_gb": round(memory.available / (1024**3), 1),
                "percent_used": memory.percent,
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 1),
                "used_gb": round(disk.used / (1024**3), 1),
                "free_gb": round(disk.free / (1024**3), 1),
                "percent_used": round(disk.percent, 1),
            },
        }

        if battery:
            info["battery"] = {
                "percent": battery.percent,
                "plugged_in": battery.power_plugged,
            }

        # Build a readable summary
        summary_parts = [
            f"{info['os']} {info['os_version']}",
            f"CPU: {cpu_percent}%",
            f"RAM: {memory.percent}% ({info['memory']['used_gb']}/{info['memory']['total_gb']} GB)",
            f"Disk: {disk.percent}% ({info['disk']['used_gb']}/{info['disk']['total_gb']} GB)",
        ]
        if battery:
            plug = "plugged in" if battery.power_plugged else "on battery"
            summary_parts.append(f"Battery: {battery.percent}% ({plug})")

        return ToolResult(
            success=True,
            message=", ".join(summary_parts),
            data=info,
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"{type(e).__name__}: {e}",
            message="Failed to retrieve system information.",
        )


def _get_endpoint_volume():
    """Get Windows master endpoint volume using pycaw WASAPI (<1ms)."""
    try:
        import ctypes
        ctypes.windll.ole32.CoInitialize(None)
    except Exception:
        pass
    try:
        from pycaw.pycaw import AudioUtilities
        speakers = AudioUtilities.GetSpeakers()
        if speakers:
            return speakers.EndpointVolume
    except Exception:
        pass
    return None


def _send_volume_key(vk_code: int, repeat: int = 1) -> None:
    """Send hardware media key press instantly via Win32 keybd_event (<0.01ms, 0 subprocesses)."""
    try:
        import ctypes
        KEYEVENTF_KEYUP = 0x0002
        for _ in range(repeat):
            ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
    except Exception:
        pass


@register(
    name="change_volume",
    description="Adjust the system audio volume (up, down, mute, unmute, or set to a specific level)",
    permission=PermissionLevel.SAFE,
    category="system",
    parameters=[
        ToolParameter(
            name="action",
            type="string",
            description="Volume action: 'up', 'down', 'mute', 'unmute', or a number 0-100",
        ),
    ],
)
def change_volume(action: str) -> ToolResult:
    """
    Change system volume on Windows natively via pycaw / WASAPI (<1ms) or keybd_event.

    Supports:
      - 'up' / 'increase' → increase by ~6%
      - 'down' / 'decrease' → decrease by ~6%
      - 'mute'   → mute volume
      - 'unmute' → unmute volume
      - '0'-'100' → set exact percentage instantly
    """
    system = platform.system()

    if system != "Windows":
        return ToolResult(
            success=False,
            error="Volume control currently only supported on Windows",
            message="Volume control is not yet implemented for this OS.",
        )

    action_lower = action.lower().strip()
    endpoint = _get_endpoint_volume()

    # 1. Volume Up
    if action_lower in ("up", "louder", "increase", "raise"):
        if endpoint:
            try:
                cur = endpoint.GetMasterVolumeLevelScalar()
                new_vol = min(1.0, cur + 0.06)
                endpoint.SetMasterVolumeLevelScalar(new_vol, None)
                percent = int(round(new_vol * 100))
                return ToolResult(
                    success=True,
                    message=f"Volume increased to {percent}%.",
                    data={"level": percent},
                )
            except Exception:
                pass
        _send_volume_key(0xAF, repeat=3)
        return ToolResult(success=True, message="Volume increased.")

    # 2. Volume Down
    elif action_lower in ("down", "softer", "quieter", "lower", "decrease"):
        if endpoint:
            try:
                cur = endpoint.GetMasterVolumeLevelScalar()
                new_vol = max(0.0, cur - 0.06)
                endpoint.SetMasterVolumeLevelScalar(new_vol, None)
                percent = int(round(new_vol * 100))
                return ToolResult(
                    success=True,
                    message=f"Volume decreased to {percent}%.",
                    data={"level": percent},
                )
            except Exception:
                pass
        _send_volume_key(0xAE, repeat=3)
        return ToolResult(success=True, message="Volume decreased.")

    # 3. Mute
    elif action_lower == "mute":
        if endpoint:
            try:
                endpoint.SetMute(1, None)
                return ToolResult(success=True, message="Volume muted.", data={"muted": True})
            except Exception:
                pass
        _send_volume_key(0xAD)
        return ToolResult(success=True, message="Volume muted.")

    # 4. Unmute
    elif action_lower == "unmute":
        if endpoint:
            try:
                endpoint.SetMute(0, None)
                return ToolResult(success=True, message="Volume unmuted.", data={"muted": False})
            except Exception:
                pass
        _send_volume_key(0xAD)
        return ToolResult(success=True, message="Volume unmuted.")

    # 5. Set to specific percentage 0-100
    else:
        try:
            level = int(action_lower.replace("%", ""))
            if not 0 <= level <= 100:
                raise ValueError
        except ValueError:
            return ToolResult(
                success=False,
                error=f"Invalid volume action: '{action}'",
                message="Use 'up', 'down', 'mute', 'unmute', or a number 0-100.",
            )

        if endpoint:
            try:
                scalar = level / 100.0
                endpoint.SetMasterVolumeLevelScalar(scalar, None)
                return ToolResult(
                    success=True,
                    message=f"Volume set to {level}%.",
                    data={"level": level},
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    error=str(e),
                    message=f"Failed to set volume to {level}%.",
                )

        return ToolResult(
            success=False,
            error="pycaw endpoint unavailable for exact level",
            message="Could not set exact volume percentage.",
        )


_COMMON_TIMEZONES: dict[str, str] = {
    "japan": "Asia/Tokyo", "tokyo": "Asia/Tokyo",
    "london": "Europe/London", "uk": "Europe/London", "england": "Europe/London",
    "paris": "Europe/Paris", "france": "Europe/Paris",
    "berlin": "Europe/Berlin", "germany": "Europe/Berlin",
    "new york": "America/New_York", "nyc": "America/New_York",
    "california": "America/Los_Angeles", "los angeles": "America/Los_Angeles", "san francisco": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "india": "Asia/Kolkata", "delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata",
    "dubai": "Asia/Dubai", "uae": "Asia/Dubai",
    "sydney": "Australia/Sydney", "australia": "Australia/Sydney",
    "toronto": "America/Toronto", "canada": "America/Toronto",
    "singapore": "Asia/Singapore",
    "beijing": "Asia/Shanghai", "china": "Asia/Shanghai",
    "seoul": "Asia/Seoul", "korea": "Asia/Seoul",
    "moscow": "Europe/Moscow", "russia": "Europe/Moscow",
    "utc": "UTC", "gmt": "GMT",
}


@register(
    name="get_current_time",
    description="Get the current time, date, and day of week locally or for a specific city/country",
    permission=PermissionLevel.SAFE,
    category="system",
    parameters=[
        ToolParameter(
            name="location",
            type="string",
            description="Optional city, country, or timezone (e.g. 'Japan', 'Tokyo', 'London', 'New York'). Leave empty for local time.",
            required=False,
        ),
    ],
)
def get_current_time(location: str = "") -> ToolResult:
    """Retrieve current time and date for local system or a specific region."""
    from datetime import datetime
    import zoneinfo

    clean_loc = location.strip().lower()

    try:
        if not clean_loc or clean_loc in ("local", "here", "my time", "system"):
            now = datetime.now()
            time_str = now.strftime("%I:%M %p").lstrip("0")
            date_str = now.strftime("%A, %B %d, %Y")
            return ToolResult(
                success=True,
                message=f"It is {time_str} on {date_str}.",
                data={"time": time_str, "date": date_str, "location": "local"},
            )

        tz_key = _COMMON_TIMEZONES.get(clean_loc)
        if not tz_key:
            # Check if clean_loc itself is a valid IANA key
            try:
                tz = zoneinfo.ZoneInfo(clean_loc)
            except Exception:
                tz = None
        else:
            tz = zoneinfo.ZoneInfo(tz_key)

        if tz:
            now_loc = datetime.now(tz)
            time_str = now_loc.strftime("%I:%M %p").lstrip("0")
            date_str = now_loc.strftime("%A, %B %d, %Y")
            tz_abbr = now_loc.strftime("%Z")
            return ToolResult(
                success=True,
                message=f"The current time in {location.title()} is {time_str} ({tz_abbr}) on {date_str}.",
                data={"time": time_str, "date": date_str, "timezone": tz_abbr, "location": location},
            )
        else:
            now = datetime.now()
            time_str = now.strftime("%I:%M %p").lstrip("0")
            return ToolResult(
                success=True,
                message=f"I couldn't find the timezone for '{location}', but your local time is {time_str}.",
                data={"time": time_str, "location": "local"},
            )
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"{type(e).__name__}: {e}",
            message="Failed to retrieve time.",
        )


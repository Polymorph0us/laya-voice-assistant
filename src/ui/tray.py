"""
System Tray Icon & Desktop Presence for Laya Assistant.

Provides an escape hatch and control center:
- System tray icon in Windows notification area
- Right-click menu: Toggle UI, Mute, Open Settings, View Logs, Quit
- Runs in a non-blocking background daemon thread
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Callable

from src.utils.logger import get_logger

logger = get_logger("ui.tray")


def _create_tray_icon_image():
    """Generate a clean 64x64 purple/cyan glowing orb icon in memory."""
    from PIL import Image, ImageDraw

    size = (64, 64)
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Concentric glowing circles
    draw.ellipse([4, 4, 60, 60], fill=(138, 43, 226, 200))  # Purple base
    draw.ellipse([12, 12, 52, 52], fill=(0, 206, 209, 230))  # Cyan core
    draw.ellipse([22, 22, 42, 42], fill=(255, 255, 255, 255))  # White center shine

    return image


class LayaTray:
    """Manages the Windows system tray icon and options."""

    def __init__(
        self,
        on_toggle_ui: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
    ):
        self.on_toggle_ui = on_toggle_ui
        self.on_quit = on_quit
        self.is_muted = False
        self._icon = None
        self._thread = None

    def _open_settings(self, icon, item):
        """Open settings.yaml in default text editor."""
        settings_file = Path("config/settings.yaml").resolve()
        if settings_file.exists():
            os.startfile(str(settings_file))

    def _open_logs(self, icon, item):
        """Open logs folder in file explorer."""
        logs_dir = Path("logs").resolve()
        logs_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(logs_dir))

    def _toggle_mute(self, icon, item):
        """Toggle microphone mute status."""
        self.is_muted = not self.is_muted
        logger.info(f"Microphone {'muted' if self.is_muted else 'unmuted'} via tray icon.")

    def _action_toggle_ui(self, icon, item):
        if self.on_toggle_ui:
            self.on_toggle_ui()

    def _action_quit(self, icon, item):
        logger.info("Quit requested via system tray icon.")
        if self._icon:
            self._icon.stop()
        if self.on_quit:
            self.on_quit()
        else:
            os._exit(0)

    def start(self):
        """Start system tray icon in a background daemon thread."""
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Laya Assistant", lambda icon, item: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Toggle Orb Overlay", self._action_toggle_ui),
            pystray.MenuItem(
                lambda text: "Unmute Microphone" if self.is_muted else "Mute Microphone",
                self._toggle_mute,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Settings", self._open_settings),
            pystray.MenuItem("View Logs", self._open_logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Laya", self._action_quit),
        )

        icon_image = _create_tray_icon_image()
        self._icon = pystray.Icon("LayaAssistant", icon_image, "Laya Voice Assistant", menu)

        self._thread = threading.Thread(target=self._icon.run, daemon=True, name="TrayThread")
        self._thread.start()
        logger.info("System tray icon initialized.")

    def stop(self):
        if self._icon:
            self._icon.stop()


def start_tray_icon(
    on_toggle_ui: Callable[[], None] | None = None,
    on_quit: Callable[[], None] | None = None,
) -> LayaTray:
    """Convenience helper to launch tray icon."""
    tray = LayaTray(on_toggle_ui=on_toggle_ui, on_quit=on_quit)
    tray.start()
    return tray

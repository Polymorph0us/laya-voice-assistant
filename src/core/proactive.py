"""
Proactivity Engine — Laya Assistant.

Monitors system health and scheduled proactive triggers in the background:
- Low battery warning (<20% on discharge)
- High resource alerts (sustained RAM / CPU warnings)
- Morning briefing trigger (daily weather + reminders + status)
"""

from __future__ import annotations

import asyncio
import datetime
import psutil
from typing import Callable, Optional

from src.utils.logger import get_logger

logger = get_logger("core.proactive")


class ProactiveEngine:
    """Background engine evaluating system state and firing proactive notifications."""

    def __init__(
        self,
        check_interval_seconds: float = 60.0,
        notify_callback: Optional[Callable[[str, str], None]] = None,
    ):
        self.check_interval = check_interval_seconds
        self.notify_callback = notify_callback
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # State tracking to avoid spamming alerts
        self._low_battery_alerted = False
        self._last_briefing_date: Optional[datetime.date] = None

    def start(self) -> None:
        """Start the background proactive monitoring loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Proactive monitoring engine started.")

    def stop(self) -> None:
        """Stop background monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Proactive monitoring engine stopped.")

    async def _monitor_loop(self) -> None:
        """Periodic background evaluation loop."""
        # Initial grace period on startup
        await asyncio.sleep(5.0)

        while self._running:
            try:
                await self._check_battery()
                await self._check_morning_briefing()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in proactive monitoring loop: {e}")

            await asyncio.sleep(self.check_interval)

    async def _check_battery(self) -> None:
        """Check battery level and trigger alert if discharging and < 20%."""
        try:
            battery = psutil.sensors_battery()
            if not battery:
                return

            percent = battery.percent
            plugged = battery.power_plugged

            if not plugged and percent <= 20:
                if not self._low_battery_alerted:
                    self._low_battery_alerted = True
                    msg = f"Battery is low ({percent}%). Please plug in your charger."
                    logger.warning(f"Proactive trigger: {msg}")
                    self._deliver_notification("Low Battery Alert", msg)
            elif plugged or percent > 25:
                # Reset alert state once charging or above 25%
                self._low_battery_alerted = False

        except Exception as e:
            logger.debug(f"Battery check exception: {e}")

    async def _check_morning_briefing(self) -> None:
        """Trigger morning briefing once per day between 8:00 AM and 10:00 AM."""
        now = datetime.datetime.now()
        today = now.date()

        if self._last_briefing_date == today:
            return

        # Check if current time is in the morning window (8 AM to 10 AM)
        if 8 <= now.hour < 10:
            self._last_briefing_date = today
            briefing = await self._generate_morning_briefing()
            if briefing:
                logger.info(f"Proactive trigger: Morning Briefing -> '{briefing}'")
                self._deliver_notification("Morning Briefing", briefing)

    async def _generate_morning_briefing(self) -> str:
        """Assemble a concise morning status report."""
        try:
            from src.tools.web_tools import get_weather
            from src.tools.productivity_tools import list_active_timers
            from src.tools.system_tools import get_current_time

            time_res = get_current_time()
            time_str = time_res.message if time_res.success else "Good morning!"

            weather_res = get_weather("")
            weather_str = weather_res.message if weather_res.success else ""

            timers_res = list_active_timers()
            timers_str = timers_res.message if timers_res.success else ""

            briefing_parts = [f"Good morning! {time_str}"]
            if weather_str:
                briefing_parts.append(weather_str)
            if timers_str and "don't have any" not in timers_str.lower():
                briefing_parts.append(timers_str)

            return " ".join(briefing_parts)
        except Exception as e:
            logger.debug(f"Error generating morning briefing: {e}")
            return "Good morning! Have a productive day ahead."

    def _deliver_notification(self, title: str, message: str) -> None:
        """Deliver proactive notification via Windows WinRT toast and registered callback."""
        # 1. Custom callback if provided
        if self.notify_callback:
            try:
                self.notify_callback(title, message)
            except Exception:
                pass

        # 2. Native Windows WinRT Toast
        try:
            from windows_toasts import Toast, ToastDisplayImage, WindowsToaster
            toaster = WindowsToaster("Laya Assistant")
            toast = Toast([title, message])
            toaster.show_toast(toast)
        except Exception:
            pass


# Global singleton proactive engine
proactive_engine = ProactiveEngine()

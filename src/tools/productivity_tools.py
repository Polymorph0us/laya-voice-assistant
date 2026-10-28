"""
Productivity tools: set_timer, set_reminder, list_active_timers, cancel_timer, check_timer_remaining.

Backed by PersistentScheduler (SQLite + WinRT Windows Toast Notifications).
Survives system crashes and application reboots.
"""

from __future__ import annotations

from src.core.scheduler import scheduler
from src.tools.base import PermissionLevel, ToolParameter, ToolResult
from src.tools.registry import register
from src.utils.logger import get_logger

logger = get_logger("tools.productivity")


def _format_seconds(seconds: int) -> str:
    """Format seconds into natural human-readable time (days, hours, minutes, seconds)."""
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, rem_sec = divmod(rem, 60)

    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if rem_sec > 0 and days == 0 and hours == 0:
        parts.append(f"{rem_sec} second{'s' if rem_sec != 1 else ''}")

    if not parts:
        return "0 seconds"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


@register(
    name="set_timer",
    description="Set a countdown timer for a specific duration in seconds with persistent storage and Windows toast alert",
    permission=PermissionLevel.SAFE,
    category="productivity",
    parameters=[
        ToolParameter(
            name="duration_seconds",
            type="integer",
            description="The duration of the timer in seconds (e.g. 60 for 1 minute, 300 for 5 minutes)",
        ),
        ToolParameter(
            name="label",
            type="string",
            description="Optional label or reason for the timer (e.g. 'Tea', 'Laundry', 'Pomodoro')",
            required=False,
        ),
    ],
)
def set_timer(duration_seconds: int, label: str = "") -> ToolResult:
    """Set a persistent timer."""
    if duration_seconds <= 0:
        return ToolResult(success=False, error="Duration must be greater than zero", message="Please specify a positive time duration.")

    entry = scheduler.add_timer(duration_seconds, label)
    human_time = _format_seconds(duration_seconds)
    lbl = f" for '{label}'" if label else ""
    return ToolResult(
        success=True,
        message=f"I've set a timer{lbl} for {human_time}.",
        data=entry,
    )


import re
from datetime import datetime, timedelta

def _parse_natural_datetime(text: str, base_time: datetime | None = None) -> datetime | None:
    """Parse natural language date/time strings into a concrete datetime."""
    if not text:
        return None
    now = base_time or datetime.now()
    t = text.strip().lower()

    # Offset pattern: '10 mins before ...' or '1 hour before ...'
    m_before = re.match(r"(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\s+before\s+(.+)", t)
    if m_before:
        num = int(m_before.group(1))
        unit = m_before.group(2)
        base_event_str = m_before.group(3).strip()
        event_dt = _parse_natural_datetime(base_event_str, now)
        if event_dt:
            if "sec" in unit:
                offset = timedelta(seconds=num)
            elif "min" in unit:
                offset = timedelta(minutes=num)
            else:
                offset = timedelta(hours=num)
            return event_dt - offset

    # Relative: 'in X mins/hours/days'
    m_rel = re.match(r"in\s+(\d+)\s+(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)", t)
    if m_rel:
        num = int(m_rel.group(1))
        unit = m_rel.group(2)
        if "sec" in unit:
            return now + timedelta(seconds=num)
        if "min" in unit:
            return now + timedelta(minutes=num)
        if "hour" in unit or "hr" in unit:
            return now + timedelta(hours=num)
        if "day" in unit:
            return now + timedelta(days=num)

    # Tomorrow pattern
    if "tomorrow" in t:
        base_dt = now + timedelta(days=1)
        m_time = re.search(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t.replace("tomorrow", ""))
        if m_time and m_time.group(1):
            h = int(m_time.group(1))
            m = int(m_time.group(2) or 0)
            ampm = m_time.group(3)
            if ampm == "pm" and h < 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
            return base_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        return base_dt.replace(hour=9, minute=0, second=0, microsecond=0)

    # Timezone-aware or clean ISO formats
    # e.g. 2026-10-24 21:00:00+0900, 2026-10-24T21:00:00+09:00, 2026-10-24 21:00:00
    m_iso = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)\s*([+-]\d{2}:?\d{2}|Z)?", t, re.IGNORECASE)
    if m_iso:
        date_part, time_part, tz_part = m_iso.groups()
        if tz_part:
            if tz_part.upper() == "Z":
                tz_norm = "+00:00"
            elif len(tz_part) == 5 and tz_part[0] in "+-":
                tz_norm = f"{tz_part[:3]}:{tz_part[3:]}"
            else:
                tz_norm = tz_part
            try:
                dt_aware = datetime.fromisoformat(f"{date_part}T{time_part}{tz_norm}")
                return dt_aware.astimezone().replace(tzinfo=None)
            except Exception:
                pass
        else:
            try:
                return datetime.fromisoformat(f"{date_part}T{time_part}")
            except Exception:
                pass

    # ISO formats fallback
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(t, fmt)
            if fmt == "%Y-%m-%d":
                dt = dt.replace(hour=9, minute=0, second=0)
            return dt
        except ValueError:
            pass

    # Month day time: 'oct 24 17:20', 'october 24 at 5:20 pm', 'oct 24'
    m_date = re.search(
        r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(?:at\s+)?(\d{1,2}):?(\d{2})?\s*(am|pm)?)?",
        t,
    )
    if m_date:
        month_str, day_str, hour_str, min_str, ampm = m_date.groups()
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        month = month_map[month_str[:3]]
        day = int(day_str)
        year = now.year
        if month < now.month or (month == now.month and day < now.day):
            year += 1

        hour = int(hour_str) if hour_str else 9
        minute = int(min_str) if min_str else 0
        if ampm:
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0

        return datetime(year, month, day, hour, minute, 0)

    return None


@register(
    name="set_reminder",
    description="Schedule a reminder, alert, or notification for an event, contest, meeting, or task at a specific date and time. Always call this tool when the user asks to be reminded or when setting a reminder for a contest/event.",
    permission=PermissionLevel.SAFE,
    category="productivity",
    parameters=[
        ToolParameter(
            name="task",
            type="string",
            description="The title, event, or task to be reminded about (e.g. 'AtCoder Beginner Contest 481', 'doctor appointment')",
        ),
        ToolParameter(
            name="target_time",
            type="string",
            description="When the reminder should trigger (e.g. '2026-10-24 20:50:00', '10 mins before 2026-10-24 21:00:00+0900', 'tomorrow at 9am', 'oct 24 at 5:20 pm')",
            required=False,
            default="",
        ),
        ToolParameter(
            name="delay_seconds",
            type="integer",
            description="Optional relative delay in seconds (e.g. 600 for 10 minutes from now)",
            required=False,
            default=0,
        ),
    ],
)
def set_reminder(task: str = "", target_time: str = "", delay_seconds: int = 0, **kwargs: Any) -> ToolResult:
    """Set a persistent reminder by target time or duration."""
    # Resolve aliases if LLM passed parameter variants
    if not task:
        task = kwargs.get("message") or kwargs.get("label") or kwargs.get("title") or "Reminder"
    if not target_time:
        target_time = str(kwargs.get("time") or kwargs.get("at_time") or kwargs.get("when") or kwargs.get("date") or "")

    now = datetime.now()
    dt = None

    if target_time:
        dt = _parse_natural_datetime(target_time, now)

    if dt:
        delta_seconds = int((dt - now).total_seconds())
        if delta_seconds <= 0:
            return ToolResult(
                success=False,
                error="Target time is in the past",
                message=f"The specified time '{target_time}' has already passed.",
            )
        entry = scheduler.add_reminder(task, at_datetime=dt)
        human_time = _format_seconds(delta_seconds)
        date_str = dt.strftime("%A, %B %d at %I:%M %p")
        return ToolResult(
            success=True,
            message=f"I've set a reminder to '{task}' for {date_str} (in {human_time}).",
            data=entry,
        )

    # Fallback to delay_seconds
    seconds = max(1, delay_seconds if delay_seconds > 0 else 60)
    entry = scheduler.add_reminder(task, delay_seconds=seconds)
    human_time = _format_seconds(seconds)
    return ToolResult(
        success=True,
        message=f"I'll remind you to '{task}' in {human_time}.",
        data=entry,
    )


@register(
    name="list_active_timers",
    description="List all currently active countdown timers and reminders with their remaining time",
    permission=PermissionLevel.SAFE,
    category="productivity",
)
def list_active_timers() -> ToolResult:
    """List running timers and reminders."""
    active = scheduler.list_active()
    if not active:
        return ToolResult(
            success=True,
            message="You don't have any active timers or reminders running right now.",
            data={"active": []},
        )

    parts = []
    for item in active:
        rem_str = _format_seconds(item["remaining_seconds"])
        parts.append(f"{item['type'].title()} '{item['label']}' with {rem_str} left")

    msg = f"You have {len(active)} active item{'s' if len(active) != 1 else ''}: " + ", ".join(parts) + "."
    return ToolResult(
        success=True,
        message=msg,
        data={"active": active},
    )


@register(
    name="check_timer_remaining",
    description="Check how much time is left on active timers or a specific timer",
    permission=PermissionLevel.SAFE,
    category="productivity",
    parameters=[
        ToolParameter(
            name="label",
            type="string",
            description="Optional label of the timer to check",
            required=False,
        ),
    ],
)
def check_timer_remaining(label: str = "") -> ToolResult:
    """Check remaining time on timer."""
    active = scheduler.list_active()
    if not active:
        return ToolResult(
            success=True,
            message="You don't have any active timers right now.",
            data={"active": []},
        )

    clean_lbl = label.strip().lower()
    if clean_lbl:
        matched = [a for a in active if clean_lbl in a["label"].lower()]
        if matched:
            target = matched[0]
            rem_str = _format_seconds(target["remaining_seconds"])
            return ToolResult(
                success=True,
                message=f"There is {rem_str} remaining on your timer '{target['label']}'.",
                data=target,
            )

    # If only 1 timer running
    if len(active) == 1:
        target = active[0]
        rem_str = _format_seconds(target["remaining_seconds"])
        return ToolResult(
            success=True,
            message=f"There is {rem_str} remaining on your {target['label']}.",
            data=target,
        )

    # Multiple timers
    summaries = [f"'{a['label']}' has {_format_seconds(a['remaining_seconds'])} left" for a in active]
    return ToolResult(
        success=True,
        message="Active timers: " + ", ".join(summaries) + ".",
        data={"active": active},
    )


@register(
    name="cancel_timer",
    description="Cancel active timers or reminders by name, ID, or cancel all",
    permission=PermissionLevel.SAFE,
    category="productivity",
    parameters=[
        ToolParameter(
            name="label_or_id",
            type="string",
            description="The label or ID of the timer to cancel, or 'all' to cancel everything",
            required=False,
        ),
    ],
)
def cancel_timer(label_or_id: str = "") -> ToolResult:
    """Cancel matching timers."""
    count = scheduler.cancel(label_or_id)
    if count > 0:
        target_desc = f"'{label_or_id}'" if label_or_id and label_or_id != "all" else "all active"
        return ToolResult(
            success=True,
            message=f"Cancelled {count} timer{'s' if count != 1 else ''} ({target_desc}).",
            data={"cancelled_count": count},
        )
    return ToolResult(
        success=True,
        message="No matching active timers were found to cancel.",
        data={"cancelled_count": 0},
    )

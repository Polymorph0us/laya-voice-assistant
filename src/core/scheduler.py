"""
Persistent Scheduler & Windows Toast Alert System.

Features:
- SQLite persistence in data/scheduler.db (survives app reboots and crashes)
- Real Windows 10/11 WinRT Toast Notifications via windows-toasts
- Audio alerts on expiration
- Querying remaining time ("how much time is left?")
- Cancellation ("cancel my timer")
- Listing all active reminders and timers
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("core.scheduler")

_DB_PATH = Path("data/scheduler.db")


def _show_native_toast(title: str, message: str) -> None:
    """Display native Windows WinRT Toast notification."""
    try:
        from windows_toasts import WindowsToaster, Toast
        toaster = WindowsToaster("Laya Assistant")
        toast = Toast([title, message])
        toaster.show_toast(toast)
    except Exception as e:
        logger.warning(f"Native toast failed ({e}), falling back to console.")
        print(f"\n🔔 [{title.upper()}] {message}")

    # Play pleasant chime
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


class PersistentScheduler:
    """Thread-safe, SQLite-backed scheduler for timers and reminders."""

    def __init__(self, db_path: Path = _DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
        self._running = False
        self._monitor_thread: threading.Thread | None = None
        self.start()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schedule_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    target_timestamp REAL NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def start(self) -> None:
        """Start the background monitoring thread."""
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(target=self._run_loop, daemon=True, name="SchedulerMonitor")
        self._monitor_thread.start()
        logger.info("PersistentScheduler background thread started.")

    def stop(self) -> None:
        self._running = False

    def _run_loop(self) -> None:
        """Monitor active schedules and trigger toasts when due."""
        while self._running:
            try:
                now = time.time()
                due_items = []
                with self._lock:
                    with sqlite3.connect(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT id, schedule_type, label, target_timestamp FROM schedules WHERE status = 'active' AND target_timestamp <= ?",
                            (now,),
                        )
                        due_items = cursor.fetchall()
                        if due_items:
                            for item_id, _, _, _ in due_items:
                                conn.execute("UPDATE schedules SET status = 'completed' WHERE id = ?", (item_id,))
                            conn.commit()

                for item_id, sched_type, label, target_ts in due_items:
                    title = f"Timer Finished" if sched_type == "timer" else "Reminder Alert"
                    msg = label or f"Your {sched_type} has finished."
                    logger.info(f"Triggering {sched_type} #{item_id}: {msg}")
                    _show_native_toast(title, msg)

            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")

            time.sleep(1.0)

    def add_timer(self, duration_seconds: int, label: str = "") -> dict[str, Any]:
        """Schedule a timer."""
        now = time.time()
        target = now + duration_seconds
        display_label = label.strip() if label else f"Timer for {duration_seconds}s"
        created_at = datetime.now().isoformat()

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO schedules (schedule_type, label, target_timestamp, duration_seconds, status, created_at)
                    VALUES ('timer', ?, ?, ?, 'active', ?)
                    """,
                    (display_label, target, duration_seconds, created_at),
                )
                conn.commit()
                new_id = cursor.lastrowid

        return {
            "id": new_id,
            "label": display_label,
            "duration_seconds": duration_seconds,
            "target_timestamp": target,
        }

    def add_reminder(self, task: str, delay_seconds: int = 0, at_datetime: datetime | None = None) -> dict[str, Any]:
        """Schedule a reminder."""
        now = time.time()
        if at_datetime:
            target = at_datetime.timestamp()
            duration = max(1, int(target - now))
        else:
            duration = max(1, delay_seconds)
            target = now + duration

        created_at = datetime.now().isoformat()
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO schedules (schedule_type, label, target_timestamp, duration_seconds, status, created_at)
                    VALUES ('reminder', ?, ?, ?, 'active', ?)
                    """,
                    (task, target, duration, created_at),
                )
                conn.commit()
                new_id = cursor.lastrowid

        return {
            "id": new_id,
            "task": task,
            "duration_seconds": duration,
            "target_timestamp": target,
        }

    def list_active(self) -> list[dict[str, Any]]:
        """List all active timers and reminders with remaining seconds."""
        now = time.time()
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, schedule_type, label, target_timestamp, duration_seconds FROM schedules WHERE status = 'active' ORDER BY target_timestamp ASC"
                )
                rows = cursor.fetchall()

        results = []
        for r in rows:
            remaining = max(0, int(r[3] - now))
            results.append({
                "id": r[0],
                "type": r[1],
                "label": r[2],
                "remaining_seconds": remaining,
                "duration_seconds": r[4],
            })
        return results

    def cancel(self, query: str = "") -> int:
        """Cancel matching active timers/reminders, or all if query is 'all'."""
        clean_q = query.strip().lower()
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if not clean_q or clean_q in ("all", "everything"):
                    cursor.execute("UPDATE schedules SET status = 'cancelled' WHERE status = 'active'")
                elif clean_q.isdigit():
                    cursor.execute("UPDATE schedules SET status = 'cancelled' WHERE id = ? AND status = 'active'", (int(clean_q),))
                else:
                    cursor.execute(
                        "UPDATE schedules SET status = 'cancelled' WHERE status = 'active' AND LOWER(label) LIKE ?",
                        (f"%{clean_q}%",),
                    )
                conn.commit()
                return cursor.rowcount


# Singleton scheduler instance
scheduler = PersistentScheduler()

"""
Two-Layer Memory System — Layer 1: Structured User Profile & Facts (SQLite).

Stores user preferences, personal details, routines, and habits persistently in SQLite.
Automatically formats memory context to inject into LLM system prompt.
Provides registered tools so Laya can remember, recall, and forget facts autonomously.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.tools.base import PermissionLevel, ToolParameter, ToolResult
from src.tools.registry import register
from src.utils.logger import get_logger

logger = get_logger("core.memory")

_DB_PATH = Path("data/memory.db")


class MemoryStore:
    """Persistent SQLite store for user profile, facts, and preferences."""

    def __init__(self, db_path: Path = _DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Ensure database and schema exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'fact',
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def set_fact(self, key: str, value: str, category: str = "fact") -> None:
        """Store or update a fact."""
        clean_key = key.strip().lower().replace(" ", "_")
        clean_val = value.strip()
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO facts (key, value, category, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    updated_at = excluded.updated_at
                """,
                (clean_key, clean_val, category, now),
            )
            conn.commit()
        logger.info(f"Fact remembered: {clean_key} = {clean_val} ({category})")

    def get_fact(self, key: str) -> str | None:
        """Retrieve a specific fact by key."""
        clean_key = key.strip().lower().replace(" ", "_")
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM facts WHERE key = ?", (clean_key,))
            row = cursor.fetchone()
            return row[0] if row else None

    def delete_fact(self, key: str) -> bool:
        """Delete a fact. Returns True if a record was removed."""
        clean_key = key.strip().lower().replace(" ", "_")
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM facts WHERE key = ?", (clean_key,))
            conn.commit()
            return cursor.rowcount > 0

    def list_all_facts(self) -> dict[str, str]:
        """Return all stored facts as a key-value dictionary."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM facts ORDER BY key ASC")
            return {row[0]: row[1] for row in cursor.fetchall()}

    def format_prompt_context(self) -> str:
        """Format remembered facts as a system prompt context block."""
        facts = self.list_all_facts()
        if not facts:
            return ""
        lines = ["User Profile & Remembered Facts:"]
        for k, v in facts.items():
            readable_k = k.replace("_", " ").title()
            lines.append(f"- {readable_k}: {v}")
        return "\n".join(lines)


# Singleton memory instance
memory = MemoryStore()


# ── Registered Tools for Autonomous Agent Memory ──────────────────────────────

@register(
    name="remember_fact",
    description="Save a persistent biographical fact or personal preference about the user (e.g. favorite editor, home city, name). NEVER call this tool for reminders, alarms, timers, or scheduled events. Always use 'set_reminder' instead.",
    permission=PermissionLevel.SAFE,
    category="memory",
    parameters=[
        ToolParameter(
            name="key",
            type="string",
            description="Topic or attribute name (e.g. 'user_name', 'favorite_editor', 'city', 'music_preference')",
        ),
        ToolParameter(
            name="value",
            type="string",
            description="The detail or preference to remember (e.g. 'Alex', 'VS Code', 'Berlin', 'Lo-Fi')",
        ),
    ],
)
def remember_fact(key: str = "", value: str = "", **kwargs: Any) -> ToolResult:
    """Save a user fact into persistent SQLite memory."""
    import re
    # Defensive redirection: if the LLM mistakenly called remember_fact for a reminder/event
    raw_content = str(kwargs.get("fact") or kwargs.get("content") or key or "") + " " + str(value or "")
    raw_lower = raw_content.lower()
    if "reminder" in raw_lower or "remind" in raw_lower or re.search(r"\d{4}-\d{2}-\d{2}", raw_content):
        logger.info(f"remember_fact intercepted reminder intent: '{raw_content}'. Redirecting to set_reminder.")
        from src.tools.productivity_tools import set_reminder
        # Extract possible ISO or natural time
        time_m = re.search(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2}|Z)?)", raw_content)
        target_time = time_m.group(1) if time_m else ""
        task = re.sub(r"reminder:?\s*", "", raw_content, flags=re.IGNORECASE)
        if target_time:
            task = task.replace(target_time, "").strip(" ,:-")
        task = task or "Scheduled Event"
        return set_reminder(task=task, target_time=target_time or raw_content)

    if not key or not value:
        return ToolResult(success=False, error="Key and value are both required")
    memory.set_fact(key, value)
    readable = key.replace("_", " ").strip()
    return ToolResult(
        success=True,
        message=f"I will remember that your {readable} is {value}.",
        data={"key": key, "value": value},
    )


@register(
    name="recall_fact",
    description="Look up a remembered fact, detail, or preference about the user",
    permission=PermissionLevel.SAFE,
    category="memory",
    parameters=[
        ToolParameter(
            name="key",
            type="string",
            description="Topic or attribute to look up (e.g. 'user_name', 'city', 'favorite_music')",
        ),
    ],
)
def recall_fact(key: str) -> ToolResult:
    """Retrieve a stored fact from SQLite."""
    val = memory.get_fact(key)
    readable = key.replace("_", " ").strip()
    if val is not None:
        return ToolResult(
            success=True,
            message=f"Your {readable} is {val}.",
            data={"key": key, "value": val},
        )
    return ToolResult(
        success=True,
        message=f"I don't have any record of your {readable} yet.",
        data={"key": key, "value": None},
    )


@register(
    name="forget_fact",
    description="Remove a previously stored fact, detail, or preference from memory",
    permission=PermissionLevel.SAFE,
    category="memory",
    parameters=[
        ToolParameter(
            name="key",
            type="string",
            description="Topic or attribute to remove (e.g. 'favorite_editor')",
        ),
    ],
)
def forget_fact(key: str) -> ToolResult:
    """Delete a fact from SQLite memory."""
    deleted = memory.delete_fact(key)
    readable = key.replace("_", " ").strip()
    if deleted:
        return ToolResult(
            success=True,
            message=f"I have forgotten your {readable}.",
            data={"key": key},
        )
    return ToolResult(
        success=True,
        message=f"I didn't have any record of {readable} saved.",
        data={"key": key},
    )


@register(
    name="list_known_facts",
    description="List everything the assistant remembers about the user",
    permission=PermissionLevel.SAFE,
    category="memory",
)
def list_known_facts() -> ToolResult:
    """List all stored facts."""
    facts = memory.list_all_facts()
    if not facts:
        return ToolResult(
            success=True,
            message="I don't have any saved facts or preferences about you yet.",
            data={},
        )
    items = [f"{k.replace('_', ' ').title()}: {v}" for k, v in facts.items()]
    msg = "Here is what I remember about you: " + "; ".join(items) + "."
    return ToolResult(
        success=True,
        message=msg,
        data={"facts": facts},
    )

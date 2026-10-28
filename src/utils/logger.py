"""
Structured JSON logging for the Laya assistant.

Every tool execution, Laya decision, and agent action is logged as a structured
JSON record. This makes the system fully observable and debuggable.
"""

import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StructuredFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Merge any extra structured data attached to the record
        if hasattr(record, "data"):
            log_entry["data"] = record.data

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """Readable formatter for console output."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"{color}{self.BOLD}[{timestamp}] {record.levelname:<8}{self.RESET}"
        message = record.getMessage()

        parts = [f"{prefix} {message}"]

        # Show structured data in a readable way
        if hasattr(record, "data") and record.data:
            for key, value in record.data.items():
                if isinstance(value, dict):
                    parts.append(f"  {color}├─ {key}:{self.RESET}")
                    for k, v in value.items():
                        parts.append(f"  {color}│  {k}: {v}{self.RESET}")
                else:
                    parts.append(f"  {color}├─ {key}: {value}{self.RESET}")

        return "\n".join(parts)


def setup_logging(
    log_dir: Path | None = None,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    human_readable: bool = True,
) -> logging.Logger:
    """
    Configure the application-wide logging system.

    Args:
        log_dir: Directory for log files. If None, only console logging.
        console_level: Minimum level for console output.
        file_level: Minimum level for file output.
        human_readable: Use colored human-readable format for console.

    Returns:
        The root 'laya' logger.
    """
    logger = logging.getLogger("laya")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Console handler
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(console_level)
    if human_readable:
        console.setFormatter(HumanFormatter())
    else:
        console.setFormatter(StructuredFormatter())
    logger.addHandler(console)

    # File handler (JSON structured)
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"laya_{date_str}.jsonl"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(file_level)
        file_handler.setFormatter(StructuredFormatter())
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "laya") -> logging.Logger:
    """Get a named child logger under the 'laya' namespace."""
    return logging.getLogger(f"laya.{name}")


def log_event(
    logger: logging.Logger,
    message: str,
    level: int = logging.INFO,
    **data: Any,
) -> None:
    """
    Log a message with attached structured data.

    Usage:
        log_event(logger, "Tool executed", tool="open_app", status="success")
    """
    record = logger.makeRecord(
        name=logger.name,
        level=level,
        fn="",
        lno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.data = data  # type: ignore[attr-defined]
    logger.handle(record)


def generate_request_id() -> str:
    """Generate a unique request ID for tracking through the pipeline."""
    return f"req_{uuid.uuid4().hex[:12]}"

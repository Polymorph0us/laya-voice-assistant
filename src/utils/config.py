"""
YAML-based configuration management for the Laya assistant.

Loads settings from config/settings.yaml with sensible defaults.
Configuration is immutable after loading — no runtime mutation.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Default configuration values
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "assistant": {
        "name": "Laya",
    },
    "laya": {
        "preload": False,
        "max_loaded": 2,
        "device": "cpu",
        "default_model": "english",
    },
    "llm": {
        "provider": "ollama",
        "api_key": "",
        "ollama_url": "http://localhost:11434",
        "ollama_model": "qwen3:4b",
    },
    "github": {
        "token": "",
        "username": "",
    },
    "confidence": {
        "high_threshold": 0.65,
        "medium_threshold": 0.35,
        "absolute_minimum": 0.20,
    },
    "logging": {
        "console_level": "INFO",
        "file_level": "DEBUG",
        "human_readable": True,
    },
    "tools": {
        "app_aliases": {
            "vscode": ["code"],
            "chrome": ["start chrome", "start", "chrome"],
            "firefox": ["start firefox"],
            "notepad": ["notepad"],
            "calculator": ["calc"],
            "file explorer": ["explorer"],
            "task manager": ["taskmgr"],
            "terminal": ["wt"],
            "powershell": ["powershell"],
            "cmd": ["cmd"],
        },
    },
}


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AssistantConfig:
    name: str = "Laya"


@dataclass(frozen=True)
class LayaConfig:
    preload: bool = False
    max_loaded: int = 2
    device: str = "cpu"
    default_model: str = "english"

@dataclass(frozen=True)
class LLMConfig:
    provider: str = "ollama"
    api_key: str = ""
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"


@dataclass(frozen=True)
class GitHubConfig:
    token: str = ""
    username: str = ""


@dataclass(frozen=True)
class ConfidenceConfig:
    high_threshold: float = 0.65
    medium_threshold: float = 0.35
    absolute_minimum: float = 0.20


@dataclass(frozen=True)
class LoggingConfig:
    console_level: str = "INFO"
    file_level: str = "DEBUG"
    human_readable: bool = True


@dataclass(frozen=True)
class ToolsConfig:
    app_aliases: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class AppConfig:
    assistant: AssistantConfig = field(default_factory=AssistantConfig)
    laya: LayaConfig = field(default_factory=LayaConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    confidence: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Path | None = None) -> AppConfig:
    """
    Load configuration from a YAML file, merged with defaults.

    Args:
        config_path: Path to settings.yaml. If None, uses defaults only.

    Returns:
        Frozen AppConfig dataclass.
    """
    raw = _DEFAULTS.copy()

    if config_path and config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        raw = _deep_merge(raw, user_config)

    return AppConfig(
        assistant=AssistantConfig(**raw.get("assistant", {})),
        laya=LayaConfig(**raw.get("laya", {})),
        llm=LLMConfig(**raw.get("llm", {})),
        github=GitHubConfig(**raw.get("github", {})),
        confidence=ConfidenceConfig(**raw.get("confidence", {})),
        logging=LoggingConfig(**raw.get("logging", {})),
        tools=ToolsConfig(
            app_aliases=raw.get("tools", {}).get("app_aliases", {}),
        ),
    )

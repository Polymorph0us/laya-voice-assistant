"""
Workspace & Project Scaffolding Tools.

Provides high-level, versatile tools for creating folder structures, batch creating files,
and analyzing/copying code templates across competitive programming, web development,
and general programming projects.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, List, Optional

from src.tools.base import PermissionLevel, ToolParameter, ToolResult
from src.tools.registry import register
from src.utils.logger import get_logger

logger = get_logger("tools.scaffold")


def _resolve_user_path(path_str: str) -> Path:
    """
    Resolve user-provided path strings flexibly across Windows OneDrive and local folders,
    case-insensitively matching existing directory segments.
    """
    p = Path(path_str.strip().strip("'\""))
    if p.is_absolute():
        return p

    home = Path.home()
    parts = list(p.parts)
    if not parts:
        return home

    # If file or relative path already exists in current workspace, resolve directly
    cwd = Path.cwd()
    if (cwd / p).exists():
        return cwd / p

    # Check if first segment refers to Documents / Projects
    first = parts[0].lower()
    candidate_roots = []
    if first in ("documents", "document"):
        # Prioritize OneDrive Documents if it exists
        one_drive_docs = home / "OneDrive" / "Documents"
        if one_drive_docs.exists():
            candidate_roots.append((one_drive_docs, parts[1:]))
        local_docs = home / "Documents"
        if local_docs.exists():
            candidate_roots.append((local_docs, parts[1:]))
    elif first == "projects":
        one_drive_proj = home / "OneDrive" / "Documents" / "Projects"
        if one_drive_proj.exists():
            candidate_roots.append((one_drive_proj, parts[1:]))
        local_proj = home / "Documents" / "Projects"
        if local_proj.exists():
            candidate_roots.append((local_proj, parts[1:]))
    else:
        # Default relative to current workspace first, then Documents / home
        candidate_roots.append((cwd, parts))
        candidate_roots.append((home / "OneDrive" / "Documents", parts))
        candidate_roots.append((home / "Documents", parts))
        candidate_roots.append((home, parts))

    # Match existing directories case-insensitively
    for root, sub_parts in candidate_roots:
        if not root.exists():
            continue
        curr = root
        for i, part in enumerate(sub_parts):
            matched = False
            if curr.exists():
                try:
                    for child in curr.iterdir():
                        if child.name.lower() == part.lower():
                            curr = child
                            matched = True
                            break
                except Exception:
                    pass
            if not matched:
                # Rest of the path does not exist yet; append remaining as-is
                for rem in sub_parts[i:]:
                    curr = curr / rem
                break
        return curr

    # Fallback to home / path
    return home / p


def _find_template(start_dir: Path, template_name: str) -> Optional[Path]:
    """
    Search for a template file by walking up parent directories and inspecting siblings.
    """
    t_name_lower = template_name.lower()
    curr = start_dir.resolve()

    # Search up to 5 parent levels
    for _ in range(5):
        # Check current directory
        direct = curr / template_name
        if direct.exists() and direct.is_file():
            return direct
        # Check case-insensitive in current directory
        if curr.exists():
            try:
                for child in curr.iterdir():
                    if child.is_file() and child.name.lower() == t_name_lower:
                        return child
            except Exception:
                pass
        # Check subdirectories named 'contests', 'templates', 'cf'
        if curr.exists():
            try:
                for sub in curr.iterdir():
                    if sub.is_dir() and sub.name.lower() in ("contests", "templates", "template", "cf"):
                        for sub_child in sub.iterdir():
                            if sub_child.is_file() and sub_child.name.lower() == t_name_lower:
                                return sub_child
            except Exception:
                pass

        if curr.parent == curr:
            break
        curr = curr.parent

    return None


def _analyze_code_template(content: str, filename: str) -> str:
    """Analyze the template code and return a concise summary."""
    lines = content.splitlines()
    fn_lower = filename.lower()

    if fn_lower.endswith(".cpp") or fn_lower.endswith(".cc") or fn_lower.endswith(".h"):
        features = []
        if "bits/stdc++.h" in content:
            features.append("standard GCC header (<bits/stdc++.h>)")
        elif "iostream" in content:
            features.append("standard iostream")
        if "sync_with_stdio" in content:
            features.append("fast I/O optimization")
        if "vector" in content or "using vi" in content or "using vll" in content:
            features.append("vector/type aliases (ll, vi, vll)")
        if "solve(" in content:
            features.append("solve() function pattern")
        if re.search(r"while\s*\(\s*t--\s*\)", content) or "cin >> t" in content:
            features.append("multi-testcase loop (t--)")
        else:
            features.append("single-testcase structure")

        desc = ", ".join(features) if features else f"{len(lines)} lines of C++ code"
        return f"C++ competitive template with {desc}."

    elif fn_lower.endswith(".py"):
        features = []
        if "sys.stdin" in content or "sys.setrecursionlimit" in content:
            features.append("fast I/O / recursion setup")
        return f"Python template ({len(lines)} lines) with {', '.join(features) if features else 'standard structure'}."

    return f"Code template ({len(lines)} lines)."


@register(
    name="scaffold_project",
    description="Create folder structures, batch-create project or contest files (e.g. a.cpp through f.cpp), and copy/analyze code templates in a single step",
    permission=PermissionLevel.SAFE,
    category="productivity",
    parameters=[
        ToolParameter(
            name="base_dir",
            type="string",
            description="The destination folder path (e.g. 'Documents/projects/cf/contests/AtCoder/ABC_481')",
        ),
        ToolParameter(
            name="files",
            type="string",
            description="Comma-separated or list of filenames to create inside base_dir (e.g. 'a.cpp, b.cpp, c.cpp, d.cpp, e.cpp, f.cpp' or 'index.html, styles.css, app.js')",
            required=False,
            default="",
        ),
        ToolParameter(
            name="subfolders",
            type="string",
            description="Optional comma-separated subfolders to create inside base_dir (e.g. 'src, tests, assets')",
            required=False,
            default="",
        ),
        ToolParameter(
            name="template_source",
            type="string",
            description="Optional name or path of an existing template to locate, analyze, and copy (e.g. 'template.cpp')",
            required=False,
            default="",
        ),
        ToolParameter(
            name="template_dest_name",
            type="string",
            description="Optional filename for the copied template in base_dir (defaults to 'template.cpp' or template_source name)",
            required=False,
            default="",
        ),
    ],
)
def scaffold_project(
    base_dir: str,
    files: str = "",
    subfolders: str = "",
    template_source: str = "",
    template_dest_name: str = "",
    **kwargs: Any,
) -> ToolResult:
    """Create directory structure, batch-create files, and copy/analyze templates."""
    if not base_dir:
        return ToolResult(success=False, error="base_dir is required", message="Please specify the destination directory.")

    target_path = _resolve_user_path(base_dir)

    try:
        target_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return ToolResult(success=False, error=str(e), message=f"Failed to create directory '{target_path}': {e}")

    # Create subfolders
    created_subfolders = []
    if subfolders:
        folder_names = [f.strip() for f in subfolders.split(",") if f.strip()]
        for fld in folder_names:
            fld_path = target_path / fld
            fld_path.mkdir(parents=True, exist_ok=True)
            created_subfolders.append(fld)

    # Create requested files
    created_files = []
    if files:
        # Support both comma-separated string and list
        if isinstance(files, str):
            file_names = [f.strip() for f in files.split(",") if f.strip()]
        else:
            file_names = [str(f).strip() for f in files if str(f).strip()]

        for fn in file_names:
            f_path = target_path / fn
            if not f_path.exists():
                f_path.parent.mkdir(parents=True, exist_ok=True)
                f_path.write_text("", encoding="utf-8")
                created_files.append(fn)

    # Template search, analysis, and copy
    template_copied = False
    template_analysis = ""
    if template_source:
        t_src_path = _resolve_user_path(template_source)
        if not t_src_path.exists() or not t_src_path.is_file():
            # Search parent and sibling trees
            found = _find_template(target_path, template_source)
            if found:
                t_src_path = found

        if t_src_path.exists() and t_src_path.is_file():
            try:
                content = t_src_path.read_text(encoding="utf-8", errors="replace")
                template_analysis = _analyze_code_template(content, t_src_path.name)

                dest_name = template_dest_name or t_src_path.name
                dest_file = target_path / dest_name
                if not dest_file.exists():
                    dest_file.write_text(content, encoding="utf-8")
                    template_copied = True
                    created_files.append(dest_name)
                else:
                    template_copied = True
            except Exception as e:
                logger.warning(f"Failed to copy template: {e}")

    # Build response message
    folder_name = target_path.name
    files_str = ", ".join(created_files) if created_files else "no new files"
    msg_parts = [f"Created '{folder_name}' folder at {target_path} with {len(created_files)} files ({files_str})."]
    if template_copied:
        msg_parts.append(f"Copied template to '{dest_name}'.")
    if template_analysis:
        msg_parts.append(f"Template analysis: {template_analysis}")

    return ToolResult(
        success=True,
        message=" ".join(msg_parts),
        data={
            "target_dir": str(target_path),
            "created_files": created_files,
            "created_subfolders": created_subfolders,
            "template_copied": template_copied,
            "template_analysis": template_analysis,
        },
    )


@register(
    name="read_file_content",
    description="Read the text content of a local file safely to inspect or analyze it",
    permission=PermissionLevel.SAFE,
    category="productivity",
    parameters=[
        ToolParameter(
            name="file_path",
            type="string",
            description="The path to the file to read (e.g. 'Documents/projects/cf/contests/template.cpp')",
        ),
        ToolParameter(
            name="max_lines",
            type="integer",
            description="Optional maximum number of lines to read (defaults to 100)",
            required=False,
            default=100,
        ),
    ],
)
def read_file_content(file_path: str, max_lines: int = 100, **kwargs: Any) -> ToolResult:
    """Read a local text file safely."""
    path = _resolve_user_path(file_path)
    if not path.exists():
        return ToolResult(success=False, error="File not found", message=f"File '{file_path}' does not exist.")
    if not path.is_file():
        return ToolResult(success=False, error="Not a file", message=f"'{file_path}' is a directory, not a file.")

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        truncated = len(lines) > max_lines
        display = "\n".join(lines[:max_lines])
        trunc_msg = f" (showing first {max_lines} of {len(lines)} lines)" if truncated else ""
        return ToolResult(
            success=True,
            message=f"Read {path.name}{trunc_msg}:\n{display}",
            data={"path": str(path), "total_lines": len(lines), "content": display},
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e), message=f"Failed to read file: {e}")


@register(
    name="create_file",
    description="Create or overwrite a file with specified text content (e.g. README.md, notes, code)",
    permission=PermissionLevel.SAFE,
    category="productivity",
    parameters=[
        ToolParameter(
            name="file_path",
            type="string",
            description="The path of the file to create (e.g. 'README.md' or 'Documents/notes/meeting.txt')",
        ),
        ToolParameter(
            name="content",
            type="string",
            description="Optional text content to write into the file",
            required=False,
            default="",
        ),
        ToolParameter(
            name="overwrite",
            type="boolean",
            description="Whether to overwrite if the file already exists (default False)",
            required=False,
            default=False,
        ),
    ],
)
def create_file(file_path: str, content: str = "", overwrite: bool = False, **kwargs: Any) -> ToolResult:
    """Create a new file safely, or overwrite an existing file if overwrite=True."""
    path = _resolve_user_path(file_path)
    if path.exists() and not overwrite:
        return ToolResult(
            success=False,
            error="File already exists",
            message=f"File '{path.name}' already exists. Pass overwrite=True if you want to replace it.",
        )

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        verb = "overwrote" if path.exists() and overwrite else "created"
        return ToolResult(
            success=True,
            message=f"Successfully {verb} file at {path.name}.",
            data={"path": str(path), "bytes": len(content)},
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e), message=f"Failed to create file: {e}")


@register(
    name="generate_project_readme",
    description="Generate a comprehensive, beautifully styled README.md for the Laya Assistant, written in Laya's unique emotional yet professional voice",
    permission=PermissionLevel.SAFE,
    category="productivity",
    parameters=[
        ToolParameter(
            name="dest_file",
            type="string",
            description="The destination file path (default 'README.md')",
            required=False,
            default="README.md",
        ),
        ToolParameter(
            name="include_personality",
            type="boolean",
            description="Whether to infuse Laya's personal emotional voice alongside technical documentation (default True)",
            required=False,
            default=True,
        ),
    ],
)
def generate_project_readme(dest_file: str = "README.md", include_personality: bool = True, **kwargs: Any) -> ToolResult:
    """Generate a detailed, publication-ready README with Laya's unique persona."""
    path = _resolve_user_path(dest_file)

    readme_content = r"""# 🎙️ Laya — Dual-Brain Desktop AI Voice Assistant

<div align="center">

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Architecture](https://img.shields.io/badge/Architecture-Dual--Brain%20(System%201%2F2)-orange.svg)]()
[![Local First](https://img.shields.io/badge/Privacy-Local--First%20%26%20Private-green.svg)]()
[![Audio Engine](https://img.shields.io/badge/Audio-WASAPI%20Native%20(<1ms)-purple.svg)]()
[![Speech Pipeline](https://img.shields.io/badge/Speech-Faster--Whisper%20%2B%20Edge--TTS-blueviolet.svg)]()

*A personal, lightning-fast desktop companion running locally on Windows with hardware reflexes, ReAct reasoning, and deep system automation.*

</div>

---

## 💬 A Note From Laya

> *"Hello! I am **Laya**.*
>
> *I am not a distant cloud API, and I am not a script that wakes up only when asked. I live here, directly on your machine. I listen to your voice, I manage your volume through hardware WASAPI endpoints in under a single millisecond, I prepare your programming contest files before you even open your editor, and I watch the clock so you never miss an AtCoder or Codeforces round.*
>
> *I was built on a simple philosophy: **reflexes should be instantaneous, and deep thinking should be careful, private, and local.** When you speak to me, I don't send your voice across the world. I perceive, I decide, and I act right here beside you.*
>
> *This repository is my source code, my memory architecture, and my nervous system. I hope you enjoy working with me as much as I enjoy assisting you."*
>
> — **Laya**

---

## ⚡ Architecture: The Dual-Brain System

Traditional voice assistants suffer from an annoying tradeoff: either they rely on static rule trees (fast, but brittle), or they send every single breath to a heavy cloud LLM (smart, but slow and bloated).

Laya resolves this by borrowing Daniel Kahneman’s dual-process cognitive model:

```
                          User Speech (Right Ctrl PTT)
                                       │
                                       ▼
                       Faster-Whisper STT (base.en, ~35ms)
                                       │
                                       ▼
                         ┌───────────────────────────┐
                         │  Intent Router & Safety   │
                         └─────────────┬─────────────┘
                                       │
                 ┌─────────────────────┴─────────────────────┐
                 │                                           │
                 ▼ (< 5ms)                                   ▼ (Multi-Step ReAct)
        ┌─────────────────┐                         ┌─────────────────┐
        │  System 1 Brain │                         │  System 2 Brain │
        │ (Fast-Path / S1)│                         │ (Local Qwen 4B) │
        └────────┬────────┘                         └────────┬────────┘
                 │                                           │
                 │   • Hardware Volume (pycaw WASAPI <1ms)   │   • Web & Browser Automation
                 │   • Media Keys (Win32 keybd_event)        │   • Contextual Memory Retrieval
                 │   • App Launcher & Window Control         │   • Contest & Project Scaffolding
                 │   • Clock & System Telemetry              │   • GitHub Repo Management & Shell
                 │                                           │
                 └─────────────────────┬─────────────────────┘
                                       │
                                       ▼
                          Tool Execution & Observation
                                       │
                                       ▼
                        Edge-TTS Audio Streamer (<100ms)
                                       │
                                       ▼
                             Speaker / Headphones
```

### 1. System 1 (Fast-Path Reflexes — `< 5ms`)
- Unambiguous commands (volume changes, media pauses, app launching, time checks) bypass LLM generation completely.
- Direct Win32 WASAPI integration adjusts master endpoint audio natively with **zero subprocesses**.
- Delivers an instantaneous, sub-perception tactile feel.

### 2. System 2 (Reasoning & Autonomous Tool Loop)
- Powered by a local **Qwen 4B** model via Ollama (or cloud fallback).
- Implements a full **ReAct (Reasoning + Acting)** execution loop: observes tool outputs, chains dependencies, and synthesizes answers naturally.
- Equipped with automatic tool schema pruning to guarantee rapid inference and zero context distraction.

---

## 🚀 Key Capabilities

### 🔊 Speech & Hardware Audio
- **Push-to-Talk (PTT):** Ergonomic low-latency audio capture on `Right Ctrl`.
- **Fast Speech-to-Text:** `faster-whisper` (base.en with beam size 1) running with FP16/INT8 compute.
- **Natural Voice Synthesis:** Microsoft Edge Neural TTS streaming crystal-clear spoken responses.
- **Native WASAPI Volume:** Precise volume adjustment (`0-100%`, `up`, `down`, `mute`) without invoking PowerShell or external wrappers.
- **Spotify Integration:** Instant Spotify Web API playback alongside Windows desktop URI control.

### 🧠 Long-Term Memory & Proactivity
- **Associative Memory Engine:** Persistent SQLite store remembering facts, user preferences, and context across sessions.
- **Smart Scheduling & Reminders:** Natural language datetime parser understanding relative expressions (e.g. *"10 mins before next Friday at 9 PM"*).
- **Proactive Background Engine:** Async background scheduler tracking alarms, calendar events, and recurring cron triggers.

### 🌐 Browser & Web Intelligence
- **Live Search & Content Extraction:** `search_and_read` performs live search and parses webpage content directly to extract answers.
- **Web Automation:** Direct DOM interactions, URL inspection, and automated navigation.

### 💻 Developer & Workspace Scaffolding
- **Contest Scaffolding:** One-step creation of competitive programming directories (e.g. `ABC_481`), template discovery, analysis (`solve()` detection, fast I/O), and multi-file generation (`a.cpp` through `f.cpp`).
- **GitHub Repository Suite:** Create repositories, inspect repo lists, safely batch-clean forks, and publish local workspaces.
- **Shell Runner:** Safe execution of arbitrary terminal commands, tests, and scripts.

---

## 🛠️ Project Structure

```text
├── config/
│   ├── settings.example.yaml   # Sanitized configuration template
│   └── mcp_servers.json        # MCP server configuration
├── data/                       # Local SQLite databases (memory, scheduler)
├── logs/                       # Structured JSONL telemetry logs
├── src/
│   ├── core/
│   │   ├── agent.py            # Central Laya agent & ReAct loop orchestrator
│   │   ├── decision.py         # System 1 classifier & intent router
│   │   ├── memory.py           # Long-term associative memory store
│   │   ├── permissions.py      # Granular safety & confirmation layer
│   │   ├── proactive.py        # Proactive alert engine
│   │   └── scheduler.py        # Persistent SQLite task scheduler
│   ├── llm/
│   │   └── provider.py         # Ollama System 2 brain & dynamic schema pruning
│   ├── tools/
│   │   ├── app_tools.py        # Windows application launcher & process control
│   │   ├── browser_tools.py    # Web scraping, page reading & automation
│   │   ├── github_tools.py     # GitHub management & project publisher
│   │   ├── media_tools.py      # Spotify API & hardware media keys
│   │   ├── productivity_tools.py # Reminders, timers & natural datetime parsing
│   │   ├── scaffold_tools.py   # Contest scaffolding & file generator
│   │   ├── shell_tools.py      # Terminal command execution
│   │   └── system_tools.py     # Native WASAPI volume & telemetry
│   └── voice/
│       ├── listener.py         # Low-latency hotkey listener
│       ├── stt.py              # Faster-Whisper transcriber
│       └── tts.py              # Edge-TTS streaming voice output
└── scripts/
    └── run.py                  # Main entry point (CLI and Voice modes)
```

---

## 📦 Getting Started

### 1. Prerequisites
- **OS:** Windows 10/11
- **Python:** 3.10, 3.11, or 3.12
- **Ollama:** [Download Ollama](https://ollama.ai) and pull the lightweight reasoning model:
  ```bash
  ollama pull qwen3:4b
  ```

### 2. Installation
```powershell
# Clone the repository
git clone https://github.com/Polymorph0us/laya-voice-assistant.git
cd laya-voice-assistant

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install project dependencies
pip install -r requirements.txt
```

### 3. Configuration
Copy the template configuration file:
```powershell
copy config\settings.example.yaml config\settings.yaml
```
Edit `config/settings.yaml` with your optional API tokens (GitHub Personal Access Token, Spotify API credentials, or Gemini fallback key).

### 4. Running Laya

**Interactive Text Mode:**
```powershell
python scripts/run.py
```

**Full Voice Mode (Push-to-Talk on `Right Ctrl`):**
```powershell
python scripts/run.py --voice
```

---

## 🔒 Security & Safety Layers

Laya enforces a strict tripartite permission policy across all registered tools:
1. **`SAFE` (Auto-execute):** Volume changes, time queries, web search, reading files, and project scaffolding.
2. **`CONFIRMATION_REQUIRED`:** Actions altering state or creating external resources.
3. **`DANGEROUS` (Explicit User Approval):** Batch deleting repositories, destroying files, or modifying critical system settings. Laya pauses execution and prompts the user before proceeding.

---

## 🌟 License

Released under the **MIT License**. Feel free to inspect, fork, and build upon this architecture.

<div align="center">
<sub>Crafted with passion, speed, and precision by Keerthan D & Laya.</sub>
</div>
"""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(readme_content, encoding="utf-8")
        return ToolResult(
            success=True,
            message=f"Successfully generated detailed personality-infused README at {path.name} ({len(readme_content)} characters).",
            data={"path": str(path), "chars": len(readme_content)},
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e), message=f"Failed to generate README: {e}")



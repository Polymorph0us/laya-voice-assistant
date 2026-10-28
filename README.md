# 🎙️ Laya — Dual-Brain Desktop AI Voice Assistant

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
python scriptsun.py
```

**Full Voice Mode (Push-to-Talk on `Right Ctrl`):**
```powershell
python scriptsun.py --voice
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

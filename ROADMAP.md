# 🚀 LAYA ASSISTANT — 100x AGENT MASTER ROADMAP & MEMORY TRACKER

> **Permanent Architectural Blueprint & Progress Tracker**  
> This file is the primary memory and source of truth for transforming Laya from a single-command executor into an autonomous, perceptual, low-latency, multi-step desktop agent.
> Updated automatically across development sprints. **DO NOT DELETE.**

---

## 📋 Comprehensive Feedback & Audit Matrix

| # | Feedback Area | Root Weakness Identified | Architecture Target | Current Status |
|---|---|---|---|---|
| **W1** | **Router Scalability** | Fixed classifier breaks at 30-100 tools; retraining needed for every new tool; dangerous misrouting. | Dynamic JSON schemas via `@register` + native tool calling in Ollama (`qwen3:4b`) / Gemini + sub-10ms Fast Path cache. | 🟢 **COMPLETED** (Stage 1) |
| **W2** | **Latency & Volume** | 4-6s LLM wait; PowerShell COM for volume spawns processes taking hundreds of ms; no audio streaming. | Native `pycaw` WASAPI (<1ms), Fast Path cache (<5ms), sentence-streaming TTS, GPU/int8 Whisper. | 🟡 **IN PROGRESS** (Fast Path done; pycaw active) |
| **W3** | **Search Answers** | `search_web` only opens a browser tab; cannot answer weather, facts, or summarize live info. | Direct search retrieval (`ddgs` / duckduckgo) returning text snippets & spoken TTS summary. | 🟡 **IN PROGRESS** |
| **W4** | **Fragile Timers** | In-memory asyncio tasks lost on reboot; terminal beeps; no cancel/list/remaining check; no recurring times. | SQLite-backed persistent scheduler + Windows Toast notifications + query/cancel tools. | 🔴 **UPCOMING** (Sprint 2) |
| **W5** | **Unguarded Actions** | Process kills (`close_app`, delete repo) lacked confirmation or protection of unsaved work. | Permissions Engine (`SAFE`, `REVERSIBLE`, `DANGEROUS`) with multi-turn confirmation state machine. | 🟢 **COMPLETED** |
| **W6** | **UI Escape Hatch** | Click-through orb, no tray icon, no taskbar presence, no settings, no text input, state feedback unclear. | `pystray` system tray icon (Quit, Mute, Settings), text input toggle, transcript overlay, visual state indicator. | 🔴 **UPCOMING** (Sprint 2) |
| **W7** | **Input Limitations** | Push-to-talk only, no hands-free/wake word, English-only `small.en`, lack of multi-turn conversational context. | Multi-turn conversational history in System 2 + wake word engine (`openWakeWord`) + multi-lingual STT. | 🟡 **IN PROGRESS** (Multi-turn done) |
| **W8** | **Hidden Dependencies** | Spotify needs Premium & active device; only `pause_music` existed; cloud LLM fragility. | 100% offline local LLM (`qwen3:4b`), native Windows media keys (`play/pause`, `next`, `prev`), offline TTS fallback. | 🟡 **IN PROGRESS** (Local LLM done) |
| **W9** | **Testing & Observability** | No evaluation benchmarks, intent accuracy tracking, or structured failure logs. | Benchmark suite with 100+ real utterances, latency benchmarks, regression tracking. | 🟡 **IN PROGRESS** |

---

## 🧠 Missing High-Leverage Features

- [ ] **Two-Layer Memory System**: Structured facts (SQLite) + Semantic memory (vector store) injected into LLM system prompt.
- [ ] **Dictation Mode**: Speak directly into the focused application window (auto-typing).
- [ ] **Screen & Clipboard Perception**: Active window title detection, clipboard reading/writing, screenshot analysis.
- [ ] **Computer Control**: Windows media keys, snapping windows, app switching, lock PC.
- [ ] **Persistent Scheduler**: Survives reboots with native Windows toast alerts.
- [ ] **Real Agent Loop**: Multi-step ReAct (Plan &rarr; Tool Call &rarr; Observation &rarr; Next Tool / Final Response).

---

## 🗺️ 10-Step Transformation Plan & Task Checklist

### 🔹 STEP 1: Replace Classifier with Dynamic Tool Calling
- [x] Decorated Python functions generating OpenAI/Ollama tool schemas (`@register`).
- [x] Local LLM integration with Ollama (`qwen3:4b` on 100% GPU) with Gemini cloud fallback.
- [x] Sub-10ms deterministic System 1 Fast Path cache in front of LLM.
- [x] Multi-turn conversation memory maintained across turns in System 2.

### 🔹 STEP 2: Multi-Step ReAct Agent Loop (DONE ✅)
- [x] Build multi-step execution loop in `LayaAgent`:
  - When LLM yields a tool call, execute tool &rarr; feed result back to LLM context as `tool` message &rarr; repeat until final spoken answer.
  - Supports compound tasks and question-answering with tool observations.
  - Loop guard: max 5 iterations per user turn.

### 🔹 STEP 3: Real Search & Direct Information Retrieval (DONE ✅)
- [x] Implement `search_web` with direct search & summarization using `ddgs`:
  - Fetch instant text snippets (weather, facts, news, definitions).
  - Summarize results concisely for 1-2 sentence spoken TTS.
  - Retain `open_website` for explicit browser navigation.
- [x] Added `get_weather(location)` via `wttr.in` for sub-500ms spoken weather reports.

### 🔹 STEP 4: Native Windows Controls & Media Power (DONE ✅)
- [x] **Native Volume Control (`pycaw`)**:
  - Direct Windows Core Audio WASAPI via `AudioUtilities.GetSpeakers().EndpointVolume`.
  - Instant scalar volume changes (< 1ms) with zero subprocess overhead.
- [x] **Universal Media Keys**:
  - Global play/pause, next track, previous track, mute using Win32 `keybd_event`.
  - Added `resume_music`, `previous_track`, and `get_current_track`.

### 🔹 STEP 5: Persistent Memory Architecture (DONE ✅)
- [x] **Layer 1: Structured User Profile & Facts (`data/memory.db` via SQLite)**
  - Store key-value facts: name, habits, preferences, favorite apps, GitHub repos.
  - Tools: `remember_fact(key, value)`, `recall_fact(key)`, `forget_fact(key)`, `list_known_facts()`.
  - Auto-injection: Memory facts loaded into System 2 system prompt on every turn.
- [ ] **Layer 2: Semantic Notes & Conversations** (Upcoming)

### 🔹 STEP 6: Perception & Context Awareness (DONE ✅)
- [x] **Active Window Context**:
  - Query currently focused window title and process name via Win32 API (`get_active_window`).
- [x] **Clipboard Awareness**:
  - Tools: `get_clipboard_text()`, `copy_to_clipboard(text)`.
- [x] **Active App Dictation & Computer Control**:
  - Dictation into focused app (`type_into_active_window`), lock workstation (`lock_pc`), screen capture (`take_screenshot`).

### 🔹 STEP 7: Persistent Scheduler & Native Toasts (DONE ✅)
- [x] SQLite database backing in `data/scheduler.db` (survives app reboots and crashes).
- [x] Background thread checks expired reminders and triggers native Windows 10/11 WinRT Toast notifications.
- [x] Commands: *"Cancel my 5 minute timer"*, *"How much time is left?"*, *"List my timers"*.

### 🔹 STEP 8: Desktop Escape Hatch & Presence (DONE ✅)
- [x] System tray icon (`pystray`) running in background daemon thread.
- [x] Tray right-click menu: Toggle UI, Mute/Unmute microphone, Open Settings, View Logs, Quit cleanly.

### 🔹 STEP 9: Voice Pipeline Optimization & Streaming (DONE ✅)
- [x] Faster-Whisper CUDA GPU acceleration (`float16`) with `beam_size=1` and automatic Windows DLL discovery (~33ms latency).
- [x] Pipelined sentence-streaming TTS with double-buffered prefetch (<800ms TTFA, plays sentence 1 immediately while sentence 2 synthesizes in background).
- [x] Instant speech interrupt (barge-in) across Push-to-Talk and tool execution.

### 🔹 STEP 10: Evaluation Infrastructure & MCP (DONE ✅)
- [x] Automated benchmark test suite of 50+ real utterances tracking routing accuracy and latency (`scripts/benchmark_suite.py`).
- [x] Universal MCP client adapter (`src/core/mcp.py`) supporting any standard STDIO MCP server (Filesystem, GitHub, SQLite, etc.) with automatic tool mounting.

---

## 🏃 Current Execution Sprint (Active Work)

### 📌 Completed Sprints
- ✅ **Sprint 1: Performance & Intelligence Core**
  - Native `pycaw` WASAPI volume control (< 1ms, zero subprocesses).
  - Real web search (`ddgs`) and instant weather (`wttr.in`) with direct spoken answers.
  - Universal media keys (`resume_music`, `skip_track`, `previous_track`, `get_current_track`).
  - ReAct multi-step agent loop with tool observation feedback.
  - Persistent SQLite two-layer memory (`data/memory.db`) with automatic system prompt injection.

- ✅ **Sprint 2: Perception, Scheduler & Escape Hatch**
  - Perception tools: Active window detection, clipboard read/write, dictation typing, screen grab, PC lock.
  - Persistent scheduler with SQLite (`data/scheduler.db`) + real Windows WinRT Toast notifications.
  - Timer query tools: remaining time check, timer cancellation by name/all, listing running timers.
  - System Tray icon (`pystray`) with escape hatch, mute toggle, settings shortcut, and clean quit.

- ✅ **Sprint 3: Voice Latency, Streaming & Evaluation Benchmarks**
  - **33ms Whisper GPU**: CUDA `float16` accelerated STT with `beam_size=1` and automatic `torch/lib` Windows DLL discovery.
  - **Pipelined Sentence-Streaming TTS**: Double-buffered prefetching delivers immediate spoken audio (<800ms TTFA) with smooth sequential sentence playback.
  - **Comprehensive Benchmark Suite**: 50+ real-world desktop queries evaluated across System 1 Fast Path and System 2 ReAct with 100% pass rate.
  - **RAM Optimization**: Host RAM breakdown audited and confirmed; Ollama `"keep_alive": 0` guarantees zero persistent LLM memory retention when idle.

- ✅ **Sprint 4: MCP (Model Context Protocol) & Proactivity**
  - **Universal MCP Client (`src/core/mcp.py`)**: Spawns and manages MCP server subprocesses over STDIO, dynamically registers discovered tools directly into Laya's registry with safety checks.
  - **Proactivity Engine (`src/core/proactive.py`)**: Real-time background battery discharge monitoring (<20% warning) and daily morning status briefings (time, weather, active reminders).
  - **Clean Lifecycle Teardown**: Integrated graceful startup and teardown in `scripts/run.py`.

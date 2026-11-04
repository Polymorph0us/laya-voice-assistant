"""
System 2 (LLM) Provider — Ollama (Local) + Gemini (Cloud) Fallback.

Supports:
- Native multi-step tool calling (ReAct observation loop)
- Persistent SQLite memory injection (User Profile & Facts)
- Conversational context history
- Qwen3 reasoning tag cleaning
"""

from __future__ import annotations

import json
import re
import httpx
from typing import Any

from src.utils.logger import get_logger
from src.tools.registry import get_tool, _TOOLS

logger = get_logger("llm.provider")


def _build_tool_schemas(messages: list[dict] | None = None) -> list[dict]:
    """
    Build OpenAI-compatible tool schemas from the tool registry.
    Dynamically prunes heavy or sensitive tool subsets (e.g. MCP filesystem, GitHub)
    unless the current conversation context explicitly mentions them.
    This prevents small local models (4B) from suffering context distraction or
    wandering into unprompted disk searches.
    """
    from src.tools.registry import ensure_tools_loaded
    ensure_tools_loaded()

    # Determine conversational domain context
    user_requests_text = ""
    context_text = ""
    if messages:
        for m in messages:
            content = m.get("content")
            text_val = ""
            if isinstance(content, str):
                text_val = content.lower()
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        text_val += " " + part["text"].lower()
            context_text += " " + text_val
            if m.get("role") == "user":
                user_requests_text += " " + text_val

    file_keywords = (
        "file", "files", "folder", "folders", "directory", "directories",
        "document", "documents", "read file", "write file", "save file",
        "create file", "delete file", "list directory", "disk", "path",
        ".txt", ".pdf", ".docx", ".csv", ".json", ".py", ".md", ".cpp", "cpp", "c++",
        "assignment", "scaffold", "create a folder", "create folder", "template", "project", "readme"
    )

    disk_keywords = (
        "unneeded", "unnecessary", "unused", "usetime", "use time", "usage",
        "cleanup", "clean", "junk", "temp", "cache", "storage", "free space",
        "disk space", "installer", "installers", "downloads", "large file", "large files"
    )
    has_file_context = any(kw in context_text for kw in file_keywords) if context_text else False
    has_disk_context = any(kw in context_text for kw in disk_keywords) or has_file_context

    github_keywords = (
        "github", "repo", "repos", "repository", "repositories", "fork", "forks",
        "commit", "clone", "push", "public", "private", "visibility"
    )
    has_github_context = any(kw in context_text for kw in github_keywords) if context_text else False

    shell_keywords = ("shell", "terminal", "command", "cmd", "powershell", "bash", "execute", "run", "git", "npm", "pip", "pytest", "python", "script")
    has_shell_context = any(kw in context_text for kw in shell_keywords) if context_text else False

    tools = []
    for name, registered_tool in _TOOLS.items():
        if not registered_tool.definition.enabled:
            continue

        # Prune disk analysis & cleanup tools unless disk/file cleanup context
        if name in ("analyze_unneeded_files", "clean_unneeded_files") and not has_disk_context:
            continue

        # Only expose destructive clean_unneeded_files if user explicitly asked to clean or delete
        clean_intent = any(w in user_requests_text for w in ("clean", "cleanup", "delete", "purge", "remove", "clear", "wipe"))
        if name == "clean_unneeded_files" and not clean_intent:
            continue

        # Prune MCP filesystem tools and native file tools unless user requested file/folder operations
        if (name.startswith("mcp_filesystem_") or name in ("scaffold_project", "create_file", "read_file_content", "generate_project_readme")) and not has_file_context:
            continue

        # Prune GitHub repo management tools unless user requested GitHub operations
        if name in ("cleanup_forked_repos", "create_github_repo", "delete_github_repo", "list_github_repos", "git_push_project", "update_github_repo") and not has_github_context:
            continue

        # Prune shell tools unless user requested shell/command/github operations
        if name in ("run_shell_command",) and not (has_shell_context or has_github_context):
            continue

        properties = {}
        required = []
        for p in registered_tool.definition.parameters:
            json_type = "string"
            if p.type == "integer":
                json_type = "integer"
            elif p.type == "boolean":
                json_type = "boolean"
            elif p.type == "float":
                json_type = "number"

            properties[p.name] = {
                "type": json_type,
                "description": p.description,
            }
            if p.required:
                required.append(p.name)

        tool_schema = {
            "type": "function",
            "function": {
                "name": registered_tool.definition.name,
                "description": registered_tool.definition.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
        tools.append(tool_schema)

    return tools


class System2:
    """
    LLM brain for Laya. Tries Ollama (local) first, Gemini (cloud) second.
    """

    def __init__(
        self,
        api_key: str = "",
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "qwen3:4b",
    ):
        self.ollama_url = ollama_url.rstrip("/")
        self.ollama_model = ollama_model
        self.gemini_api_key = api_key
        self.tool_schemas = _build_tool_schemas()
        self.history: list[dict[str, Any]] = []

        # Check Ollama availability at init
        self._ollama_available = False
        self._gemini_available = False

        try:
            resp = httpx.get(f"{self.ollama_url}/api/tags", timeout=2.0)
            if resp.status_code == 200:
                self._ollama_available = True
                models = [m["name"] for m in resp.json().get("models", [])]
                if any(ollama_model.split(":")[0] in m for m in models):
                    logger.info(
                        f"System 2: Ollama '{ollama_model}' ready at {ollama_url} with {len(self.tool_schemas)} tools."
                    )
                else:
                    logger.warning(
                        f"Ollama is running but model '{ollama_model}' not found. "
                        f"Available: {models}. Run: ollama pull {ollama_model}"
                    )
                    self._ollama_available = False
        except Exception:
            logger.info("Ollama not detected at localhost:11434.")

        # Check Gemini as fallback
        if api_key:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=api_key)
                self._gemini_available = True
                logger.info("System 2: Gemini cloud fallback available.")
            except Exception as e:
                logger.warning(f"Gemini fallback unavailable: {e}")
                self._gemini_client = None
        else:
            self._gemini_client = None

        if not self._ollama_available and not self._gemini_available:
            logger.warning("System 2 is fully disabled. Install Ollama or provide a Gemini API key.")

    def is_available(self) -> bool:
        return self._ollama_available or self._gemini_available

    def get_system_prompt(self) -> str:
        """Construct the base system prompt including persistent user memory, current datetime, and tools guidance."""
        import datetime

        now = datetime.datetime.now()
        current_time_str = now.strftime("%A, %B %d, %Y, %I:%M %p")

        base = (
            "You are Laya, an intelligent AI desktop voice assistant running locally on the user's computer. "
            f"CURRENT SYSTEM DATE & TIME: {current_time_str}. Use this to resolve relative dates like 'today', 'tomorrow', 'next Friday', or specific dates. "
            "You have access to system and browser automation tools. If the user asks you to do something actionable "
            "(open an app, play music, set a timer/reminder, search the web, read webpages, automate browser actions, manage GitHub repos, check time/date, remember/recall facts), use the appropriate tool. "
            "\n\nTool Selection Rules:"
            "\n- Event Reminders: If the user asks to set a reminder for an event (e.g. 'the next AtCoder contest on Oct 24', 'F1 race', 'meeting') whose exact time is uncertain or unstated, FIRST call 'search_and_read' or 'search_web' to look up the official schedule and time! Once you get the event date/time from the web results, IMMEDIATELY call 'set_reminder' with the task and target_time (e.g. task='AtCoder Beginner Contest 481', target_time='10 mins before 2026-10-24 21:00:00+0900' or '2026-10-24 20:50:00')."
            "\n- NEVER search local files or call filesystem tools when setting event reminders. Complete the reminder using 'set_reminder'."
            "\n- Reminders vs Memory: ALWAYS use 'set_reminder' for reminders, alerts, or alarms. NEVER call 'remember_fact' for reminders or time-based tasks."
            "\n- Project & Contest Scaffolding: When the user asks to create a folder structure, contest folder (like AtCoder, Codeforces, ABC), or batch-create files with templates, call 'scaffold_project'. Pass base_dir (e.g. 'Documents/projects/cf/contests/AtCoder/ABC_481'), files (e.g. 'a.cpp, b.cpp, c.cpp, d.cpp, e.cpp, f.cpp'), and template_source (e.g. 'template.cpp'). It automatically creates the folder structure, creates all files, finds the existing template, copies it into the new folder, and analyzes the template in a single step."
            "\n- GitHub & Publishing Projects: When the user asks to create a new GitHub repo, write a detailed README with personality, and push this project: First call 'generate_project_readme' to generate the full README.md with your unique persona. Next, call 'git_push_project' with repo_name (e.g. 'laya-voice-assistant') and commit_message. It automatically creates the repo on GitHub if needed, initializes git, stages project files respecting .gitignore, commits, and pushes directly to GitHub in one complete step! To update repository visibility (make public or private), description, or topics, call 'update_github_repo'. You also have 'run_shell_command' for arbitrary terminal commands."
            "\n- File & Disk Usage Analysis: When the user asks to analyze files, find unnecessary or unneeded files based on usage/access time, or inspect disk space, call 'analyze_unneeded_files'. Once you receive the analysis result, synthesize and report the findings directly to the user (total gigabytes, top old installers, and temporary cache); do NOT call 'clean_unneeded_files' unless the user explicitly told you to delete or clean them."
            "\n- Filesystem Privacy: NEVER inspect, list, or read files, documents, or directories on disk unless the user explicitly requested a file/document operation."
            "\n- Browser & Web Access: You have direct browser capabilities! Use 'read_webpage' to inspect live URLs, 'search_and_read' to extract live answers from web pages, and 'browser_interact' to click or automate web forms."
            "\n- Pay close attention to conversation history when the user refers to previous context ('them', 'it', 'yes', 'proceed', etc.). "
            "When tool results are provided to you, summarize the essential facts naturally and concisely in 1-2 spoken sentences. "
            "Keep all responses short, clear, and conversational — they will be spoken aloud via TTS. "
            "Do NOT use markdown, bullet points, asterisks, or emoji. Speak in plain English."
        )
        try:
            from src.core.memory import memory
            mem_ctx = memory.format_prompt_context()
            if mem_ctx:
                base += f"\n\n{mem_ctx}"
        except Exception:
            pass

        return base

    async def chat_turn(self, messages: list[dict], use_tools: bool = True) -> dict[str, Any]:
        """
        Execute one turn in a conversation loop.
        Takes full messages history and returns:
          {"type": "text", "content": "..."}
          {"type": "tool_call", "tool": "name", "arguments": {...}, "raw_message": {...}}
          {"type": "error", "content": "..."}
        """
        if not self.is_available():
            return {
                "type": "error",
                "content": "My brain is not active. Please install Ollama or add a Gemini API key.",
            }

        if self._ollama_available:
            return await self._ollama_chat_turn(messages, use_tools)
        else:
            return await self._gemini_chat_turn(messages, use_tools)

    async def generate_response(self, user_input: str) -> dict[str, Any]:
        """Single-turn generation wrapper."""
        messages = [
            {"role": "system", "content": self.get_system_prompt()},
            *self.history[-6:],
            {"role": "user", "content": user_input},
        ]
        return await self.chat_turn(messages, use_tools=True)

    # ── Ollama (Local) Implementation ─────────────────────────────────────────

    async def _ollama_chat_turn(self, messages: list[dict], use_tools: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.ollama_model,
            "messages": messages,
            "stream": False,
            # Unload model from RAM immediately after each response.
            # Frees ~3.2 GB when idle. Cold-start on next LLM query is ~1-2s
            # which is fine — the LLM is a fallback, not the primary path.
            "keep_alive": 0,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
            },
        }
        if use_tools:
            # Refresh schemas filtered by current conversation messages
            self.tool_schemas = _build_tool_schemas(messages)
            payload["tools"] = self.tool_schemas

        try:
            import asyncio

            def _call():
                return httpx.post(
                    f"{self.ollama_url}/api/chat",
                    json=payload,
                    timeout=45.0,
                )

            resp = await asyncio.to_thread(_call)

            if resp.status_code != 200:
                logger.error(f"Ollama returned {resp.status_code}: {resp.text[:200]}")
                return {"type": "error", "content": f"Ollama error ({resp.status_code})."}

            data = resp.json()
            message = data.get("message", {})

            # Check for tool calls
            tool_calls = message.get("tool_calls", [])
            if tool_calls:
                parsed_calls = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    fn_name = func.get("name", "")
                    if fn_name:
                        parsed_calls.append({"tool": fn_name, "arguments": args})

                if len(parsed_calls) > 1:
                    return {
                        "type": "tool_calls",
                        "tool_calls": parsed_calls,
                        "raw_message": message,
                    }
                elif len(parsed_calls) == 1:
                    return {
                        "type": "tool_call",
                        "tool": parsed_calls[0]["tool"],
                        "arguments": parsed_calls[0]["arguments"],
                        "raw_message": message,
                    }

            # Plain text response
            content = message.get("content", "").strip()
            # Qwen3 sometimes wraps thinking in <think> tags — strip them
            if "<think>" in content:
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

            clean_str = content.strip()

            # Check for XML-wrapped tool calls like <function_call>...</function_call> or <tool_call>...</tool_call>
            fn_tag_match = re.search(r"<(?:function_call|tool_call)>\s*(.*?)\s*</(?:function_call|tool_call)>", clean_str, flags=re.DOTALL)
            if fn_tag_match:
                clean_str = fn_tag_match.group(1).strip()

            # Strip markdown code blocks if wrapped in ```json ... ```
            clean_str = re.sub(r"^```(?:json)?\s*", "", clean_str)
            clean_str = re.sub(r"\s*```$", "", clean_str).strip()

            # Check if model outputted a JSON list of tool calls inside content
            if clean_str.startswith("[") and ("\"name\"" in clean_str or "\"function\"" in clean_str):
                try:
                    parsed_list = json.loads(clean_str)
                    if isinstance(parsed_list, list) and parsed_list:
                        from src.tools.registry import get_tool
                        calls = []
                        for item in parsed_list:
                            if isinstance(item, dict):
                                fn_name = item.get("function") or item.get("name")
                                fn_args = item.get("arguments", {})
                                if fn_name and get_tool(fn_name):
                                    if isinstance(fn_args, str):
                                        try:
                                            fn_args = json.loads(fn_args)
                                        except Exception:
                                            pass
                                    calls.append({"tool": fn_name, "arguments": fn_args if isinstance(fn_args, dict) else {}})
                        if len(calls) > 1:
                            return {"type": "tool_calls", "tool_calls": calls, "raw_message": message}
                        elif len(calls) == 1:
                            return {"type": "tool_call", "tool": calls[0]["tool"], "arguments": calls[0]["arguments"], "raw_message": message}
                except Exception:
                    pass

            # Check if model outputted a single JSON tool call inside content
            if clean_str.startswith("{") and ("\"name\"" in clean_str or "\"function\"" in clean_str):
                try:
                    parsed = json.loads(clean_str)
                    func_name = parsed.get("function") or parsed.get("name")
                    func_args = parsed.get("arguments", {})
                    if func_name and isinstance(func_name, str):
                        from src.tools.registry import get_tool
                        if get_tool(func_name):
                            if isinstance(func_args, str):
                                try:
                                    func_args = json.loads(func_args)
                                except Exception:
                                    pass
                            return {
                                "type": "tool_call",
                                "tool": func_name,
                                "arguments": func_args if isinstance(func_args, dict) else {},
                                "raw_message": message,
                            }
                except Exception:
                    pass

            # Check if model outputted a python-style function call inside content
            # e.g., set_reminder(target_time="2026-10-24 20:50:00", task="AtCoder")
            clean_code = re.sub(r"^```(?:python)?\s*", "", content)
            clean_code = re.sub(r"\s*```$", "", clean_code).strip()
            if "(" in clean_code and clean_code.endswith(")"):
                try:
                    import ast
                    tree = ast.parse(clean_code)
                    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Call):
                        call = tree.body[0].value
                        func_name = getattr(call.func, "id", None)
                        if func_name and isinstance(func_name, str):
                            from src.tools.registry import get_tool
                            if get_tool(func_name):
                                func_args = {}
                                for kw in call.keywords:
                                    try:
                                        func_args[kw.arg] = ast.literal_eval(kw.value)
                                    except Exception:
                                        func_args[kw.arg] = str(kw.value)
                                return {
                                    "type": "tool_call",
                                    "tool": func_name,
                                    "arguments": func_args,
                                    "raw_message": message,
                                }
                except Exception:
                    pass

            text_reply = content or "I am ready."
            return {
                "type": "text",
                "content": text_reply,
                "raw_message": message,
            }

        except httpx.TimeoutException:
            logger.error("Ollama request timed out.")
            return {"type": "error", "content": "My local brain took too long to respond."}
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return {"type": "error", "content": f"Local LLM error: {e}"}

    # ── Gemini (Cloud Fallback) Implementation ────────────────────────────────

    async def _gemini_chat_turn(self, messages: list[dict], use_tools: bool = True) -> dict[str, Any]:
        """Cloud fallback using Gemini."""
        if not self._gemini_client:
            return {"type": "error", "content": "Gemini is not configured."}

        # Convert simple messages to prompt
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        prompt = (
            f"{self.get_system_prompt()}\n\n"
            f"User: {last_user}"
        )

        try:
            import asyncio
            from google.genai import types

            gemini_tools = []
            if use_tools:
                self.tool_schemas = _build_tool_schemas(messages)
                for schema in self.tool_schemas:
                    fn = schema["function"]
                    gemini_tools.append(
                        types.Tool(
                            function_declarations=[
                                {
                                    "name": fn["name"],
                                    "description": fn["description"],
                                    "parameters": fn["parameters"],
                                }
                            ]
                        )
                    )

            config = types.GenerateContentConfig(
                tools=gemini_tools if gemini_tools else None,
                temperature=0.7,
            )
            response = await asyncio.to_thread(
                self._gemini_client.models.generate_content,
                model="gemini-2.0-flash",
                contents=prompt,
                config=config,
            )

            if response.function_calls:
                fc = response.function_calls[0]
                return {
                    "type": "tool_call",
                    "tool": fc.name,
                    "arguments": {k: v for k, v in fc.args.items()},
                    "raw_message": {},
                }

            return {
                "type": "text",
                "content": response.text.strip() if response.text else "Done.",
                "raw_message": {},
            }

        except Exception as e:
            logger.error(f"Gemini error: {e}")
            return {"type": "error", "content": f"Cloud LLM error: {e}"}

    def record_interaction(self, user_text: str, assistant_text: str) -> None:
        """Record completed conversational turn in memory history."""
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": assistant_text})
        if len(self.history) > 10:
            self.history = self.history[-10:]

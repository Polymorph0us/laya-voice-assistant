"""
Main agent orchestrator.

Coordinates the flow:
Input → Laya Decision → Confidence Routing → Permission Check → Tool Execution
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.core.confidence import RouteAction, determine_route
from src.core.decision import DecisionEngine, LayaDecision
from src.core.permissions import EnforcementAction, check_permissions
from src.tools.base import ToolResult
from src.tools.registry import execute_tool, get_tool
from src.utils.config import AppConfig
from src.utils.logger import generate_request_id, get_logger, log_event
from src.llm.provider import System2

logger = get_logger("core.agent")


class LayaAgent:
    """The central orchestrator for the Laya assistant."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.decision_engine = DecisionEngine(config)
        self.system2 = System2(
            api_key=config.llm.api_key,
            ollama_url=getattr(config.llm, "ollama_url", "http://localhost:11434"),
            ollama_model=getattr(config.llm, "ollama_model", "qwen3:4b"),
        )
        self._pending_confirmation: dict[str, Any] | None = None
        logger.info("LayaAgent initialized")

    async def process_request(self, user_input: str) -> str:
        """
        Process a natural language request end-to-end.
        """
        req_id = generate_request_id()
        log_event(logger, f"Processing request: '{user_input}'", request_id=req_id)

        # ── Check pending confirmation state ──────────────────────────────────
        clean_input = user_input.strip().lower()
        if self._pending_confirmation:
            # Affirmative confirmation (e.g. "yes", "confirmed you may proceed", "proceed", "go ahead")
            if re.search(r"\b(yes|confirm|confirmed|proceed|go ahead|do it|sure|ok|affirmative|yeah|yup|please do)\b", clean_input):
                pending = self._pending_confirmation
                self._pending_confirmation = None
                log_event(logger, f"User confirmed action: {pending['tool_name']}", request_id=req_id)
                result = await execute_tool(pending["tool_name"], pending["arguments"])
                return self._build_response(result)

            # Negative cancellation (e.g. "no", "cancel", "abort", "don't", "stop")
            if re.search(r"\b(no|cancel|stop|abort|don't|dont|nevermind|nope|wait)\b", clean_input) and not re.search(r"\b(delete|cleanup|remove)\b", clean_input):
                self._pending_confirmation = None
                log_event(logger, "User cancelled action", request_id=req_id)
                return "Cancelled. I won't perform that action."

        # ── Pre-processing: compound command detection ───────────────────────
        # e.g. "open brave and go to reddit" → open_website("reddit.com")
        # e.g. "open a new tab in chrome and search for python"
        compound = self._detect_compound_command(user_input)
        if compound:
            results = []
            for sub_input in compound:
                resp = await self._execute_single(sub_input, req_id)
                results.append(resp)
            return " | ".join(results)

        return await self._execute_single(user_input, req_id)

    async def _execute_single(self, user_input: str, req_id: str = "") -> str:
        """Run a single (non-compound) request through the full pipeline."""
        
        # ── Pre-processing: intercept simple greetings & identity ─────────────
        clean_input = user_input.strip().lower()
        if re.fullmatch(r"(hello|hi|hey|greetings|good morning|good afternoon|good evening|yo|sup)( laya)?(!)?", clean_input):
            return "Hello! How can I help you today?"
            
        if re.fullmatch(r"(what is ur name|what is your name|who are you|what are you)( laya)?(\?)?", clean_input):
            return "I am Laya, your personal AI assistant!"
            
        if re.fullmatch(r"(how are you|how are you doing|hows it going)( laya)?(\?)?", clean_input):
            return "I'm doing great! How can I help you today?"
            
        if re.fullmatch(r"(what can you do|help)( laya)?(\?)?", clean_input):
            return "I can open apps, search the web, play music on Spotify, check the time, set timers, and control system volume. What would you like to do?"

        # ── Pre-processing: System 1 (Fast Path) ──────────────────────────────
        # Instant execution (< 5ms) for unambiguous actions without waiting for LLM
        fast = self._try_fast_path(clean_input)
        if fast:
            tool_name, arguments = fast
            logger.info(f"Fast path triggered: {tool_name} with {arguments}")
            result = await execute_tool(tool_name, arguments)
            return self._build_response(result)

        # 1. System 2 (LLM: Ollama local / Gemini fallback) ReAct Multi-Step Loop
        if self.system2.is_available():
            messages = [
                {"role": "system", "content": self.system2.get_system_prompt()},
                *self.system2.history[-6:],
                {"role": "user", "content": user_input},
            ]

            max_steps = 5
            executed_calls: list[str] = []
            for step in range(max_steps):
                response = await self.system2.chat_turn(messages, use_tools=True)

                if response["type"] == "text":
                    final_text = response["content"]

                    # Check if user asked for a reminder, but LLM stopped at reporting info without setting it
                    user_wants_reminder = any(w in user_input.lower() for w in ("remind", "reminder", "alarm"))
                    reminder_set = any("set_reminder" in c for c in executed_calls)
                    if user_wants_reminder and not reminder_set and executed_calls and step < max_steps - 1:
                        logger.info("User requested a reminder, but LLM replied with text before invoking set_reminder. Nudging model to complete action.")
                        messages.append({"role": "assistant", "content": final_text})
                        messages.append({
                            "role": "user",
                            "content": "Now invoke 'set_reminder' with the task and target_time to finish setting the reminder."
                        })
                        continue

                    self.system2.record_interaction(user_input, final_text)
                    return final_text

                if response["type"] in ("tool_call", "tool_calls"):
                    calls_to_execute = (
                        response["tool_calls"]
                        if response["type"] == "tool_calls"
                        else [{"tool": response["tool"], "arguments": response["arguments"]}]
                    )

                    for call_item in calls_to_execute:
                        tool_name = call_item["tool"]
                        arguments = call_item.get("arguments", {})

                        # Prevent repeating the exact same tool call in an infinite loop
                        call_sig = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
                        if call_sig in executed_calls:
                            logger.warning(
                                f"ReAct loop detected repeating tool call '{tool_name}' with identical arguments. Skipping duplicate."
                            )
                            continue
                        executed_calls.append(call_sig)

                        # Check permissions
                        tool = get_tool(tool_name)
                        if not tool:
                            messages.append({"role": "tool", "content": f"Unknown tool: {tool_name}"})
                            continue

                        decision = LayaDecision(
                            intent=tool_name,
                            intent_confidence=1.0,
                            intent_probabilities={},
                            needs_confirmation=0.0,
                            needs_system2=1.0,
                            latency_ms=0.0,
                            model_used=getattr(self.config.llm, "provider", "ollama"),
                            raw_result={}
                        )
                        enforcement = check_permissions(tool_name, decision)

                        if enforcement == EnforcementAction.DENY:
                            return f"I'm not permitted to run '{tool_name}'."

                        if enforcement == EnforcementAction.REQUIRE_CONFIRM:
                            self._pending_confirmation = {
                                "tool_name": tool_name,
                                "arguments": arguments,
                            }
                            args_display = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
                            return (
                                f"[Confirm] Shall I {tool_name.replace('_', ' ')}({args_display})? "
                                "Please reply 'yes' to proceed or 'no' to cancel."
                            )

                        # Execute tool
                        result = await execute_tool(tool_name, arguments)
                        tool_output = result.message or ("Success" if result.success else f"Error: {result.error}")

                        messages.append({
                            "role": "assistant",
                            "tool_calls": [{"function": {"name": tool_name, "arguments": arguments}}]
                        })
                        messages.append({
                            "role": "tool",
                            "content": tool_output,
                        })

                    # Observations recorded, continue loop so LLM synthesizes or performs next step
                    continue

                if response["type"] == "error":
                    logger.warning(f"System 2 returned error: {response['content']}, falling back to System 1")
                    break

            # If the loop ended after executing tools, synthesize a final spoken response from observations
            if executed_calls:
                summary_resp = await self.system2.chat_turn(messages, use_tools=False)
                if summary_resp.get("type") == "text" and summary_resp.get("content"):
                    final_text = summary_resp["content"]
                    self.system2.record_interaction(user_input, final_text)
                    return final_text

        # ── FAST PATH FALLBACK (If LLM is missing or disabled) ──────────────
        normalized = self._normalize_informational(user_input)
        decision = self.decision_engine.predict(normalized)
        route = determine_route(decision, self.config.confidence)

        if route == RouteAction.REJECT:
            return "I'm not sure what you're asking. Could you rephrase that?"

        if route == RouteAction.FALLBACK:
            search_query = re.sub(
                r"^search\s+(?:for\s+)?", "", normalized, flags=re.IGNORECASE
            ).strip()
            result = await execute_tool("search_web", {"query": search_query})
            return self._build_response(result)

        if route == RouteAction.CLARIFY:
            intent_name = decision.intent.replace("_", " ")
            return f"Did you want me to {intent_name}?"

        tool_name = decision.intent
        arguments = self._extract_arguments(normalized, tool_name)

        if arguments is None:
            return f"I know you want to {tool_name.replace('_', ' ')}, but I need more details."

        enforcement = check_permissions(tool_name, decision)
        if enforcement == EnforcementAction.DENY:
            return f"I'm not permitted to run '{tool_name}'."
        if enforcement == EnforcementAction.REQUIRE_CONFIRM:
            args_display = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
            return f"[Confirm] Shall I {tool_name.replace('_', ' ')}({args_display})?"

        result = await execute_tool(tool_name, arguments)
        return self._build_response(result)

    def _normalize_informational(self, text: str) -> str:
        """
        Map informational/conversational phrases onto equivalent search commands
        so Laya correctly routes them to search_web instead of unknown/conversation.

        e.g. "give me the latest news" → "search for the latest news"
        e.g. "what's the weather today" → "search for the weather today"
        e.g. "tell me about black holes" → "search for black holes"
        """
        t = text.strip()
        patterns = [
            (r"^give me\s+", "search for "),
            (r"^show me\s+", "search for "),
            (r"^tell me about\s+", "search for "),
            (r"^what(?:'s| is) the\s+", "search for the "),
            (r"^what(?:'s| is)\s+", "search for "),
            (r"^how (?:do|does|can|to)\s+", "search for how to "),
            (r"^find me\s+", "search for "),
            (r"^i want to know (?:about\s+)?", "search for "),
        ]
        for pattern, replacement in patterns:
            new_t = re.sub(pattern, replacement, t, flags=re.IGNORECASE)
            if new_t != t:
                log_event(logger, f"Normalized: '{t}' → '{new_t}'")
                return new_t
        return t

    def _detect_compound_command(self, text: str) -> list[str] | None:
        """
        Detect compound commands like:
          "open brave and go to reddit.com"
          "open a new tab in chrome and search for python"
          "launch vscode and open the terminal"

        Returns a list of sub-commands, or None if not compound.
        """
        text_lower = text.lower()

        # Pattern: "open <browser> and go to <url>"
        m = re.search(
            r"open\s+(brave|chrome|firefox|edge|microsoft edge|brave browser)\s+and\s+"
            r"(?:go to|navigate to|open|visit)\s+(.+)",
            text_lower,
        )
        if m:
            browser = m.group(1).strip()
            url = m.group(2).strip(".!? ")
            return [f"open {browser}", f"open {url}"]

        # Pattern: "open a new tab in <browser> and go to <url>"
        m = re.search(
            r"open\s+a\s+new\s+tab\s+in\s+(brave|chrome|firefox|edge)\s+and\s+"
            r"(?:go to|navigate to|open|visit|search for)\s+(.+)",
            text_lower,
        )
        if m:
            browser = m.group(1).strip()
            destination = m.group(2).strip(".!? ")
            # Determine if it's a URL or a search query
            if re.search(r"[\w-]+\.\w+", destination):
                return [f"open {browser}", f"go to {destination}"]
            else:
                return [f"open {browser}", f"search for {destination}"]

        return None


    def _extract_arguments(self, text: str, tool_name: str) -> dict[str, Any] | None:
        """
        Rule-based argument extraction for Stage 1.

        Strips conversational fluff, then pattern-matches based on the tool.
        Returns None only if required parameters genuinely can't be found.
        """
        text_lower = text.lower()
        tool = get_tool(tool_name)

        if not tool:
            return None

        params = tool.definition.parameters
        if not params:
            return {}  # Tool takes no arguments

        # Strip conversational openers
        clean = re.sub(
            r"^(can you|could you|please|i want to|i need to|will you|hey laya|laya)\s+",
            "", text_lower
        ).strip()
        clean = re.sub(r"\s+please$", "", clean).strip(".!? ")

        # ── App management ──────────────────────────────────────────────────
        if tool_name in ("open_app", "close_app"):
            match = re.search(
                r"(?:open|launch|start|run|close|quit|kill|exit)\s+(.+)", clean
            )
            if match:
                return {"app_name": match.group(1).strip(".!? ")}
            # Fallback: treat the whole clean input as the app name
            return {"app_name": clean}

        # ── Web search ──────────────────────────────────────────────────────
        elif tool_name == "search_web":
            match = re.search(
                r"(?:search|find|look up|google|search for|look for)"
                r"(?:\s+(?:the\s+)?web\s+(?:for\s+)?|\s+for\s+|\s+)"
                r"(.+)",
                clean,
            )
            if match:
                return {"query": match.group(1).strip(".!? ")}
            return {"query": clean}

        # ── Open website ────────────────────────────────────────────────────
        elif tool_name == "open_website":
            match = re.search(
                r"(?:open|go to|navigate to|take me to|visit)\s+(.+)", clean
            )
            if match:
                return {"url": match.group(1).strip(".!? ")}
            # Try to grab a domain-like token from anywhere in the text
            domain = re.search(
                r"([\w-]+\.(?:com|org|net|io|dev|co|uk|in|ai|edu)[\w/]*)", text_lower
            )
            if domain:
                return {"url": domain.group(1)}
            return {"url": clean}

        # ── Volume control ──────────────────────────────────────────────────
        elif tool_name == "change_volume":
            if re.search(r"\bup\b|raise|increase|louder", clean):
                return {"action": "up"}
            if re.search(r"\bdown\b|lower|decrease|quieter|softer|reduce", clean):
                level = re.search(r"(\d+)\s*(?:%|percent)?", clean)
                if level:
                    return {"action": level.group(1)}
                return {"action": "down"}
            if re.search(r"\bunmute\b", clean):
                return {"action": "unmute"}
            if re.search(r"\bmute\b", clean):
                return {"action": "mute"}
            level = re.search(r"(?:to\s+)?(\d+)\s*(?:%|percent)?", clean)
            if level:
                return {"action": level.group(1)}
            return None

        # ── Music / Spotify ─────────────────────────────────────────────────
        elif tool_name == "play_music":
            match = re.search(
                r"(?:play|put on|start playing|queue)\s+(.+)", clean
            )
            if match:
                query = match.group(1).strip(".!? ")
                # Strip platform suffixes — Spotify/YouTube are implied
                query = re.sub(
                    r"\s+(?:on|in|via|using|through)\s+(?:spotify|youtube|apple music|amazon music)$",
                    "", query, flags=re.IGNORECASE
                ).strip()
                return {"query": query}
            return {"query": clean}

        elif tool_name in ("pause_music", "skip_track"):
            return {}  # No args needed

        # ── System info ─────────────────────────────────────────────────────
        elif tool_name == "get_system_info":
            return {}

        # Fallback: if no required params, proceed anyway
        if not any(p.required for p in params):
            return {}

        return None


    def _build_response(self, result: ToolResult) -> str:
        """Format the tool result into a natural language response."""
        if result.success:
            return result.message or "Done."
        else:
            err = f" ({result.error})" if result.error else ""
            return f"Something went wrong: {result.message}{err}"

    def _try_fast_path(self, clean_input: str) -> tuple[str, dict] | None:
        """
        System 1 Fast Path: Sub-5ms deterministic pattern matching.

        Design principle: The LLM (Ollama) is a FALLBACK for genuinely ambiguous
        queries only. ~95% of voice commands are predictable and handled here.
        This keeps RAM low (model stays unloaded) and latency at <5ms.
        """
        # Normalise: strip polite openers, trailing punctuation, filler words
        cmd = re.sub(
            r"^(can you |could you |please |kindly |hey laya[,]? |laya[,]? )+",
            "", clean_input
        ).strip()
        cmd = re.sub(r"[\?!\.]+$", "", cmd).strip()
        # Also strip common trailing fillers
        cmd_stripped = re.sub(r"\s+(rn|right now|for me|please)$", "", cmd).strip()

        # ── 1. Media controls ──────────────────────────────────────────────────
        if re.fullmatch(
            r"pause(?: the)?(?: music| song| playback)?"
            r"|stop(?: the)?(?: music| song| playback)?",
            cmd
        ):
            return "pause_music", {}

        if re.fullmatch(
            r"resume(?: the)?(?: music| song| playback)?"
            r"|unpause(?: music)?"
            r"|continue(?: playing| music)?"
            r"|play(?: music| again)?",
            cmd
        ):
            return "resume_music", {}

        if re.fullmatch(
            r"(?:next|skip)(?: (?:the )?(?:song|track|this song|this track))?"
            r"|skip(?: this)?",
            cmd
        ):
            return "skip_track", {}

        if re.fullmatch(
            r"(?:previous|prev|go back)(?: (?:a |the )?(?:song|track))?"
            r"|last track",
            cmd
        ):
            return "previous_track", {}

        if re.fullmatch(
            r"(?:what(?:'?s| is)(?: currently)? playing|what song is (?:this|playing)|what(?:'?s| is) playing)"
            r"|(?:what(?:'?s| is) this song)"
            r"|current(?: track| song)?"
            r"|now playing",
            cmd
        ):
            return "get_current_track", {}

        # "play <something>" — only if clearly a music query (not app launch)
        m = re.match(r"play\s+(?P<query>.{2,})", cmd)
        if m:
            query = m.group("query").strip()
            # Avoid catching "play " as music if it's clearly an app
            from src.tools.app_tools import _resolve_app
            if _resolve_app(query) is None:
                return "play_music", {"query": query}

        # ── 2. Volume controls ─────────────────────────────────────────────────
        if re.fullmatch(
            r"(?:volume up|turn (?:the )?volume up|increase(?: the)? volume|louder|raise(?: the)? volume)",
            cmd
        ):
            return "change_volume", {"action": "up"}

        if re.fullmatch(
            r"(?:volume down|turn (?:the )?volume down|decrease(?: the)? volume|quieter|softer|lower(?: the)? volume)",
            cmd
        ):
            return "change_volume", {"action": "down"}

        if re.fullmatch(r"(?:mute|mute(?: the)? volume|silence(?: the)? (?:volume|audio|speaker)?)", cmd):
            return "change_volume", {"action": "mute"}

        if re.fullmatch(r"(?:unmute|unmute(?: the)? volume|un-mute)", cmd):
            return "change_volume", {"action": "unmute"}

        m = re.fullmatch(
            r"(?:set(?: the)? volume to|change(?: the)? volume to|volume(?: to)?|turn(?: it)? (?:up|down) to)\s*(?P<val>\d{1,3})\s*%?",
            cmd
        )
        if m:
            return "change_volume", {"action": m.group("val")}

        # ── 3. Time & Date ─────────────────────────────────────────────────────
        if re.fullmatch(
            r"(?:what(?:'?s| is)(?: the)? time|current time|what time is it|the time|time now|tell me the time)",
            cmd_stripped
        ):
            return "get_current_time", {}

        m = re.fullmatch(
            r"(?:what(?:'?s| is)(?: the)? time in|time in|current time in)\s+(?P<loc>[a-zA-Z][a-zA-Z ]+)",
            cmd_stripped
        )
        if m:
            return "get_current_time", {"location": m.group("loc").strip()}

        if re.fullmatch(
            r"(?:what(?:'?s| is)(?: (?:the|today(?:'?s)?))? date(?: today)?|today(?:'?s)? date|what day is it|what(?:'?s| is) today)",
            cmd_stripped
        ):
            return "get_current_time", {}

        # ── 4. Weather ─────────────────────────────────────────────────────────
        if re.fullmatch(
            r"(?:what(?:'?s| is)(?: the)? weather(?: (?:today|now|outside|like))?"
            r"|weather(?: today| now| outside| like)?"
            r"|how(?:'?s| is)(?: the)? weather(?: today|now|outside|like)?)",
            cmd_stripped
        ):
            return "get_weather", {"location": ""}

        m = re.fullmatch(
            r"(?:what(?:'?s| is)(?: the)? weather in|weather in|how(?:'?s| is)(?: (?:it|the weather)(?: like)?)? in)\s+(?P<loc>[a-zA-Z][a-zA-Z ]+)",
            cmd_stripped
        )
        if m:
            return "get_weather", {"location": m.group("loc").strip()}

        # ── 5. User Profile / Memory (read) ───────────────────────────────────
        if re.fullmatch(
            r"(?:what do you remember(?: about me)?|list(?: (?:my|known|all))? facts?|my profile|who am i|what do you know about me|show(?: my)? memory)",
            cmd_stripped
        ):
            return "list_known_facts", {}

        # remember / recall shorthand
        m = re.fullmatch(r"(?:recall|what(?:'?s| is) my)\s+(?P<key>[a-zA-Z ]+)", cmd_stripped)
        if m:
            return "recall_fact", {"key": m.group("key").strip()}

        # ── 6. Perception & Clipboard ──────────────────────────────────────────
        if re.fullmatch(
            r"(?:what(?:'?s| is)(?: my)? active window|what (?:window|app) is (?:this|open|active)|active window|show(?: the)? active window|show window|what am i looking at|current window)",
            cmd_stripped
        ):
            return "get_active_window", {}

        if re.fullmatch(
            r"(?:what(?:'?s| is)(?: on)?(?: my)? clipboard|clipboard(?: content|text)?|read(?: my)? clipboard|show(?: my)? clipboard|paste content)",
            cmd_stripped
        ):
            return "get_clipboard_text", {}

        m = re.fullmatch(r"copy\s+(?P<txt>.+?)\s+to(?: my)? clipboard", cmd)
        if m:
            return "copy_to_clipboard", {"text": m.group("txt").strip()}

        if re.fullmatch(
            r"(?:lock(?: the)? (?:pc|computer|workstation|screen|my pc)|screen lock|lock screen)",
            cmd_stripped
        ):
            return "lock_pc", {}

        if re.fullmatch(
            r"(?:take(?: a)? screenshot|screenshot|capture(?: the)? screen|snap(?: the)? screen|grab(?: the)? screen)",
            cmd_stripped
        ):
            return "take_screenshot", {}

        # ── 7. Timers & Reminders ──────────────────────────────────────────────
        if re.fullmatch(
            r"(?:cancel(?: my| the)? timer|stop(?: the)? timer|remove(?: the)? timer)",
            cmd_stripped
        ):
            return "cancel_timer", {"label_or_id": ""}

        if re.fullmatch(r"(?:cancel all(?: timers| reminders)?|stop all timers|clear(?: all)? timers)", cmd_stripped):
            return "cancel_timer", {"label_or_id": "all"}

        if re.fullmatch(
            r"(?:how (?:much )?time(?: is)? left(?: on(?: (?:the|my))? timer)?|time left(?: on(?: (?:the|my))? timer)?|how long(?: is)? left)",
            cmd_stripped
        ):
            return "check_timer_remaining", {}

        if re.fullmatch(
            r"(?:(?:list|show)(?: (?:my|all|active))? timers?|my timers?|active timers?|what timers(?: do i have)?)",
            cmd_stripped
        ):
            return "list_active_timers", {}

        # "set a timer for N minutes/seconds [called X]"
        m = re.fullmatch(
            r"(?:set(?: a)? timer(?: for)?|timer(?: for)?)\s+(?P<num>\d+)\s+(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?)"
            r"(?:\s+(?:called|labeled|named|for)\s+(?P<label>.+))?",
            cmd_stripped
        )
        if m:
            num = int(m.group("num"))
            unit = m.group("unit").lower()
            if "hour" in unit or "hr" in unit:
                duration = num * 3600
            elif "min" in unit:
                duration = num * 60
            else:
                duration = num
            label = (m.group("label") or "").strip()
            return "set_timer", {"duration_seconds": duration, "label": label}

        # "remind me in N minutes to X" or "set a reminder to X in N minutes"
        m = re.fullmatch(
            r"(?:remind me|set(?: a)? reminder)(?:\s+(?:in\s+)?(?P<num>\d+)\s+(?P<unit>minutes?|mins?|seconds?|secs?|hours?|hrs?))?(?:\s+(?:to|for)\s+(?P<msg>.+?))?(?:\s+in\s+(?P<num2>\d+)\s+(?P<unit2>minutes?|mins?|seconds?|secs?|hours?|hrs?))?",
            cmd_stripped
        )
        if m and (m.group("num") or m.group("num2") or m.group("msg")):
            num = int(m.group("num") or m.group("num2") or 5)
            unit = (m.group("unit") or m.group("unit2") or "minutes").lower()
            if "hour" in unit or "hr" in unit:
                duration = num * 3600
            elif "min" in unit:
                duration = num * 60
            else:
                duration = num
            msg = (m.group("msg") or "reminder").strip()
            return "set_reminder", {"task": msg, "delay_seconds": duration}

        # ── 8. App launching / closing ─────────────────────────────────────────
        m = re.fullmatch(
            r"(?:open|launch|start|run|pull up)\s+(?P<app>[a-zA-Z0-9][a-zA-Z0-9_\-\.\s]+)",
            cmd
        )
        if m:
            app_target = m.group("app").strip()
            from src.tools.app_tools import _resolve_app
            if _resolve_app(app_target) is not None:
                return "open_app", {"app_name": app_target}

        m = re.fullmatch(
            r"(?:close|quit|kill|exit|shut down|terminate)\s+(?P<app>[a-zA-Z0-9][a-zA-Z0-9_\-\.\s]+)",
            cmd
        )
        if m:
            return "close_app", {"app_name": m.group("app").strip()}

        # ── 9. System info ─────────────────────────────────────────────────────
        if re.fullmatch(
            r"(?:(?:get|show)(?: me)?(?: (?:my|the))? system(?: info(?:rmation)?| specs?| status)?|system (?:info|specs?|status)|specs|how(?:'?s| is) my (?:pc|computer|system)(?: running)?)",
            cmd
        ):
            return "get_system_info", {}

        # ── 10. Web — open website ─────────────────────────────────────────────
        m = re.fullmatch(
            r"(?:go to|open|navigate to|take me to|visit)\s+(?P<url>[\w\-]+\.(?:com|org|net|io|dev|co|uk|in|ai|edu)[\w/\.\-]*)",
            cmd
        )
        if m:
            return "open_website", {"url": m.group("url").strip()}

        # ── 11. Search web ─────────────────────────────────────────────────────
        m = re.fullmatch(
            r"(?:search(?: (?:the )?web)?(?: for)?|google|look up|find(?: me)?)\s+(?P<query>.{3,})",
            cmd
        )
        if m:
            return "search_web", {"query": m.group("query").strip()}

        return None


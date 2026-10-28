"""
Laya decision engine integration.

Defines the questions asked to the Laya model and provides the interface
for routing natural language requests to structured decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.tools.registry import get_tool_criteria
from src.utils.config import AppConfig
from src.utils.logger import get_logger, log_event


logger = get_logger("core.decision")


@dataclass
class LayaDecision:
    """Structured output from a Laya prediction pass."""

    intent: str
    intent_confidence: float
    intent_probabilities: dict[str, float]

    needs_confirmation: float  # P(true)
    needs_system2: float       # P(true) — only for truly complex tasks

    latency_ms: float
    model_used: str
    raw_result: dict[str, Any]


def get_laya_questions() -> dict[str, Any]:
    """
    Build the standard question set for Laya.

    Dynamically pulls the intent criteria from the tool registry so that
    adding a new tool automatically teaches Laya about it.
    """
    tool_criteria = get_tool_criteria()

    # Add generic fallback intents — only true open-ended tasks go here
    criteria = tool_criteria.copy()
    criteria["conversation"] = (
        "The user is asking a factual question, having a chat, or asking for an explanation "
        "that does NOT require launching an app, searching the web, or controlling the computer"
    )
    criteria["unknown"] = (
        "The request is completely ambiguous or requests a capability not listed above"
    )

    return {
        "intent": {
            "type": "choice",
            "instructions": (
                "Identify the single best-matching capability for this user request. "
                "Prefer specific tool intents (open_app, play_music, change_volume, etc.) "
                "over the generic 'conversation' or 'unknown' options whenever any computer "
                "action is involved, even if phrased conversationally."
            ),
            "criteria": criteria,
        },
        "needs_confirmation": {
            "type": "noul",
            "instructions": (
                "Does this request send a message, delete data, make a purchase, "
                "or perform an irreversible action? Playing music, opening apps, "
                "changing volume, and web searches do NOT need confirmation."
            ),
        },
        "needs_system2": {
            "type": "noul",
            "instructions": (
                "Does this request require composing a long written document, deep reasoning, "
                "multi-step planning across many different tools, or generating creative content? "
                "Simple actions like opening apps, playing music, searching the web, "
                "changing volume, or getting system info do NOT need System 2."
            ),
        },
    }



class DecisionEngine:
    """
    Wrapper around the Laya Router for the assistant's System 1.
    """
    
    def __init__(self, config: AppConfig):
        self.config = config
        logger.info(f"Initializing dummy DecisionEngine fallback")

    def predict(self, user_input: str) -> LayaDecision:
        """Fallback empty decision when System 2 is disabled."""
        return LayaDecision(
            intent="unknown",
            intent_confidence=0.0,
            intent_probabilities={},
            needs_confirmation=0.0,
            needs_system2=0.0,
            latency_ms=0.0,
            model_used="fallback",
            raw_result={},
        )




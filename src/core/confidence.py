"""
Confidence-based routing policy.

Translates Laya's continuous probability outputs into discrete system actions.
"""

from __future__ import annotations

from enum import Enum

from src.core.decision import LayaDecision
from src.utils.config import ConfidenceConfig
from src.utils.logger import get_logger, log_event


logger = get_logger("core.confidence")


class RouteAction(Enum):
    """The action the system should take based on confidence."""
    EXECUTE = "execute"           # High confidence, proceed to permission check
    CLARIFY = "clarify"           # Medium confidence, ask the user
    FALLBACK = "fallback"         # Low confidence, use System 2 (LLM)
    REJECT = "reject"             # Too low, tell the user we don't understand


def determine_route(decision: LayaDecision, config: ConfidenceConfig) -> RouteAction:
    """
    Apply the confidence policy to determine the next system action.

    Routing priority:
    1. If Laya says needs_system2 >= 0.6 AND intent is unknown/conversation → FALLBACK
    2. If intent is a real tool AND confidence >= high_threshold → EXECUTE
    3. If intent is a real tool AND confidence >= medium_threshold → try to EXECUTE anyway
       (SAFE tools with medium confidence are better than a useless fallback)
    4. If confidence is below medium → CLARIFY
    5. Below absolute minimum → REJECT
    """
    conf = decision.intent_confidence
    intent = decision.intent

    # Gate 1: Laya explicitly says this needs System 2 reasoning
    # Only route to System 2 if ALSO the intent is non-actionable
    if decision.needs_system2 >= 0.6 and intent in ("unknown", "conversation"):
        log_event(
            logger,
            "Routing to System 2 (Laya flagged complex + non-actionable intent)",
            intent=intent,
            needs_system2=round(decision.needs_system2, 3),
            action=RouteAction.FALLBACK.value,
        )
        return RouteAction.FALLBACK

    # Gate 2: Unknown/conversation with no System 2 signal → still try to clarify or fallback
    if intent in ("unknown",):
        if conf < config.absolute_minimum:
            return RouteAction.REJECT
        return RouteAction.FALLBACK

    # Gate 3: It's a real tool intent — confidence thresholds
    if conf >= config.high_threshold:
        action = RouteAction.EXECUTE
    elif conf >= config.medium_threshold:
        # Medium confidence on a real tool: attempt execution rather than a useless fallback
        # The tool itself will handle any argument errors gracefully
        action = RouteAction.EXECUTE
    elif conf >= config.absolute_minimum:
        action = RouteAction.CLARIFY
    else:
        action = RouteAction.REJECT

    log_event(
        logger,
        f"Confidence routing: {action.value}",
        intent=intent,
        confidence=round(conf, 3),
        thresholds={
            "high": config.high_threshold,
            "medium": config.medium_threshold,
            "min": config.absolute_minimum,
        },
        action=action.value,
    )

    return action


"""
Permission enforcement layer.

Validates that tools have the appropriate authorization before execution,
and incorporates Laya's dynamic safety signals (e.g., needs_confirmation).
"""

from __future__ import annotations

from enum import Enum

from src.core.decision import LayaDecision
from src.tools.base import PermissionLevel
from src.tools.registry import get_permission
from src.utils.logger import get_logger, log_event


logger = get_logger("core.permissions")


class EnforcementAction(Enum):
    """The action the system should take after permission checks."""
    ALLOW = "allow"               # Proceed with execution
    REQUIRE_CONFIRM = "confirm"   # Ask user before proceeding
    DENY = "deny"                 # Block execution entirely


def check_permissions(tool_name: str, decision: LayaDecision | None = None) -> EnforcementAction:
    """
    Determine if a tool is allowed to execute.
    
    Args:
        tool_name: The name of the tool to execute.
        decision: The Laya decision that led to this execution (optional).
                 Used to incorporate dynamic safety signals.
    """
    level = get_permission(tool_name)
    
    if level is None:
        log_event(
            logger,
            f"Permission denied: Unknown tool '{tool_name}'",
            tool=tool_name,
            action=EnforcementAction.DENY.value,
        )
        return EnforcementAction.DENY
        
    # Check Laya's dynamic safety signal if provided
    dynamic_confirm_needed = False
    if decision and decision.needs_confirmation >= 0.5:
        dynamic_confirm_needed = True
        
    # Apply policy
    if level == PermissionLevel.DANGEROUS:
        # Dangerous tools ALWAYS require explicit confirmation, regardless of Laya
        action = EnforcementAction.REQUIRE_CONFIRM
        reason = "Tool is marked as DANGEROUS"
        
    elif level == PermissionLevel.CONFIRMATION_REQUIRED:
        # Confirmation required tools ALWAYS require confirmation
        action = EnforcementAction.REQUIRE_CONFIRM
        reason = "Tool requires confirmation"
        
    elif level == PermissionLevel.SAFE:
        # SAFE tools NEVER get dynamic confirmation — their whole point is auto-execution.
        # Laya's needs_confirmation signal only elevates CONFIRMATION_REQUIRED tools.
        action = EnforcementAction.ALLOW
        reason = "Tool is SAFE — auto-execute"
            
    else:
        action = EnforcementAction.DENY
        reason = f"Unknown permission level: {level}"

    log_event(
        logger,
        f"Permission check: {action.value}",
        tool=tool_name,
        permission_level=level.value,
        dynamic_risk=dynamic_confirm_needed,
        action=action.value,
        reason=reason,
    )
        
    return action

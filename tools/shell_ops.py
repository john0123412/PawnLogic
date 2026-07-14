"""Host-shell policy orchestration shared by file-oriented tool adapters."""

from __future__ import annotations

from collections.abc import Callable

from core.operation_policy import (
    OperationAction,
    OperationDecision,
    audit_operation_decision,
    classify_shell_command,
)


def authorize_shell_operation(
    command: str,
    cwd: str,
    *,
    workspace_dir: str,
    operation_type: str,
    interactive: bool,
    confirmer: Callable[[OperationDecision], bool],
    classifier: Callable[..., OperationDecision] = classify_shell_command,
    auditor: Callable[..., None] = audit_operation_decision,
) -> tuple[bool, OperationDecision]:
    """Classify, authorize, and audit one shell request without executing it."""
    decision = classifier(
        command,
        cwd=cwd,
        workspace_dir=workspace_dir,
    )
    if decision.action == OperationAction.ALLOW:
        auditor(
            decision, operation_type=operation_type, cwd=cwd, interactive=interactive
        )
        return True, decision
    if decision.action == OperationAction.DENY:
        auditor(
            decision, operation_type=operation_type, cwd=cwd, interactive=interactive
        )
        return False, decision
    if not interactive:
        denied = decision.with_action(
            OperationAction.DENY,
            reason=decision.reason + " Confirmation unavailable in non-interactive or --eval mode.",
            matched_rule=f"confirmation_unavailable:{decision.matched_rule}",
        )
        auditor(
            denied, operation_type=operation_type, cwd=cwd, interactive=False
        )
        return False, denied
    try:
        confirmed = confirmer(decision)
    except Exception:
        confirmed = False
    if not confirmed:
        denied = decision.with_action(
            OperationAction.DENY,
            reason=decision.reason + " User did not confirm the operation.",
            matched_rule=f"user_denied:{decision.matched_rule}",
        )
        auditor(
            denied, operation_type=operation_type, cwd=cwd, interactive=True
        )
        return False, denied
    auditor(
        decision, operation_type=operation_type, cwd=cwd, interactive=True
    )
    return True, decision


__all__ = ["authorize_shell_operation"]

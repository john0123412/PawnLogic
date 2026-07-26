"""Agent Event adapter for the main synchronous session runtime."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from core.agent_events import AgentEvent, AgentEventKind
from utils.ansi import c, GRAY


class SessionEventEmitter:
    """Correlate runtime lifecycle observations into versioned Agent Events."""

    def __init__(self, runtime_context: Any, session_id: str) -> None:
        self._runtime_context = runtime_context
        self._session_id = session_id
        self._turn_id = "turn-inactive"
        self._sequence = 0
        self._finished = True
        self._open_tools: dict[str, tuple[str, int]] = {}

    @property
    def turn_id(self) -> str:
        return self._turn_id

    def bind(self, runtime_context: Any) -> None:
        self._runtime_context = runtime_context
        runtime_context.session_id = self._session_id
        runtime_context.agent_id = self._session_id

    def start_turn(self, model_alias: str, phase: str) -> None:
        self._turn_id = f"turn-{uuid.uuid4().hex}"
        self._sequence = 0
        self._finished = False
        self._open_tools.clear()
        self._runtime_context.session_id = self._session_id
        self._runtime_context.agent_id = self._session_id
        self._runtime_context.active_turn_id = self._turn_id
        self._publish(
            AgentEventKind.TURN_STARTED,
            {"model_alias": model_alias, "phase": phase},
            source="session",
        )

    def retrieval_adapter(self, retriever: Callable[..., Any]) -> Callable[..., Any]:
        def retrieve(*args: Any, **kwargs: Any) -> Any:
            hits = retriever(*args, **kwargs)
            self.retrieval(hits)
            return hits

        return retrieve

    def retrieval(self, hits: Sequence[Any]) -> None:
        evidence = []
        for hit in hits:
            evidence.append(
                {
                    "record_id": str(getattr(hit, "record_id", "")),
                    "namespace": str(getattr(hit, "namespace", "")),
                    "source_type": str(getattr(hit, "source_type", "")),
                    "source_id": str(getattr(hit, "source_id", "")),
                    "source_revision": str(getattr(hit, "source_revision", "")),
                    "score": float(getattr(hit, "score", 0.0)),
                    "score_kind": str(getattr(hit, "score_kind", "")),
                    "provenance": dict(getattr(hit, "provenance", {})),
                }
            )
        if evidence:
            self._publish(
                AgentEventKind.RETRIEVAL_EVIDENCE,
                {"hits": evidence},
                source="knowledge",
            )

    def usage(self, usage: Mapping[str, int]) -> None:
        self._publish(
            AgentEventKind.USAGE,
            {
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
            },
            source="provider",
        )

    def tool_started(self, tool_call: Mapping[str, Any], iteration: int) -> None:
        self._open_tools[str(tool_call["id"])] = (
            str(tool_call["name"]),
            iteration,
        )
        self._publish(
            AgentEventKind.TOOL_STARTED,
            {
                "tool_call_id": str(tool_call["id"]),
                "tool_name": str(tool_call["name"]),
                "iteration": iteration,
            },
            source="tool-loop",
        )

    def tool_result(
        self,
        tool_call: Mapping[str, Any],
        outcome: Any,
        iteration: int,
    ) -> None:
        self._open_tools.pop(str(tool_call["id"]), None)
        self._publish(
            AgentEventKind.TOOL_RESULT,
            {
                "tool_call_id": str(tool_call["id"]),
                "tool_name": str(tool_call["name"]),
                "iteration": iteration,
                "status": str(getattr(outcome, "status", "unknown")),
                "error_type": getattr(outcome, "error_type", None),
                "side_effect": bool(getattr(outcome, "side_effect", False)),
            },
            source="tool-loop",
        )

    def plan_guard(self, decision: str) -> None:
        self.policy(
            policy="plan_guard",
            decision=decision,
            reason="missing_required_plan" if decision != "ok" else "",
        )

    def policy(
        self,
        *,
        policy: str,
        decision: str,
        reason: str = "",
    ) -> None:
        self._publish(
            AgentEventKind.POLICY_DECISION,
            {"policy": policy, "decision": decision, "reason": reason},
            source="session",
        )

    def finish(self, status: str, metrics: Any) -> None:
        if self._finished:
            return
        event_type = {
            "completed": AgentEventKind.TURN_COMPLETED,
            "interrupted": AgentEventKind.TURN_CANCELLED,
            "failed": AgentEventKind.TURN_FAILED,
        }.get(status)
        if event_type is None:
            return
        for tool_call_id, (tool_name, iteration) in tuple(
            self._open_tools.items()
        ):
            self._publish(
                AgentEventKind.TOOL_RESULT,
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "iteration": iteration,
                    "status": "interrupted",
                    "error_type": "TurnInterrupted",
                    "side_effect": False,
                },
                source="tool-loop",
            )
        self._open_tools.clear()
        self._finished = True
        self._publish(
            event_type,
            {
                "status": status,
                "prompt_tokens": int(getattr(metrics, "turn_prompt_tokens", 0)),
                "completion_tokens": int(
                    getattr(metrics, "turn_completion_tokens", 0)
                ),
                "tool_calls": int(getattr(metrics, "turn_tool_calls", 0)),
            },
            source="session",
        )

    def _publish(
        self,
        event_type: AgentEventKind,
        payload: Mapping[str, object],
        *,
        source: str,
    ) -> None:
        self._sequence += 1
        event = AgentEvent(
            event_type=event_type,
            session_id=self._session_id,
            turn_id=self._turn_id,
            agent_id=self._session_id,
            payload=payload,
            metadata={"sequence": self._sequence, "source": source},
        )
        try:
            self._runtime_context.publish_event(event)
        except Exception:
            return


def render_turn_usage(
    snapshot: Any,
    *,
    user_mode: bool,
    output: Callable[[str], None],
) -> None:
    """Preserve the existing human usage summary outside session orchestration."""
    pt = snapshot.turn_prompt_tokens
    ct = snapshot.turn_completion_tokens
    tt = snapshot.turn_tool_calls
    if pt + ct + tt == 0:
        return
    tot_pt = snapshot.total_prompt_tokens
    tot_ct = snapshot.total_completion_tokens
    tot_tt = snapshot.total_tool_calls
    if user_mode:
        cumulative = (
            f"  cum:↑{tot_pt:,}↓{tot_ct:,}🔧{tot_tt}"
            if tot_pt != pt or tot_tt != tt
            else ""
        )
        output(c(GRAY, f"  [↑{pt:,}tok ↓{ct:,}tok 🔧{tt}]{cumulative}"))
        return
    total_turn = pt + ct
    cumulative_total = tot_pt + tot_ct
    lines = [
        "",
        "  ┌─ Turn Usage ──────────────────────────────",
        f"  │  Prompt tokens    : {pt:>8,}"
        + (f"   (session: {tot_pt:,})" if tot_pt != pt else ""),
        f"  │  Completion tokens: {ct:>8,}"
        + (f"   (session: {tot_ct:,})" if tot_ct != ct else ""),
        f"  │  Total this turn  : {total_turn:>8,}"
        + (
            f"   (session: {cumulative_total:,})"
            if cumulative_total != total_turn
            else ""
        ),
        f"  │  Tool calls       : {tt:>8,}"
        + (f"   (session: {tot_tt:,})" if tot_tt != tt else ""),
        "  └───────────────────────────────────────────",
    ]
    output(c(GRAY, "\n".join(lines)))


__all__ = ["SessionEventEmitter", "render_turn_usage"]

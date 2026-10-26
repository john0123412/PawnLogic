"""Whether a model is asked to write a ``<plan>`` before its tool calls.

The system prompt's Execution Protocol section asks every model for a full
``<plan>`` (with a ``<tool>`` field) before any tool call, and the plan guard
flags a tool batch that came without one.  That suits models that write the
plan *and* call the tool.  A model that treats writing the plan as the action
it was asked for answers a request with a plan and no tool call; in a paid A/B
on such a provider the same first request was plan-only 2 of 2 times as built
and 0 of 2 times with only that section removed, and one reply was a native
tool call.

A custom provider can therefore switch the protocol off
(``/provider plan <name> off``, persisted as ``"plan_protocol": false`` in
``custom_providers.json``).  Absent or ``true`` is today's behaviour and
built-in providers are never switched.

``plan_protocol_enabled`` is the only place that turns a model alias into that
answer, the way ``core.api_payloads.model_effort_map`` is the only effort
resolver.  What it controls, all keyed to the same answer:

* ``build_session_prompt`` omits the Execution Protocol section, and the other
  injected texts that require a ``<plan>`` (the GSA conflict warning, the
  anti-loop notices);
* the plan guard does not flag, annotate or count a plan-missing tool batch, in
  any ``plan_guard_mode``.  The protocol is not in the prompt, so enforcing it
  would punish the model for ignoring an instruction it never received.  This is
  a precedence rule: with the protocol off, ``/planguard strict`` has nothing to
  enforce;
* plan-only recovery (``core/plan_recovery.py``) stays on, because a model may
  still emit a plan of its own accord and a bare plan is still not an answer.

The system prompt is a cache prefix: it is rebuilt only when its inputs change.
The setting is one of them (``plan_prompt_is_stale``), so a model switch or a
toggle on the current provider rebuilds it once, and nothing else does.  The
guard and the other consumers read the setting the *prompt* was built with
(``prompt_plan_protocol``), not the live one: an urgent-mode model switch in the
middle of a turn must not start enforcing a protocol the prompt does not carry.
"""

from __future__ import annotations

from config import MODELS
from config import providers as provider_config


def plan_protocol_enabled(model_alias: str) -> bool:
    """Return whether ``model_alias`` is asked to write a ``<plan>`` before tool calls.

    Resolves model -> its provider -> the provider's ``plan_protocol`` setting.
    An unknown alias, a built-in provider and a provider without the setting all
    answer ``True``.
    """
    provider = str((MODELS.get(model_alias) or {}).get("provider") or "")
    return provider_config.provider_plan_protocol(provider)


def prompt_plan_protocol(session: object) -> bool:
    """Return the setting ``session``'s current system prompt was built with.

    Until a prompt has been built (a test double, a session that skipped
    ``_reset_system_prompt``) there is nothing to be consistent with, so the
    live answer for the active model is used.
    """
    recorded = getattr(session, "_prompt_plan_protocol", None)
    if recorded is None:
        return plan_protocol_enabled(str(getattr(session, "model_alias", "")))
    return bool(recorded)


def plan_prompt_is_stale(session: object) -> bool:
    """Return whether the active model resolves to a different setting than the prompt carries."""
    live = plan_protocol_enabled(str(getattr(session, "model_alias", "")))
    return live != prompt_plan_protocol(session)


__all__ = [
    "plan_prompt_is_stale",
    "plan_protocol_enabled",
    "prompt_plan_protocol",
]

"""Side-effect-free model routing for delegated agent tasks."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from config import MODELS
from config import is_fast_model as default_is_fast_model
from config import is_provider_active as default_is_provider_active
from config import validate_api_key as default_validate_api_key

if TYPE_CHECKING:
    from core.delegation import AgentTask, DelegationModelPolicy


_LEGACY_WORKER_CANDIDATES = (
    "ds-v4-flash",
    "claude-haiku",
    "gpt-4.1",
)
_SUPPORTED_REQUIREMENTS = {
    "auto",
    "fast",
    "reasoning",
    "vision",
    "same",
    "same_provider",
}


@dataclass(frozen=True)
class RoutingDecision:
    """A deterministic delegated-model selection result."""

    model_alias: str | None
    reason: str
    error: str | None = None
    eligible_models: tuple[str, ...] = ()


class ModelRouter:
    """Select an authorized model without making provider requests."""

    def __init__(
        self,
        models: (
            Mapping[str, Mapping[str, Any]]
            | Callable[[], Mapping[str, Mapping[str, Any]]]
            | None
        ) = None,
        *,
        is_provider_active: Callable[[str], bool] | None = None,
        validate_api_key: Callable[[str], bool | tuple[bool, str]] | None = None,
        is_fast_model: Callable[[str], bool] | None = None,
        worker_candidates: Sequence[str] = _LEGACY_WORKER_CANDIDATES,
    ) -> None:
        self._models_source = models
        self._is_provider_active = (
            is_provider_active or default_is_provider_active
        )
        self._validate_api_key = validate_api_key or default_validate_api_key
        self._is_fast_model = is_fast_model or default_is_fast_model
        self._worker_candidates = tuple(worker_candidates)

    def select(
        self,
        task: AgentTask,
        parent_model_alias: str,
        policy: DelegationModelPolicy,
    ) -> RoutingDecision:
        """Select a model from the live registry and current host policy."""
        models = self._models()
        explicit_alias = self._clean_string(getattr(task, "model_alias", None))
        requirement = self._requirement(task, policy, explicit=bool(explicit_alias))

        if requirement not in _SUPPORTED_REQUIREMENTS:
            return RoutingDecision(
                None,
                "unsupported_requirement",
                f"Unsupported model requirement '{requirement}'.",
            )

        effective_max_tokens = self.effective_max_tokens(task, policy)
        if effective_max_tokens is not None and effective_max_tokens <= 0:
            return RoutingDecision(
                None,
                "budget_exhausted",
                "Delegated model routing requires a positive max_tokens budget.",
            )
        effective_max_cost = self.effective_max_cost(task, policy)

        eligible = self._eligible_aliases(
            models,
            policy,
            requirement=requirement,
            parent_model_alias=parent_model_alias,
            max_tokens=effective_max_tokens,
            max_cost=effective_max_cost,
        )
        eligible_tuple = tuple(eligible)

        if explicit_alias:
            if explicit_alias in eligible:
                return RoutingDecision(
                    explicit_alias,
                    "explicit_model",
                    eligible_models=eligible_tuple,
                )
            return RoutingDecision(
                None,
                "explicit_model_rejected",
                self._explicit_rejection(
                    explicit_alias,
                    models,
                    policy,
                    requirement=requirement,
                    parent_model_alias=parent_model_alias,
                    max_tokens=effective_max_tokens,
                    max_cost=effective_max_cost,
                ),
                eligible_tuple,
            )

        if not eligible:
            cost_detail = ""
            if effective_max_cost is not None:
                cost_detail = (
                    f" The max_cost budget is {effective_max_cost:g}; models "
                    "without explicit cost metadata cannot be estimated and "
                    "are ineligible."
                )
            return RoutingDecision(
                None,
                "no_eligible_models",
                "No models are active, configured, permitted by policy, "
                f"compatible with requirement '{requirement}', and within "
                f"budget.{cost_detail}",
                eligible_tuple,
            )

        selected, reason = self._select_implicit(
            eligible,
            models,
            policy,
            parent_model_alias=parent_model_alias,
            requirement=requirement,
        )
        return RoutingDecision(selected, reason, eligible_models=eligible_tuple)

    def route(
        self,
        task: AgentTask,
        parent_model_alias: str,
        policy: DelegationModelPolicy,
    ) -> RoutingDecision:
        """Compatibility alias for callers that describe selection as routing."""
        return self.select(task, parent_model_alias, policy)

    def visible_models(self, policy: DelegationModelPolicy) -> tuple[str, ...]:
        """Return the live active, configured, policy-authorized aliases."""
        return tuple(self._visible_aliases(self._models(), policy))

    def eligible_models(
        self,
        task: AgentTask,
        parent_model_alias: str,
        policy: DelegationModelPolicy,
    ) -> tuple[str, ...]:
        """Return the live visible aliases matching the effective requirement."""
        requirement = self._requirement(
            task,
            policy,
            explicit=bool(self._clean_string(getattr(task, "model_alias", None))),
        )
        if requirement not in _SUPPORTED_REQUIREMENTS:
            return ()
        effective_max_tokens = self.effective_max_tokens(task, policy)
        if effective_max_tokens is not None and effective_max_tokens <= 0:
            return ()
        effective_max_cost = self.effective_max_cost(task, policy)
        return tuple(
            self._eligible_aliases(
                self._models(),
                policy,
                requirement=requirement,
                parent_model_alias=parent_model_alias,
                max_tokens=effective_max_tokens,
                max_cost=effective_max_cost,
            )
        )

    @staticmethod
    def effective_max_tokens(
        task: AgentTask,
        policy: DelegationModelPolicy,
    ) -> int | None:
        """Return the stricter policy/task token limit, if either is bounded."""
        limits: list[int] = []
        policy_limit = ModelRouter._token_limit(policy)
        if policy_limit is not None:
            limits.append(policy_limit)

        budget = getattr(task, "budget", None)
        task_limit = ModelRouter._token_limit(budget)
        if task_limit is None:
            task_limit = ModelRouter._optional_int(getattr(task, "max_tokens", None))
        if task_limit is not None:
            limits.append(task_limit)
        return min(limits) if limits else None

    @staticmethod
    def effective_max_cost(
        task: AgentTask,
        policy: DelegationModelPolicy,
    ) -> float | None:
        """Return the stricter policy/task cost limit, if either is bounded."""
        limits: list[float] = []
        policy_limit = ModelRouter._cost_limit(policy)
        if policy_limit is not None:
            limits.append(policy_limit)
        task_limit = ModelRouter._cost_limit(getattr(task, "budget", None))
        if task_limit is None:
            task_limit = ModelRouter._optional_float(
                getattr(task, "max_cost", None)
            )
        if task_limit is not None:
            limits.append(task_limit)
        return min(limits) if limits else None

    def _models(self) -> Mapping[str, Mapping[str, Any]]:
        source = self._models_source
        if source is None:
            return MODELS
        return source() if callable(source) else source

    def _visible_aliases(
        self,
        models: Mapping[str, Mapping[str, Any]],
        policy: Any,
    ) -> list[str]:
        allowed = self._policy_aliases(
            policy,
            "allowed_model_aliases",
            "allowed_models",
            "allowlist",
        )
        denied = self._policy_aliases(
            policy,
            "denied_model_aliases",
            "denied_models",
            "denylist",
        )
        visible: list[str] = []
        for alias, config in models.items():
            provider = str(config.get("provider", ""))
            if not provider or not self._is_provider_active(provider):
                continue
            if not self._key_is_configured(alias):
                continue
            if allowed and alias not in allowed:
                continue
            if alias in denied:
                continue
            visible.append(alias)
        return visible

    def _eligible_aliases(
        self,
        models: Mapping[str, Mapping[str, Any]],
        policy: Any,
        *,
        requirement: str,
        parent_model_alias: str,
        max_tokens: int | None,
        max_cost: float | None,
    ) -> list[str]:
        return [
            alias
            for alias in self._visible_aliases(models, policy)
            if self._matches_requirement(
                alias,
                models[alias],
                requirement=requirement,
                parent_model_alias=parent_model_alias,
                models=models,
            )
            and self._within_cost_budget(
                models[alias],
                max_tokens=max_tokens,
                max_cost=max_cost,
            )
        ]

    def _select_implicit(
        self,
        eligible: list[str],
        models: Mapping[str, Mapping[str, Any]],
        policy: Any,
        *,
        parent_model_alias: str,
        requirement: str,
    ) -> tuple[str, str]:
        preferred = self._clean_string(getattr(policy, "preferred_model", None))
        if preferred in eligible:
            return preferred, "preferred_model"

        if requirement == "same":
            return parent_model_alias, "current_model"

        if requirement in {"auto", "fast", "same_provider"}:
            if (
                parent_model_alias in eligible
                and self._is_fast_model(parent_model_alias)
            ):
                return parent_model_alias, "current_fast_model"

            parent_provider = self._provider_of(parent_model_alias, models)
            for alias in eligible:
                if (
                    alias != parent_model_alias
                    and self._provider_of(alias, models) == parent_provider
                    and self._is_fast_model(alias)
                ):
                    return alias, "same_provider_fast_peer"

        for alias in self._worker_candidates:
            if alias in eligible and alias != parent_model_alias:
                return alias, "legacy_candidate"

        for alias in eligible:
            if alias != parent_model_alias:
                return alias, (
                    "reasoning_model"
                    if requirement == "reasoning"
                    else "first_eligible"
                )

        return parent_model_alias, "current_model"

    def _explicit_rejection(
        self,
        alias: str,
        models: Mapping[str, Mapping[str, Any]],
        policy: Any,
        *,
        requirement: str,
        parent_model_alias: str,
        max_tokens: int | None,
        max_cost: float | None,
    ) -> str:
        if alias not in models:
            return f"Requested model '{alias}' is not registered."

        config = models[alias]
        provider = str(config.get("provider", ""))
        if not provider or not self._is_provider_active(provider):
            return (
                f"Requested model '{alias}' is unavailable because provider "
                f"'{provider or '<unknown>'}' is inactive."
            )

        configured, missing = self._key_status(alias)
        if not configured:
            detail = f" Missing credential: {missing}." if missing else ""
            return f"Requested model '{alias}' is not configured.{detail}"

        allowed = self._policy_aliases(
            policy,
            "allowed_model_aliases",
            "allowed_models",
            "allowlist",
        )
        denied = self._policy_aliases(
            policy,
            "denied_model_aliases",
            "denied_models",
            "denylist",
        )
        if alias in denied:
            return f"Requested model '{alias}' is denied by model policy."
        if allowed and alias not in allowed:
            return f"Requested model '{alias}' is not in the model allowlist."
        if not self._matches_requirement(
            alias,
            config,
            requirement=requirement,
            parent_model_alias=parent_model_alias,
            models=models,
        ):
            return (
                f"Requested model '{alias}' does not satisfy model requirement "
                f"'{requirement}'."
            )
        if max_cost is not None:
            estimated_cost = self._estimated_cost(
                config,
                max_tokens=max_tokens,
            )
            if estimated_cost is None:
                return (
                    f"Requested model '{alias}' cost cannot be estimated from "
                    "explicit model metadata while a max_cost budget is active."
                )
            if estimated_cost > max_cost:
                return (
                    f"Requested model '{alias}' estimated cost "
                    f"{estimated_cost:g} exceeds max_cost {max_cost:g}."
                )
        return f"Requested model '{alias}' is not eligible."

    def _matches_requirement(
        self,
        alias: str,
        config: Mapping[str, Any],
        *,
        requirement: str,
        parent_model_alias: str,
        models: Mapping[str, Mapping[str, Any]],
    ) -> bool:
        if requirement == "auto":
            return True
        if requirement == "fast":
            return self._is_fast_model(alias)
        if requirement == "reasoning":
            return self._is_reasoning_model(alias, config)
        if requirement == "vision":
            capabilities = config.get("capabilities", ())
            if isinstance(capabilities, str):
                capabilities = (capabilities,)
            return bool(config.get("vision") or "vision" in capabilities)
        if requirement == "same":
            return alias == parent_model_alias
        if requirement == "same_provider":
            parent_provider = self._provider_of(parent_model_alias, models)
            return bool(parent_provider) and config.get("provider") == parent_provider
        return False

    @staticmethod
    def _is_reasoning_model(alias: str, config: Mapping[str, Any]) -> bool:
        capabilities = config.get("capabilities", ())
        if isinstance(capabilities, str):
            capabilities = (capabilities,)
        if "reasoning" in capabilities:
            return True
        if config.get("reasoning") or config.get("reasoning_capable"):
            return True
        identity = f"{alias} {config.get('id', '')} {config.get('desc', '')}".lower()
        tokens = identity.replace("-", " ").replace("_", " ").split()
        return (
            "reasoning" in tokens
            or "reasoner" in tokens
            or "r1" in tokens
            or any(token.startswith(("o1", "o3", "o4")) for token in tokens)
        )

    @classmethod
    def _within_cost_budget(
        cls,
        config: Mapping[str, Any],
        *,
        max_tokens: int | None,
        max_cost: float | None,
    ) -> bool:
        if max_cost is None:
            return True
        estimated = cls._estimated_cost(config, max_tokens=max_tokens)
        return estimated is not None and estimated <= max_cost

    @classmethod
    def _estimated_cost(
        cls,
        config: Mapping[str, Any],
        *,
        max_tokens: int | None,
    ) -> float | None:
        """Read an explicit per-task estimate or derive one from a token rate."""
        for field_name in ("estimated_cost", "cost"):
            if field_name in config:
                return cls._optional_float(config.get(field_name))

        if max_tokens is None:
            return None
        for field_name, divisor in (
            ("cost_per_1k_tokens", 1_000),
            ("cost_per_million_tokens", 1_000_000),
        ):
            if field_name not in config:
                continue
            rate = cls._optional_float(config.get(field_name))
            if rate is not None:
                return rate * max_tokens / divisor
        return None

    @staticmethod
    def _provider_of(
        alias: str,
        models: Mapping[str, Mapping[str, Any]],
    ) -> str:
        return str(models.get(alias, {}).get("provider", ""))

    def _key_is_configured(self, alias: str) -> bool:
        return self._key_status(alias)[0]

    def _key_status(self, alias: str) -> tuple[bool, str]:
        result = self._validate_api_key(alias)
        if isinstance(result, tuple):
            return bool(result[0]), str(result[1] or "")
        return bool(result), ""

    @staticmethod
    def _requirement(task: Any, policy: Any, *, explicit: bool) -> str:
        requested = ModelRouter._clean_string(
            getattr(task, "model_requirement", None)
        ).lower()
        requested = requested.replace("-", "_")
        if requested and requested != "auto":
            return requested
        if explicit:
            return "auto"
        default_mode = ModelRouter._clean_string(
            getattr(policy, "default_mode", None)
        ).lower()
        return (default_mode or "auto").replace("-", "_")

    @staticmethod
    def _policy_aliases(policy: Any, *names: str) -> frozenset[str]:
        for name in names:
            value = getattr(policy, name, None)
            if value:
                return frozenset(str(alias) for alias in value)
        return frozenset()

    @staticmethod
    def _token_limit(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, Mapping):
            raw = value.get("max_tokens")
            if raw is None:
                raw = value.get("max_output_tokens")
            return ModelRouter._optional_int(raw)
        raw = getattr(value, "max_tokens", None)
        if raw is None:
            raw = getattr(value, "max_output_tokens", None)
        return ModelRouter._optional_int(raw)

    @staticmethod
    def _cost_limit(value: Any) -> float | None:
        if value is None:
            return None
        raw = value.get("max_cost") if isinstance(value, Mapping) else getattr(
            value,
            "max_cost",
            None,
        )
        return ModelRouter._optional_float(raw)

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if result >= 0 and math.isfinite(result) else None

    @staticmethod
    def _clean_string(value: Any) -> str:
        return str(value).strip() if value is not None else ""

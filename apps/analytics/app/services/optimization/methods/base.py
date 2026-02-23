"""Base abstractions for pluggable optimization methods."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MethodContext:
    """All data a method needs to evaluate — immutable snapshot."""

    campaign_id: str
    kpis: dict[str, float] = field(default_factory=dict)
    trends: list[dict[str, Any]] = field(default_factory=list)
    raw_metrics: dict[str, float] = field(default_factory=dict)
    channel_data: list[dict[str, Any]] = field(default_factory=list)
    current_allocations: dict[str, float] = field(default_factory=dict)
    campaign_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MethodEvaluation:
    """Output when a method fires."""

    should_fire: bool
    confidence: float  # 0.0–1.0
    priority: int  # 1 = highest, 10 = lowest
    action_type: str  # e.g. "budget_reallocation", "pause_channel", "creative_refresh"
    action_payload: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    trigger_data: dict[str, Any] = field(default_factory=dict)


class BaseOptimizationMethod(ABC):
    """Abstract base for all optimisation methods.

    Subclasses must implement ``check_preconditions`` and ``evaluate``.
    """

    name: str = ""
    description: str = ""
    method_type: str = "reactive"  # "reactive" or "proactive"

    # ---- abstract interface ---------------------------------------------------

    @abstractmethod
    def check_preconditions(self, ctx: MethodContext) -> tuple[bool, str]:
        """Return ``(ok, reason)``.  If ``ok`` is False the method is skipped."""
        ...

    @abstractmethod
    def evaluate(self, ctx: MethodContext) -> MethodEvaluation | None:
        """Analyse *ctx* and return a ``MethodEvaluation`` if the method fires,
        or ``None`` if it does not trigger."""
        ...


class MethodRegistry:
    """Container for registered optimization methods.

    Provides ``register``, ``get``, ``list_methods``, and ``evaluate_all``.
    """

    def __init__(self) -> None:
        self._methods: dict[str, BaseOptimizationMethod] = {}

    # ---- mutation -------------------------------------------------------------

    def register(self, method: BaseOptimizationMethod) -> None:
        """Register a method.  Overwrites if a method with the same name exists."""
        self._methods[method.name] = method

    # ---- queries --------------------------------------------------------------

    def get(self, name: str) -> BaseOptimizationMethod | None:
        return self._methods.get(name)

    def list_methods(self) -> list[BaseOptimizationMethod]:
        return list(self._methods.values())

    # ---- bulk evaluation ------------------------------------------------------

    def evaluate_all(self, ctx: MethodContext) -> list[MethodEvaluation]:
        """Run every registered method and return evaluations that fire."""
        results: list[MethodEvaluation] = []
        for method in self._methods.values():
            ok, _reason = method.check_preconditions(ctx)
            if not ok:
                continue
            evaluation = method.evaluate(ctx)
            if evaluation is not None and evaluation.should_fire:
                results.append(evaluation)
        return results

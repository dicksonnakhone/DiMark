"""Optimization methods package — pluggable method registry."""

from app.services.optimization.methods.base import (
    BaseOptimizationMethod,
    MethodContext,
    MethodEvaluation,
    MethodRegistry,
)
from app.services.optimization.methods.budget_reallocation import (
    BudgetReallocationMethod,
)
from app.services.optimization.methods.cpa_spike import CPASpikeMethod
from app.services.optimization.methods.creative_fatigue import (
    CreativeFatigueMethod,
)

__all__ = [
    "BaseOptimizationMethod",
    "BudgetReallocationMethod",
    "CPASpikeMethod",
    "CreativeFatigueMethod",
    "MethodContext",
    "MethodEvaluation",
    "MethodRegistry",
    "build_default_registry",
]


def build_default_registry() -> MethodRegistry:
    """Build a registry pre-loaded with the default optimization methods."""
    registry = MethodRegistry()
    registry.register(CPASpikeMethod())
    registry.register(BudgetReallocationMethod())
    registry.register(CreativeFatigueMethod())
    return registry

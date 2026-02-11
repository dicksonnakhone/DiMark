from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any


class ExecutionAgent(ABC):
    @abstractmethod
    def run_window(
        self,
        *,
        campaign: Any,
        plan_json: dict[str, Any] | None,
        brief_json: dict[str, Any] | None,
        budget_plan: Any,
        allocations: dict[str, Any],
        window_start: date,
        window_end: date,
        seed: int,
        variant_name: str | None = None,
        sim_overrides: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

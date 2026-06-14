"""Daily spend guard. Fail-closed: never exceed the configured daily budget.

The cost ledger in the store is the single source of truth for spend, so the
guard's `remaining()` always reflects costs already charged this day.
"""
from __future__ import annotations

import logging

from research_bot.config import Settings
from research_bot.models import CostRecord
from research_bot.store import Store

logger = logging.getLogger(__name__)


class BudgetGuard:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store

    def remaining(self) -> int:
        return max(0, self.settings.daily_budget_units - self.store.spent_today_units())

    def can_afford(self, units: int) -> bool:
        return self.remaining() >= units

    def charge(self, cost: CostRecord) -> None:
        """Persist a charge to the ledger (also serves the budget calculation)."""
        self.store.save_cost(cost)
        if cost.amount_units:
            logger.debug(
                "charged %d units (%s); %d remaining today",
                cost.amount_units, cost.operation_id, self.remaining(),
            )

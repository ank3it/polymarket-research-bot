"""Stage 1 — discover and filter markets worth researching."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from research_bot.config import Settings
from research_bot.models import Market
from research_bot.polymarket.gamma import GammaClient
from research_bot.store import Store

logger = logging.getLogger(__name__)


def _days_to_resolution(market: Market) -> float | None:
    if not market.end_date:
        return None
    end = market.end_date
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return (end - datetime.now(timezone.utc)).total_seconds() / 86400


def passes_filters(market: Market, settings: Settings) -> bool:
    if market.liquidity < settings.min_liquidity:
        return False
    dtr = _days_to_resolution(market)
    if dtr is not None:
        if dtr < settings.min_days_to_resolution or dtr > settings.max_days_to_resolution:
            return False
    if len(market.outcomes) != 2:  # v1: binary markets only
        return False
    return True


class Scanner:
    def __init__(self, settings: Settings, gamma: GammaClient, store: Store) -> None:
        self.settings = settings
        self.gamma = gamma
        self.store = store

    async def scan(
        self, *, limit: int, category: str | None = None, redo_seen: bool = False
    ) -> list[Market]:
        extra = {"tag": category} if category else None
        # Over-fetch, then filter down to `limit` eligible markets.
        candidates = await self.gamma.list_markets(limit=max(limit * 5, 50), extra_params=extra)

        selected: list[Market] = []
        for m in candidates:
            if not passes_filters(m, self.settings):
                continue
            if not redo_seen and self.store.seen_recently(
                m.id, self.settings.min_days_to_resolution
            ):
                continue
            selected.append(m)
            if len(selected) >= limit:
                break

        logger.info("Scanner selected %d / %d candidates", len(selected), len(candidates))
        return selected

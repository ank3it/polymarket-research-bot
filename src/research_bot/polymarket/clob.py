"""Polymarket CLOB API — live prices (public read, no auth).

Base: https://clob.polymarket.com
Use the per-outcome `token_id` (from Gamma `clobTokenIds`), NOT the condition_id.
"""
from __future__ import annotations

import logging

import httpx

from research_bot.config import Settings, get_settings
from research_bot.models import Market

logger = logging.getLogger(__name__)


class ClobClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def midpoint(self, token_id: str) -> float | None:
        """Midpoint price (0..1) for a token. Falls back to None on error."""
        url = f"{self.settings.polymarket_clob_url}/midpoint"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params={"token_id": token_id})
            if resp.status_code != 200:
                logger.warning("CLOB midpoint %s -> HTTP %s", token_id, resp.status_code)
                return None
            data = resp.json()
        raw = data.get("mid") if isinstance(data, dict) else None
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    async def yes_price(self, market: Market) -> float | None:
        """Live P(YES). Prefer CLOB midpoint; fall back to Gamma's outcome price."""
        token_id = market.clob_token_ids.get("Yes")
        if token_id:
            mid = await self.midpoint(token_id)
            if mid is not None:
                return mid
        return market.yes_price

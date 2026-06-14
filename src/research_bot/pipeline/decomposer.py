"""Stage 2 — decompose a market's resolution rules into sub-questions (LLM via Gordon)."""
from __future__ import annotations

import logging
import uuid

from research_bot.config import Settings
from research_bot.gordon.client import GordonClient
from research_bot.gordon.inference import complete
from polymarket_research_core.models import CostRecord, Market, SubQuestion
from polymarket_research_core.prompts import DECOMPOSE_SYSTEM, decompose_prompt
from polymarket_research_core.util import clamp01, extract_json

logger = logging.getLogger(__name__)


def _fallback(market: Market) -> list[SubQuestion]:
    """If the LLM output can't be parsed, research the market question directly."""
    return [SubQuestion(id=str(uuid.uuid4()), market_id=market.id, text=market.question,
                        weight=1.0, impact="high")]


class Decomposer:
    def __init__(self, settings: Settings, gordon: GordonClient) -> None:
        self.settings = settings
        self.gordon = gordon

    async def decompose(self, market: Market) -> tuple[list[SubQuestion], CostRecord]:
        text, cost = await complete(
            self.gordon, self.settings,
            prompt=decompose_prompt(market), system=DECOMPOSE_SYSTEM, max_tokens=800,
        )
        cost.market_id = market.id
        data = extract_json(text)

        items = data.get("sub_questions") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            logger.warning("Decompose parse failed for %s; using fallback", market.slug)
            return _fallback(market), cost

        subs: list[SubQuestion] = []
        for item in items[:6]:
            if not isinstance(item, dict) or not item.get("text"):
                continue
            impact = "high" if str(item.get("impact", "low")).lower() == "high" else "low"
            subs.append(
                SubQuestion(
                    id=str(uuid.uuid4()),
                    market_id=market.id,
                    text=str(item["text"]),
                    weight=clamp01(float(item.get("weight", 0.5) or 0.5)),
                    impact=impact,
                )
            )
        return (subs or _fallback(market)), cost

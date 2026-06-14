"""Stage 5 — edge = model probability - market-implied probability."""
from __future__ import annotations

from dataclasses import dataclass

from research_bot.config import Settings


@dataclass
class EdgeResult:
    market_price: float
    edge: float
    flagged: bool


def compute_edge(
    model_prob: float, market_price: float, confidence: float, settings: Settings
) -> EdgeResult:
    edge = model_prob - market_price
    flagged = (
        abs(edge) >= settings.edge_threshold and confidence >= settings.confidence_threshold
    )
    return EdgeResult(market_price=market_price, edge=edge, flagged=flagged)

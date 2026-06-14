"""Pydantic data contracts shared across the pipeline."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Market(BaseModel):
    """A Polymarket market (binary YES/NO assumed for v1)."""

    id: str
    slug: str
    question: str
    description: str = ""
    resolution_rules: str = ""
    end_date: datetime | None = None
    liquidity: float = 0.0
    volume: float = 0.0
    outcomes: list[str] = Field(default_factory=lambda: ["Yes", "No"])
    clob_token_ids: dict[str, str] = Field(default_factory=dict)  # outcome -> token_id
    market_prices: dict[str, float] = Field(default_factory=dict)  # outcome -> implied prob

    @property
    def yes_price(self) -> float | None:
        return self.market_prices.get("Yes")


class SubQuestion(BaseModel):
    id: str
    market_id: str
    text: str
    weight: float = 1.0
    impact: Literal["high", "low"] = "low"


class Evidence(BaseModel):
    sub_question_id: str
    provider: str
    operation_id: str
    url: str
    title: str = ""
    snippet: str = ""
    published_date: date | None = None
    retrieved_at: datetime = Field(default_factory=_now)


class ProbabilityEstimate(BaseModel):
    sub_question_id: str
    prob: float                       # 0..1, P(YES) for the sub-question
    confidence: float = 0.5           # 0..1
    samples: list[float] = Field(default_factory=list)
    rationale: str = ""


class ResearchNote(BaseModel):
    market_id: str
    market_slug: str
    question: str
    model_prob: float                 # aggregated P(YES) for the market
    market_price: float               # implied P(YES) from Polymarket
    edge: float                       # model_prob - market_price
    confidence: float
    flagged: bool = False
    sub_estimates: list[ProbabilityEstimate] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    cost_units: int = 0
    created_at: datetime = Field(default_factory=_now)


class CostRecord(BaseModel):
    market_id: str = ""               # set by the caller after the call returns
    settlement_id: str | None = None
    service_id: str = ""
    operation_id: str = ""
    amount_units: int = 0
    receipt_status: str = "unknown"   # confirmed | failed | null | unknown
    created_at: datetime = Field(default_factory=_now)

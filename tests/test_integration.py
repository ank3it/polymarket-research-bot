"""End-to-end pipeline test with a stubbed Gordon transport.

Exercises the real stage code (decompose -> research -> estimate -> edge -> note)
without network access, secrets, or spend. The fake returns canned search hits
and inference JSON, switching on the prompt content.
"""
from __future__ import annotations

import pytest

from research_bot.budget import BudgetGuard
from research_bot.config import Settings
from research_bot.gordon.client import CallResult
from research_bot.models import CostRecord, Market
from research_bot.pipeline.decomposer import Decomposer
from research_bot.pipeline.edge import compute_edge
from research_bot.pipeline.estimator import Estimator
from research_bot.pipeline.notes import build_note, render_markdown
from research_bot.pipeline.researcher import Researcher
from research_bot.store import Store


class FakeGordon:
    """Stands in for GordonClient.call_service (duck-typed)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call_service(self, operation: str, params: dict, max_payment_units: int) -> CallResult:
        self.calls.append((operation, params))

        # search ops -> canned hits
        if "search" in operation or operation.split(".")[0] in {"exa", "tavily"}:
            payload = {
                "results": [
                    {
                        "url": "https://example.com/a",
                        "title": "Source A",
                        "text": "Strong evidence the event will occur.",
                        "publishedDate": "2026-05-01",
                    }
                ]
            }
            return CallResult(
                payload=payload,
                cost=CostRecord(settlement_id="s", amount_units=1000,
                                operation_id=operation, receipt_status="confirmed"),
            )

        # inference ops -> JSON keyed off the prompt
        msg = (params.get("messages") or [{}])[0].get("content", "").lower()
        if "break this into" in msg:
            text = (
                '{"sub_questions": ['
                '{"text": "Will A occur?", "weight": 0.6, "impact": "high"},'
                '{"text": "Will B occur?", "weight": 0.4, "impact": "low"}]}'
            )
        elif "estimate p(yes)" in msg:
            text = '{"prob": 0.72, "confidence": 0.8, "rationale": "Evidence leans yes."}'
        else:
            text = "{}"
        return CallResult(
            payload={"content": [{"type": "text", "text": text}]},
            cost=CostRecord(settlement_id="s", amount_units=2000,
                            operation_id=operation, receipt_status="confirmed"),
        )


def _market() -> Market:
    return Market(
        id="1", slug="will-x-happen", question="Will X happen?",
        resolution_rules="Resolves YES if X occurs before the end date.",
        liquidity=10000.0, outcomes=["Yes", "No"],
        clob_token_ids={"Yes": "tokenYes", "No": "tokenNo"},
        market_prices={"Yes": 0.55, "No": 0.45},
    )


@pytest.mark.asyncio
async def test_full_pipeline_offline():
    settings = Settings(_env_file=None, estimator_samples=2, edge_threshold=0.07,
                        confidence_threshold=0.6)
    store = Store(":memory:")
    budget = BudgetGuard(settings, store)
    gordon = FakeGordon()
    market = _market()

    # decompose
    subs, dcost = await Decomposer(settings, gordon).decompose(market)
    assert len(subs) == 2
    assert any(s.impact == "high" for s in subs)

    # research
    evidence_by_sub, rcosts = await Researcher(settings, gordon, budget).research(subs)
    assert all(len(evidence_by_sub[s.id]) == 1 for s in subs)

    # estimate
    model_prob, confidence, estimates, ecosts = await Estimator(
        settings, gordon, budget
    ).estimate(subs, evidence_by_sub)
    assert 0.0 < model_prob <= 1.0
    assert len(estimates) == 2
    # each sub-question drew `estimator_samples` samples
    assert all(len(e.samples) == settings.estimator_samples for e in estimates)

    # edge + note
    price = market.market_prices["Yes"]
    edge = compute_edge(model_prob, price, confidence, settings)
    all_ev = [e for lst in evidence_by_sub.values() for e in lst]
    cost_units = dcost.amount_units + sum(c.amount_units for c in (*rcosts, *ecosts))
    note = build_note(market, model_prob=model_prob, confidence=confidence, edge=edge,
                      estimates=estimates, evidence=all_ev, cost_units=cost_units)

    assert note.market_price == 0.55
    assert round(note.edge, 2) == round(model_prob - 0.55, 2)
    assert note.cost_units > 0
    md = render_markdown(note)
    assert "Research note" in md
    assert "Not a trade recommendation" in md

    # researcher + estimator charged the ledger (decompose isn't charged here;
    # the orchestrator charges it in the real loop)
    assert store.spent_today_units() == cost_units - dcost.amount_units


@pytest.mark.asyncio
async def test_budget_fail_closed_blocks_calls():
    # daily budget below one call -> researcher skips, no spend
    settings = Settings(_env_file=None, daily_budget_units=0)
    store = Store(":memory:")
    budget = BudgetGuard(settings, store)
    gordon = FakeGordon()
    subs, _ = await Decomposer(settings, gordon).decompose(_market())
    evidence_by_sub, rcosts = await Researcher(settings, gordon, budget).research(subs)
    assert rcosts == []
    assert all(evidence_by_sub[s.id] == [] for s in subs)

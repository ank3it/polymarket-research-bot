"""Stage 3 — research each sub-question via Gordon-brokered search.

Routing: high-impact sub-questions escalate to the deep-research op; the rest use
the cheap triage op. Every paid call is budget-checked (fail-closed) and charged
to the ledger.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from research_bot.budget import BudgetGuard
from research_bot.config import Settings
from research_bot.gordon.client import GordonClient, GordonError
from research_bot.gordon.routing import OpChoice, search_op
from polymarket_research_core.models import Evidence, SubQuestion

logger = logging.getLogger(__name__)

RESULTS_PER_QUERY = 5


def _search_params(operation: str, query: str, k: int) -> dict[str, Any]:
    """Map a query to the provider's expected request params."""
    slug = operation.split(".", 1)[0].lower()
    if slug == "tavily":
        return {"query": query, "max_results": k, "include_raw_content": False}
    if slug == "parallel":
        return {"objective": query, "search_queries": [query]}
    # exa / brave / default
    return {"query": query, "numResults": k}


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_results(
    payload: Any, sub_id: str, provider: str, operation: str, k: int
) -> list[Evidence]:
    rows: list[Any] = []
    if isinstance(payload, dict):
        for key in ("results", "data", "hits", "sources", "items", "citations"):
            if isinstance(payload.get(key), list):
                rows = payload[key]
                break
    elif isinstance(payload, list):
        rows = payload

    evidence: list[Evidence] = []
    for r in rows[:k]:
        if not isinstance(r, dict):
            continue
        url = r.get("url") or r.get("link") or ""
        snippet = (
            r.get("snippet") or r.get("text") or r.get("content")
            or r.get("summary") or r.get("excerpt") or ""
        )
        evidence.append(
            Evidence(
                sub_question_id=sub_id,
                provider=provider,
                operation_id=operation,
                url=str(url),
                title=str(r.get("title") or r.get("name") or ""),
                snippet=str(snippet)[:500],
                published_date=_parse_date(
                    r.get("publishedDate") or r.get("published_date") or r.get("date")
                ),
            )
        )
    return evidence


class Researcher:
    def __init__(self, settings: Settings, gordon: GordonClient, budget: BudgetGuard) -> None:
        self.settings = settings
        self.gordon = gordon
        self.budget = budget

    async def research(
        self, sub_questions: list[SubQuestion]
    ) -> tuple[dict[str, list[Evidence]], list]:
        evidence_by_sub: dict[str, list[Evidence]] = {}
        costs = []
        for sub in sub_questions:
            tier = "deep" if sub.impact == "high" else "triage"
            choice = search_op(self.settings, tier)
            ev, cost = await self._search_one(sub, choice)
            evidence_by_sub[sub.id] = ev
            if cost is not None:
                costs.append(cost)
        return evidence_by_sub, costs

    async def _search_one(self, sub: SubQuestion, choice: OpChoice):
        if not self.budget.can_afford(choice.max_payment_units):
            logger.warning("Budget exhausted; skipping research for sub-question %s", sub.id)
            return [], None

        params = _search_params(choice.operation, sub.text, RESULTS_PER_QUERY)
        provider = choice.operation.split(".", 1)[0]
        try:
            result = await self.gordon.call_service(
                choice.operation, params, choice.max_payment_units
            )
        except GordonError as exc:
            logger.error("Search failed for sub-question %s: %s", sub.id, exc)
            return [], None

        result.cost.market_id = sub.market_id
        self.budget.charge(result.cost)
        evidence = _parse_results(
            result.payload, sub.id, provider, choice.operation, RESULTS_PER_QUERY
        )
        logger.info("Researched '%s' via %s -> %d sources", sub.text[:60], provider, len(evidence))
        return evidence, result.cost

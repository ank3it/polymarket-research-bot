"""Orchestrator — runs the research loop with a fail-closed budget guard."""
from __future__ import annotations

import logging

from research_bot.budget import BudgetGuard
from research_bot.config import Settings, get_settings, units_to_usd
from research_bot.gordon.client import GordonClient, fetch_skill_md
from research_bot.models import Market, ResearchNote
from research_bot.pipeline.decomposer import Decomposer
from research_bot.pipeline.edge import compute_edge
from research_bot.pipeline.estimator import Estimator
from research_bot.pipeline.notes import build_note, save
from research_bot.pipeline.researcher import Researcher
from research_bot.pipeline.scanner import Scanner
from research_bot.polymarket.clob import ClobClient
from research_bot.polymarket.gamma import GammaClient
from research_bot.store import Store

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, settings: Settings | None = None, out_dir: str = "outputs/notes") -> None:
        self.settings = settings or get_settings()
        self.out_dir = out_dir
        self.store = Store(self.settings.database_path)
        self.gamma = GammaClient(self.settings)
        self.clob = ClobClient(self.settings)

    async def run(
        self, *, limit: int = 5, category: str | None = None,
        slug: str | None = None, redo_seen: bool = False,
    ) -> list[ResearchNote]:
        async with GordonClient(self.settings) as gordon:
            budget = BudgetGuard(self.settings, self.store)
            scanner = Scanner(self.settings, self.gamma, self.store)
            decomposer = Decomposer(self.settings, gordon)
            researcher = Researcher(self.settings, gordon, budget)
            estimator = Estimator(self.settings, gordon, budget)

            if slug:
                market = await self.gamma.get_market(slug)
                markets = [market] if market else []
            else:
                markets = await scanner.scan(limit=limit, category=category, redo_seen=redo_seen)

            notes: list[ResearchNote] = []
            for market in markets:
                if budget.remaining() <= 0:
                    logger.warning("Daily budget exhausted; stopping run.")
                    break
                note = await self._process(market, gordon, budget, decomposer, researcher, estimator)
                if note is not None:
                    notes.append(note)
            return notes

    async def _process(
        self, market: Market, gordon: GordonClient, budget: BudgetGuard,
        decomposer: Decomposer, researcher: Researcher, estimator: Estimator,
    ) -> ResearchNote | None:
        if not budget.can_afford(self.settings.inference_max_units):
            logger.warning("Insufficient budget to start market %s; skipping.", market.slug)
            return None

        logger.info("Processing market: %s", market.question[:80])
        subs, dcost = await decomposer.decompose(market)
        budget.charge(dcost)

        evidence_by_sub, rcosts = await researcher.research(subs)
        model_prob, confidence, estimates, ecosts = await estimator.estimate(subs, evidence_by_sub)

        price = await self.clob.yes_price(market)
        if price is None:
            logger.warning("No live price for %s; skipping note.", market.slug)
            self.store.mark_seen(market)
            return None

        edge = compute_edge(model_prob, price, confidence, self.settings)
        all_evidence = [e for lst in evidence_by_sub.values() for e in lst]
        cost_units = dcost.amount_units + sum(
            c.amount_units for c in (*rcosts, *ecosts)
        )

        note = build_note(
            market, model_prob=model_prob, confidence=confidence, edge=edge,
            estimates=estimates, evidence=all_evidence, cost_units=cost_units,
        )
        save(note, self.out_dir)
        self.store.save_note(note)
        self.store.mark_seen(market)
        logger.info(
            "Note for %s: model=%.2f market=%.2f edge=%+.2f conf=%.2f cost=$%.4f flagged=%s",
            market.slug, model_prob, price, edge.edge, confidence,
            units_to_usd(cost_units), edge.flagged,
        )
        return note

    # ---- P0 connectivity check ----
    async def doctor(self) -> dict[str, str]:
        report: dict[str, str] = {}

        # Polymarket
        try:
            markets = await self.gamma.list_markets(limit=1)
            report["polymarket_gamma"] = (
                f"ok ({markets[0].slug})" if markets else "ok (no markets returned)"
            )
            if markets and markets[0].clob_token_ids.get("Yes"):
                mid = await self.clob.midpoint(markets[0].clob_token_ids["Yes"])
                report["polymarket_clob"] = f"ok (mid={mid})"
        except Exception as exc:  # noqa: BLE001
            report["polymarket_gamma"] = f"FAIL: {exc}"

        # Gordon SKILL.md (public)
        try:
            skill = await fetch_skill_md()
            report["gordon_skill_md"] = f"ok ({len(skill)} bytes)"
        except Exception as exc:  # noqa: BLE001
            report["gordon_skill_md"] = f"FAIL: {exc}"

        # Gordon MCP (requires key)
        if not self.settings.gordon_configured:
            report["gordon_mcp"] = "skipped (no agent key/secret in .env)"
            return report
        try:
            async with GordonClient(self.settings) as gordon:
                enabled = await gordon.list_enabled_services()
                balance = await gordon.get_balance()
                report["gordon_mcp"] = "ok"
                report["gordon_enabled_services"] = str(enabled)[:200]
                report["gordon_balance"] = str(balance)[:200]
        except Exception as exc:  # noqa: BLE001
            report["gordon_mcp"] = f"FAIL: {exc}"
        return report

    async def services(self, query: str) -> object:
        async with GordonClient(self.settings) as gordon:
            return await gordon.find_service(query)

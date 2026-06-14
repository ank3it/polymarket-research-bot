"""Stage 4 — multisample probability estimation (LLM via Gordon).

For each sub-question we draw N samples, aggregate to a probability + confidence
(confidence is penalized by sample dispersion), then combine sub-questions into a
single market probability via their weights.
"""
from __future__ import annotations

import logging
import statistics

from research_bot.budget import BudgetGuard
from research_bot.config import Settings
from research_bot.gordon.client import GordonClient, GordonError
from research_bot.gordon.inference import complete
from polymarket_research_core.models import Evidence, ProbabilityEstimate, SubQuestion
from polymarket_research_core.prompts import ESTIMATE_SYSTEM, estimate_prompt
from polymarket_research_core.util import clamp01, extract_json

logger = logging.getLogger(__name__)


class Estimator:
    def __init__(self, settings: Settings, gordon: GordonClient, budget: BudgetGuard) -> None:
        self.settings = settings
        self.gordon = gordon
        self.budget = budget

    async def estimate(
        self, sub_questions: list[SubQuestion], evidence_by_sub: dict[str, list[Evidence]]
    ) -> tuple[float, float, list[ProbabilityEstimate], list]:
        estimates: list[ProbabilityEstimate] = []
        costs = []

        for sub in sub_questions:
            est, sub_costs = await self._estimate_one(sub, evidence_by_sub.get(sub.id, []))
            if est is not None:
                estimates.append(est)
            costs.extend(sub_costs)

        if not estimates:
            return 0.5, 0.0, [], costs

        weights = {s.id: s.weight for s in sub_questions}
        total_w = sum(weights.get(e.sub_question_id, 1.0) for e in estimates) or 1.0
        model_prob = sum(
            e.prob * weights.get(e.sub_question_id, 1.0) for e in estimates
        ) / total_w
        confidence = sum(
            e.confidence * weights.get(e.sub_question_id, 1.0) for e in estimates
        ) / total_w
        return clamp01(model_prob), clamp01(confidence), estimates, costs

    async def _estimate_one(self, sub: SubQuestion, evidence: list[Evidence]):
        probs: list[float] = []
        confs: list[float] = []
        rationale = ""
        costs = []

        for _ in range(self.settings.estimator_samples):
            if not self.budget.can_afford(self.settings.inference_max_units):
                logger.warning("Budget exhausted mid-estimation for %s", sub.id)
                break
            try:
                text, cost = await complete(
                    self.gordon, self.settings,
                    prompt=estimate_prompt(sub, evidence),
                    system=ESTIMATE_SYSTEM, max_tokens=600,
                )
            except GordonError as exc:
                logger.error("Inference failed for %s: %s", sub.id, exc)
                break
            cost.market_id = sub.market_id
            self.budget.charge(cost)
            costs.append(cost)

            data = extract_json(text)
            if not isinstance(data, dict) or "prob" not in data:
                continue
            try:
                probs.append(clamp01(float(data["prob"])))
                confs.append(clamp01(float(data.get("confidence", 0.5))))
            except (TypeError, ValueError):
                continue
            rationale = str(data.get("rationale", rationale))

        if not probs:
            return None, costs

        mean_prob = statistics.fmean(probs)
        dispersion = statistics.pstdev(probs) if len(probs) > 1 else 0.0
        mean_conf = statistics.fmean(confs) if confs else 0.5
        confidence = clamp01(mean_conf - dispersion)  # penalize disagreement
        est = ProbabilityEstimate(
            sub_question_id=sub.id, prob=mean_prob, confidence=confidence,
            samples=probs, rationale=rationale,
        )
        return est, costs

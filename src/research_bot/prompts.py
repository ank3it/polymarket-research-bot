"""LLM prompt templates for decomposition and estimation."""
from __future__ import annotations

from research_bot.models import Evidence, Market, SubQuestion

DECOMPOSE_SYSTEM = (
    "You are a forecasting analyst. You break a prediction-market question into a "
    "small set of precise, independently-researchable sub-questions whose answers "
    "together determine the outcome. You are rigorous about what the resolution "
    "rules actually require to resolve YES."
)


def decompose_prompt(market: Market) -> str:
    return f"""Market question: {market.question}

Resolution rules / description:
{market.resolution_rules or market.description or "(none provided)"}

End date: {market.end_date.isoformat() if market.end_date else "unknown"}

Break this into 2-6 sub-questions that must be researched to estimate P(YES).
For each, give a weight (0-1, how much it drives the outcome) and impact
("high" if it is pivotal, else "low").

Respond ONLY with JSON:
{{"sub_questions": [{{"text": "...", "weight": 0.5, "impact": "high"}}]}}"""


ESTIMATE_SYSTEM = (
    "You are a calibrated forecaster. Given a sub-question and dated evidence, you "
    "output a probability that the sub-question resolves YES, your confidence in "
    "that estimate, and a one-paragraph rationale. You never overstate certainty "
    "and you weight more recent, higher-quality sources more heavily."
)


def estimate_prompt(sub_question: SubQuestion, evidence: list[Evidence]) -> str:
    if evidence:
        ev_lines = "\n".join(
            f"- [{e.published_date or 'n/d'}] {e.title}: {e.snippet} ({e.url})"
            for e in evidence
        )
    else:
        ev_lines = "(no evidence retrieved)"
    return f"""Sub-question: {sub_question.text}

Evidence:
{ev_lines}

Estimate P(YES) for this sub-question.

Respond ONLY with JSON:
{{"prob": 0.0-1.0, "confidence": 0.0-1.0, "rationale": "..."}}"""

"""Maps a research tier / task to a Gordon catalog operation + spend cap.

Kept separate from pipeline code so providers and budgets are tunable via config
without touching the research logic. The operation slugs are confirmed at setup
against the agent's enabled catalog (`research-bot services`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from research_bot.config import Settings

Tier = Literal["triage", "deep"]


@dataclass(frozen=True)
class OpChoice:
    operation: str
    max_payment_units: int


def search_op(settings: Settings, tier: Tier) -> OpChoice:
    """Cheap, broad triage vs. high-accuracy deep research."""
    if tier == "deep":
        return OpChoice(settings.deep_research_op, settings.deep_max_units)
    return OpChoice(settings.triage_search_op, settings.triage_max_units)


def inference_op(settings: Settings) -> OpChoice:
    return OpChoice(settings.inference_op, settings.inference_max_units)

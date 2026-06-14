"""Stage 6 — assemble, render, and persist the research note."""
from __future__ import annotations

import logging
from pathlib import Path

from research_bot.config import units_to_usd
from polymarket_research_core.models import Evidence, Market, ProbabilityEstimate, ResearchNote
from polymarket_research_core.edge import EdgeResult

logger = logging.getLogger(__name__)


def build_note(
    market: Market,
    *,
    model_prob: float,
    confidence: float,
    edge: EdgeResult,
    estimates: list[ProbabilityEstimate],
    evidence: list[Evidence],
    cost_units: int,
) -> ResearchNote:
    return ResearchNote(
        market_id=market.id,
        market_slug=market.slug,
        question=market.question,
        model_prob=model_prob,
        market_price=edge.market_price,
        edge=edge.edge,
        confidence=confidence,
        flagged=edge.flagged,
        sub_estimates=estimates,
        evidence=evidence,
        cost_units=cost_units,
    )


def render_markdown(note: ResearchNote) -> str:
    pct = lambda x: f"{x * 100:.1f}%"  # noqa: E731
    flag = "🚩 FLAGGED" if note.flagged else "—"
    lines = [
        f"# Research note — {note.question}",
        "",
        f"- **Model P(YES):** {pct(note.model_prob)}",
        f"- **Market P(YES):** {pct(note.market_price)}",
        f"- **Edge:** {note.edge * 100:+.1f} pts",
        f"- **Confidence:** {pct(note.confidence)}",
        f"- **Signal:** {flag}",
        f"- **Research cost:** ${units_to_usd(note.cost_units):.4f}",
        f"- **Market:** https://polymarket.com/market/{note.market_slug}",
        f"- **Generated:** {note.created_at.isoformat()}",
        "",
        "## Sub-question estimates",
        "",
    ]
    if note.sub_estimates:
        by_id = {e.sub_question_id: e for e in note.sub_estimates}
        for est in note.sub_estimates:
            lines.append(f"- **{pct(est.prob)}** (conf {pct(est.confidence)}) — {est.rationale}")
        _ = by_id
    else:
        lines.append("_No sub-question estimates produced._")

    lines += ["", "## Evidence", ""]
    if note.evidence:
        for ev in note.evidence:
            d = ev.published_date.isoformat() if ev.published_date else "n/d"
            lines.append(f"- [{d}] [{ev.title or ev.url}]({ev.url}) — {ev.snippet}")
    else:
        lines.append("_No evidence retrieved._")

    lines += [
        "",
        "---",
        "_Research-only output. Not a trade recommendation. Verify before acting._",
        "",
    ]
    return "\n".join(lines)


def save(note: ResearchNote, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = note.market_slug or note.market_id
    md_path = out / f"{stem}.md"
    json_path = out / f"{stem}.json"
    md_path.write_text(render_markdown(note), encoding="utf-8")
    json_path.write_text(note.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Wrote note %s", md_path)
    return md_path, json_path

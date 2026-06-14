"""Unit tests for the pure / parsing logic (no network)."""
from __future__ import annotations

from research_bot.config import Settings, units_to_usd, usd_to_units
from research_bot.gordon.client import _extract_cost, _extract_payload
from research_bot.gordon.inference import extract_text
from research_bot.gordon.routing import inference_op, search_op
from research_bot.models import Evidence, Market, ProbabilityEstimate, ResearchNote
from research_bot.pipeline.edge import compute_edge
from research_bot.pipeline.notes import render_markdown
from research_bot.pipeline.researcher import _parse_results, _search_params
from research_bot.pipeline.scanner import passes_filters
from research_bot.polymarket.gamma import parse_market
from research_bot.util import clamp01, extract_json


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


# ---- money ----
def test_units_usd_roundtrip():
    assert units_to_usd(7000) == 0.007
    assert usd_to_units(0.01) == 10000


# ---- util ----
def test_extract_json_fenced():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_inline_prose():
    assert extract_json('here you go: {"prob": 0.4} ok') == {"prob": 0.4}


def test_extract_json_bad():
    assert extract_json("not json at all") is None


def test_clamp01():
    assert clamp01(-1) == 0.0
    assert clamp01(2) == 1.0
    assert clamp01(0.5) == 0.5


# ---- routing ----
def test_routing_tiers():
    s = _settings()
    assert search_op(s, "triage").operation == s.triage_search_op
    assert search_op(s, "deep").operation == s.deep_research_op
    assert search_op(s, "deep").max_payment_units == s.deep_max_units
    assert inference_op(s).operation == s.inference_op


# ---- search param mapping ----
def test_search_params_providers():
    assert _search_params("tavily.search", "q", 5)["max_results"] == 5
    assert _search_params("exa.search.web", "q", 5)["numResults"] == 5
    assert "objective" in _search_params("parallel.task.run", "q", 5)


# ---- result parsing ----
def test_parse_results_exa_shape():
    payload = {"results": [
        {"url": "http://x", "title": "T", "text": "snippet", "publishedDate": "2026-01-02"},
    ]}
    ev = _parse_results(payload, "sub1", "exa", "exa.search.web", 5)
    assert len(ev) == 1
    assert ev[0].url == "http://x"
    assert ev[0].published_date.isoformat() == "2026-01-02"


# ---- gordon call parsing (real SKILL.md shape: data + meta) ----
def test_extract_cost_and_payload_meta_shape():
    obj = {
        "data": {"results": []},
        "meta": {"paid_usd": "0.007", "network": "base",
                 "settlement_id": "s1", "settlement_status": "confirmed"},
    }
    cost = _extract_cost(obj)
    assert cost.amount_units == 7000          # $0.007 -> 7000 micro-units
    assert cost.settlement_id == "s1"
    assert cost.receipt_status == "confirmed"
    assert _extract_payload(obj) == {"results": []}


def test_extract_cost_no_payment():
    cost = _extract_cost({"data": {}, "meta": {"settlement_status": None}})
    assert cost.amount_units == 0
    assert cost.receipt_status == "null"


# ---- inference text extraction ----
def test_extract_text_anthropic():
    assert extract_text({"content": [{"type": "text", "text": "hi"}]}) == "hi"


def test_extract_text_openai():
    assert extract_text({"choices": [{"message": {"content": "yo"}}]}) == "yo"


def test_extract_text_plain():
    assert extract_text("plain") == "plain"


# ---- gamma parsing (JSON-string fields) ----
def test_parse_market_json_strings():
    raw = {
        "id": "123", "slug": "will-x-happen", "question": "Will X happen?",
        "description": "Resolves YES if X.",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.62", "0.38"]',
        "clobTokenIds": '["tokenYes", "tokenNo"]',
        "liquidity": "12000", "volume": "50000", "endDate": "2026-09-01T00:00:00Z",
    }
    m = parse_market(raw)
    assert m.market_prices["Yes"] == 0.62
    assert m.clob_token_ids["Yes"] == "tokenYes"
    assert m.liquidity == 12000.0
    assert m.end_date is not None


# ---- scanner filters ----
def test_passes_filters_rejects_low_liquidity():
    s = _settings(min_liquidity=5000, min_days_to_resolution=0, max_days_to_resolution=9999)
    m = Market(id="1", slug="s", question="q", liquidity=100.0)
    assert passes_filters(m, s) is False


def test_passes_filters_rejects_non_binary():
    s = _settings(min_liquidity=0, min_days_to_resolution=0, max_days_to_resolution=9999)
    m = Market(id="1", slug="s", question="q", liquidity=10000.0,
               outcomes=["A", "B", "C"])
    assert passes_filters(m, s) is False


# ---- edge ----
def test_compute_edge_flag():
    s = _settings(edge_threshold=0.07, confidence_threshold=0.6)
    res = compute_edge(0.80, 0.60, 0.9, s)
    assert round(res.edge, 2) == 0.20
    assert res.flagged is True


def test_compute_edge_low_confidence_not_flagged():
    s = _settings(edge_threshold=0.07, confidence_threshold=0.6)
    res = compute_edge(0.80, 0.60, 0.3, s)
    assert res.flagged is False


# ---- note render ----
def test_render_markdown_contains_disclaimer():
    note = ResearchNote(
        market_id="1", market_slug="s", question="Will X happen?",
        model_prob=0.7, market_price=0.6, edge=0.1, confidence=0.8, flagged=True,
        sub_estimates=[ProbabilityEstimate(sub_question_id="a", prob=0.7,
                                           confidence=0.8, rationale="because")],
        evidence=[Evidence(sub_question_id="a", provider="exa",
                           operation_id="exa.search.web", url="http://x", title="T",
                           snippet="snip")],
        cost_units=14000,
    )
    md = render_markdown(note)
    assert "Not a trade recommendation" in md
    assert "FLAGGED" in md
    assert "$0.0140" in md

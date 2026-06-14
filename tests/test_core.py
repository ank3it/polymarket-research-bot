"""CLI-specific unit tests (shared logic is tested in polymarket-research-core)."""
from __future__ import annotations

from polymarket_research_core.models import Market

from research_bot.config import Settings
from research_bot.gordon.client import _extract_cost, _extract_payload
from research_bot.gordon.inference import extract_text
from research_bot.gordon.routing import inference_op, search_op
from research_bot.pipeline.researcher import _parse_results, _search_params
from research_bot.pipeline.scanner import passes_filters


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


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
    assert cost.amount_units == 7000
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


# ---- scanner filters ----
def test_passes_filters_rejects_low_liquidity():
    s = _settings(min_liquidity=5000, min_days_to_resolution=0, max_days_to_resolution=9999)
    m = Market(id="1", slug="s", question="q", liquidity=100.0)
    assert passes_filters(m, s) is False


def test_passes_filters_rejects_non_binary():
    s = _settings(min_liquidity=0, min_days_to_resolution=0, max_days_to_resolution=9999)
    m = Market(id="1", slug="s", question="q", liquidity=10000.0, outcomes=["A", "B", "C"])
    assert passes_filters(m, s) is False

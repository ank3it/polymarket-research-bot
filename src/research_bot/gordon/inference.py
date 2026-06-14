"""LLM inference routed through Gordon's `ai` catalog.

Inference is a metered, audited Gordon service exactly like web search. This
helper builds the request params, calls the configured inference operation, and
normalizes the completion text out of common provider response shapes.

The exact `params` shape depends on the catalog operation (Anthropic-style here).
Confirm with `gordon_get_service <slug>` and adjust `build_params` if needed.
"""
from __future__ import annotations

import json
from typing import Any

from research_bot.config import Settings
from research_bot.gordon.client import GordonClient
from research_bot.gordon.routing import inference_op
from polymarket_research_core.models import CostRecord


def build_params(settings: Settings, prompt: str, system: str | None, max_tokens: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": settings.inference_model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        params["system"] = system
    return params


def extract_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        # Anthropic messages: {"content": [{"type": "text", "text": "..."}]}
        content = payload.get("content")
        if isinstance(content, list):
            parts = [b.get("text", "") for b in content if isinstance(b, dict)]
            if any(parts):
                return "".join(parts)
        if isinstance(content, str):
            return content
        # OpenAI chat: {"choices": [{"message": {"content": "..."}}]}
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            msg = first.get("message", {}) if isinstance(first, dict) else {}
            if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                return msg["content"]
            if isinstance(first, dict) and isinstance(first.get("text"), str):
                return first["text"]
        for key in ("text", "output_text", "completion", "answer"):
            if isinstance(payload.get(key), str):
                return payload[key]
    return json.dumps(payload) if payload is not None else ""


async def complete(
    gordon: GordonClient,
    settings: Settings,
    *,
    prompt: str,
    system: str | None = None,
    max_tokens: int = 1024,
) -> tuple[str, CostRecord]:
    """Run one inference call through Gordon. Returns (text, cost)."""
    op = inference_op(settings)
    params = build_params(settings, prompt, system, max_tokens)
    result = await gordon.call_service(op.operation, params, op.max_payment_units)
    return extract_text(result.payload), result.cost

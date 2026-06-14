"""Small shared helpers."""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Best-effort parse of a JSON object/array out of an LLM response.

    Handles fenced code blocks and leading/trailing prose. Returns None on failure.
    """
    if not text:
        return None
    candidates: list[str] = []
    m = _FENCE.search(text)
    if m:
        candidates.append(m.group(1))
    candidates.append(text)

    # also try the first {...} or [...] span
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if 0 <= start < end:
            candidates.append(text[start : end + 1])

    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))

"""Async wrapper around the Gordon MCP server.

Gordon runs as a remote HTTP MCP server (https://api.withgordon.ai/mcp). The bot
connects as an MCP client, authenticating with the agent key/secret, and calls
catalog services through `gordon_call_service` — Gordon performs the full
402 -> authorize -> retry -> confirm payment flow and returns a receipt.

Docs: https://www.withgordon.ai/docs

NOTE: the exact JSON shape returned by each tool is parsed defensively. On first
live run, log `CallResult.raw` and tighten `_extract_cost` / `_extract_payload`
to the real fields if they differ.
"""
from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from research_bot.config import Settings, get_settings
from polymarket_research_core.models import CostRecord

logger = logging.getLogger(__name__)

SKILL_MD_URL = "https://api.withgordon.ai/SKILL.md"


@dataclass
class CallResult:
    """Result of a paid service call through Gordon."""

    payload: Any                       # the provider's response (search hits, completion, ...)
    cost: CostRecord
    raw: dict[str, Any] = field(default_factory=dict)


class GordonError(RuntimeError):
    pass


def _content_to_obj(result: Any) -> Any:
    """Normalize an MCP call_tool result into a python object.

    Prefers structuredContent; otherwise JSON-decodes the first text block;
    falls back to the raw text string.
    """
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is None:
            continue
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
    return None


def _extract_cost(obj: Any) -> CostRecord:
    """Pull a CostRecord out of a gordon_call_service response.

    Per Gordon's SKILL.md the response is `{ data, meta: { paid_usd, network,
    settlement_id, settlement_status, receipt_url } }`. We read `meta`; amount is
    given in USD (`paid_usd`) and converted to micro-units. Older/alt shapes that
    nest a `receipt`/`settlement` object are also handled.
    """
    meta: dict[str, Any] = {}
    if isinstance(obj, dict):
        if isinstance(obj.get("meta"), dict):
            meta = obj["meta"]
        else:
            for key in ("receipt", "settlement", "transaction"):
                if isinstance(obj.get(key), dict):
                    meta = obj[key]
                    break

    amount = 0
    if meta.get("amount_units") is not None:
        try:
            amount = int(meta["amount_units"])
        except (TypeError, ValueError):
            amount = 0
    elif meta.get("paid_usd") not in (None, ""):
        try:
            amount = int(round(float(meta["paid_usd"]) * 1_000_000))
        except (TypeError, ValueError):
            amount = 0

    status = meta.get("settlement_status", meta.get("receipt_status", meta.get("status")))
    status = "null" if status is None else str(status)

    return CostRecord(
        market_id="",  # filled in by the caller
        settlement_id=meta.get("settlement_id") or meta.get("id"),
        service_id=str(meta.get("service_id", "")),
        operation_id=str(meta.get("operation_id", "")),
        amount_units=amount,
        receipt_status=status,
    )


def _extract_payload(obj: Any) -> Any:
    """Pull the provider response out of a gordon_call_service response."""
    if isinstance(obj, dict):
        for key in ("data", "result", "response", "body", "output"):
            if key in obj:
                return obj[key]
    return obj


class GordonClient:
    """Persistent MCP session to Gordon. Use as an async context manager."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    # ---- lifecycle ----
    async def __aenter__(self) -> "GordonClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self) -> None:
        if not self.settings.gordon_configured:
            raise GordonError(
                "Gordon agent key/secret missing. Set GORDON_AGENT_API_KEY and "
                "GORDON_AGENT_API_SECRET in .env."
            )
        self._stack = AsyncExitStack()
        headers = {"Authorization": self.settings.gordon_auth_header}
        read, write, *_ = await self._stack.enter_async_context(
            streamablehttp_client(self.settings.gordon_mcp_url, headers=headers)
        )
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        logger.info("Connected to Gordon MCP at %s", self.settings.gordon_mcp_url)

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._session = None

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise GordonError("GordonClient is not connected. Call connect() first.")
        return self._session

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await self.session.call_tool(name, arguments)
        if getattr(result, "isError", False):
            raise GordonError(f"Gordon tool {name} returned an error: {_content_to_obj(result)}")
        return _content_to_obj(result)

    # ---- discovery ----
    async def find_service(self, query: str) -> Any:
        """Natural-language catalog search -> matching operations + pricing."""
        return await self._call_tool("gordon_find_service", {"query": query})

    async def list_services(self, category: str | None = None) -> Any:
        args: dict[str, Any] = {}
        if category:
            args["category"] = category
        return await self._call_tool("gordon_list_services", args)

    async def get_service(self, slug: str) -> Any:
        return await self._call_tool("gordon_get_service", {"slug": slug})

    async def list_enabled_services(self) -> Any:
        return await self._call_tool("gordon_list_enabled_services", {})

    async def get_balance(self) -> Any:
        return await self._call_tool("gordon_get_balance", {})

    async def get_receipt(self, settlement_id: str) -> Any:
        return await self._call_tool("gordon_get_receipt", {"settlement_id": settlement_id})

    # ---- paid call ----
    async def call_service(
        self, operation: str, params: dict[str, Any], max_payment_units: int
    ) -> CallResult:
        """Call a catalog operation (e.g. 'exa.search.web'). Gordon pays + audits.

        Args:
            operation: '<slug>.<operation_id>', e.g. 'exa.search.web'.
            params: provider request params (shape depends on the operation).
            max_payment_units: per-call spend cap in micro-units.
        """
        obj = await self._call_tool(
            "gordon_call_service",
            {
                "operation": operation,
                "params": params,
                "max_payment_units": max_payment_units,
            },
        )
        cost = _extract_cost(obj)
        cost.operation_id = cost.operation_id or operation
        payload = _extract_payload(obj)
        raw = obj if isinstance(obj, dict) else {"value": obj}
        return CallResult(payload=payload, cost=cost, raw=raw)


async def fetch_skill_md(timeout: float = 10.0) -> str:
    """Fetch Gordon's machine-readable capability file before the first tool call."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(SKILL_MD_URL)
        resp.raise_for_status()
        return resp.text

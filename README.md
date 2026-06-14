# Polymarket Research Bot

An autonomous **research-only** agent for Polymarket prediction markets. For a given market it produces a **calibrated probability estimate plus a sourced research note** for a human to act on. It **never places trades and never holds trading funds.**

All paid work — web/news research *and* LLM inference — is brokered and paid for through **[Gordon](https://www.withgordon.ai/docs)**, the agent-native financial control plane. The bot holds **no provider API keys**: it discovers services from Gordon's catalog, calls them, and Gordon enforces spend policy and writes an audit receipt for every call.

## What it does

```
Polymarket ─▶ scan ─▶ decompose ─▶ research ─▶ estimate ─▶ edge ─▶ research note ─▶ human
                                       │            │
                                       └── Gordon ──┘   (search + inference, metered & audited)
```

1. **Scan** open Polymarket markets (Gamma API, no auth) and filter by liquidity / time-to-resolution / category.
2. **Decompose** each market's resolution rules into precise, researchable sub-questions (LLM via Gordon).
3. **Research** each sub-question via Gordon-brokered search providers (Tavily / Exa / Parallel …), collecting dated evidence.
4. **Estimate** a probability via Gordon-brokered multisample inference.
5. **Edge** = model probability − live market price (CLOB midpoint).
6. **Note** — render a Markdown + JSON research note with its evidence and its cost.

## Design invariants

- The bot **reads markets and pays for research/inference only** — never touches positions or trading funds.
- **No provider keys in the bot.** Every paid call goes through Gordon with a `max_payment_units` cap and produces a receipt.
- Every note carries its **evidence (with dates)** and its **cost** — no unsourced probabilities.
- Budget is **fail-closed**: if a call would breach the daily cap, the market is skipped rather than overspent.

## Quickstart

```bash
# 1. Install
pip install -e .

# 2. Configure
cp .env.example .env
# edit .env: add your Gordon agent key/secret, tune budgets

# 3. Verify connectivity (P0): Gordon + Polymarket reachable
research-bot doctor

# 4. Run the pipeline over N markets
research-bot run --limit 5 --category politics
```

You need a Gordon agent (key + funded USDC wallet on Base). Create one at
[withgordon.ai → Agents](https://www.withgordon.ai/account/agents) and copy the `gak_sec_` once.
The bot reads the live tool semantics from `https://api.withgordon.ai/SKILL.md` on startup.

## Catalog dependency (read this before a full run)

The bot pays for **search** and **inference** through Gordon's catalog. Run
`research-bot services "web search"` and `research-bot services "llm inference"`
to see what your agent can actually call, then set the op slugs in `.env`:

- `TRIAGE_SEARCH_OP` — a cheap search op (e.g. `exa.search.web`).
- `DEEP_RESEARCH_OP` — a high-accuracy research op for high-impact sub-questions
  (e.g. `parallel.task.run`). Falls back gracefully if not enabled.
- `INFERENCE_OP` — an `ai`-category op for the estimator/decomposer.

> Enabled catalog (Gordon dashboard): **search** — Exa, Tavily, Coingecko,
> Reversesandbox, Stableenrich, Twit; **ai/LLM** — Blockrun, Nansen, Ottoai;
> **scrape** — Zlurp; **data** — Oatp, Onesource, Zapper; **infra** — Seerium;
> **finance** — Stablefinance. Search and inference are both available, so the
> full pipeline can run.
>
> Defaults: triage search = Exa, deep research = Tavily, inference = Blockrun.
> The **service slugs** are correct, but confirm each **operation_id** with
> `research-bot services "web search"` / `"llm inference"` (the bot reads tool
> schemas from the live MCP server, not the published `SKILL.md`, which can lag).
> Missing/disabled ops degrade gracefully — they're skipped, not fatal.

## Money semantics

Gordon prices are in **micro-units: 1,000,000 units = $1.00**. Per-call caps are passed on every call;
per-service daily caps and approval thresholds are configured per agent in the Gordon dashboard.

## Status

v1 — research-only. Execution, wallet funding for positions, dashboard UI, and the calibration
feedback loop are intentionally out of scope and bolt on later without re-architecting.

## License

MIT — see [LICENSE](./LICENSE).

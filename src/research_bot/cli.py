"""Command-line entrypoint.

    research-bot doctor                 # P0 connectivity check
    research-bot services "web search"  # discover catalog operations
    research-bot run --limit 5 --category politics
    research-bot run --slug some-market-slug
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

from research_bot.config import get_settings, units_to_usd
from research_bot.orchestrator import Orchestrator


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def _doctor() -> int:
    report = await Orchestrator().doctor()
    print("\nConnectivity check\n" + "=" * 40)
    failed = False
    for k, v in report.items():
        mark = "✗" if str(v).startswith("FAIL") else "✓"
        if mark == "✗":
            failed = True
        print(f" {mark}  {k}: {v}")
    print()
    return 1 if failed else 0


async def _services(query: str) -> int:
    result = await Orchestrator().services(query)
    print(json.dumps(result, indent=2, default=str))
    return 0


async def _run(limit: int, category: str | None, slug: str | None, redo: bool) -> int:
    notes = await Orchestrator().run(limit=limit, category=category, slug=slug, redo_seen=redo)
    print(f"\nGenerated {len(notes)} research note(s)\n" + "=" * 40)
    for n in notes:
        flag = " 🚩" if n.flagged else ""
        print(
            f" {n.market_slug}: model={n.model_prob:.2f} market={n.market_price:.2f} "
            f"edge={n.edge:+.2f} conf={n.confidence:.2f} "
            f"cost=${units_to_usd(n.cost_units):.4f}{flag}"
        )
    print("\nNotes written to ./outputs/notes/")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="research-bot", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check Gordon + Polymarket connectivity")

    p_services = sub.add_parser("services", help="discover Gordon catalog operations")
    p_services.add_argument("query", help='e.g. "web search" or "llm inference"')

    p_run = sub.add_parser("run", help="run the research pipeline")
    p_run.add_argument("--limit", type=int, default=5)
    p_run.add_argument("--category", default=None)
    p_run.add_argument("--slug", default=None, help="research a single market by slug")
    p_run.add_argument("--redo-seen", action="store_true", help="ignore recent-dedupe")

    args = parser.parse_args()
    _setup_logging(args.verbose)
    _ = get_settings()  # validate env early

    if args.command == "doctor":
        rc = asyncio.run(_doctor())
    elif args.command == "services":
        rc = asyncio.run(_services(args.query))
    elif args.command == "run":
        rc = asyncio.run(_run(args.limit, args.category, args.slug, args.redo_seen))
    else:  # pragma: no cover
        parser.error(f"unknown command {args.command}")
        rc = 2
    raise SystemExit(rc)


if __name__ == "__main__":
    main()

"""SQLite store. Synchronous and intentionally simple for v1.

Swap to Postgres later by keeping the same method surface.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from research_bot.models import CostRecord, Market, ResearchNote

_SCHEMA = """
CREATE TABLE IF NOT EXISTS markets_seen (
    market_id TEXT PRIMARY KEY,
    slug TEXT,
    last_noted_at TEXT
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT,
    slug TEXT,
    created_at TEXT,
    model_prob REAL,
    market_price REAL,
    edge REAL,
    confidence REAL,
    flagged INTEGER,
    cost_units INTEGER,
    json TEXT
);
CREATE TABLE IF NOT EXISTS costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT,
    settlement_id TEXT,
    service_id TEXT,
    operation_id TEXT,
    amount_units INTEGER,
    receipt_status TEXT,
    created_at TEXT
);
"""


class Store:
    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- dedupe ----
    def seen_recently(self, market_id: str, days: int) -> bool:
        row = self.conn.execute(
            "SELECT last_noted_at FROM markets_seen WHERE market_id = ?", (market_id,)
        ).fetchone()
        if not row or not row["last_noted_at"]:
            return False
        try:
            last = datetime.fromisoformat(row["last_noted_at"])
        except ValueError:
            return False
        return last > datetime.now(timezone.utc) - timedelta(days=days)

    def mark_seen(self, market: Market) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO markets_seen(market_id, slug, last_noted_at) VALUES (?,?,?) "
            "ON CONFLICT(market_id) DO UPDATE SET last_noted_at=excluded.last_noted_at, "
            "slug=excluded.slug",
            (market.id, market.slug, now),
        )
        self.conn.commit()

    # ---- notes ----
    def save_note(self, note: ResearchNote) -> int:
        cur = self.conn.execute(
            "INSERT INTO notes(market_id, slug, created_at, model_prob, market_price, "
            "edge, confidence, flagged, cost_units, json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                note.market_id,
                note.market_slug,
                note.created_at.isoformat(),
                note.model_prob,
                note.market_price,
                note.edge,
                note.confidence,
                int(note.flagged),
                note.cost_units,
                note.model_dump_json(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    # ---- costs ----
    def save_cost(self, cost: CostRecord) -> None:
        self.conn.execute(
            "INSERT INTO costs(market_id, settlement_id, service_id, operation_id, "
            "amount_units, receipt_status, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                cost.market_id,
                cost.settlement_id,
                cost.service_id,
                cost.operation_id,
                cost.amount_units,
                cost.receipt_status,
                cost.created_at.isoformat(),
            ),
        )
        self.conn.commit()

    def spent_today_units(self) -> int:
        start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        row = self.conn.execute(
            "SELECT COALESCE(SUM(amount_units), 0) AS total FROM costs WHERE created_at >= ?",
            (start.isoformat(),),
        ).fetchone()
        return int(row["total"] or 0)

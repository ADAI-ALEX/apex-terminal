"""SQLite trade journal + derived performance statistics.

A single file (``data/apex.db``) holds the immutable record of every closed
trade. Everything the dashboard's Performance and Trade Log panels show is
computed from this table, plus the live risk inputs (daily/weekly P&L,
consecutive losses) the heartbeat feeds into the RiskEngine.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from apex.config import Direction
from apex.models import TradeRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     TEXT,
    market_key  TEXT NOT NULL,
    direction   TEXT NOT NULL,
    strategy    TEXT,
    size        REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price  REAL NOT NULL,
    pnl         REAL NOT NULL,
    points      REAL NOT NULL,
    exit_reason TEXT,
    confidence  REAL,
    reasoning   TEXT,
    opened_at   TEXT,
    closed_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_closed_at ON trades(closed_at);
CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_key);
"""


class TradeJournal:
    def __init__(self, path: str | Path = "data/apex.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.info("Trade journal ready at {}", self.path)

    # ── writes ────────────────────────────────────────────────────────
    def record(self, t: TradeRecord) -> None:
        self._conn.execute(
            """INSERT INTO trades (deal_id, market_key, direction, strategy, size, entry_price,
               exit_price, pnl, points, exit_reason, confidence, reasoning, opened_at, closed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t.deal_id, t.market_key, t.direction.value, t.strategy, t.size, t.entry_price,
             t.exit_price, t.pnl, t.points, t.exit_reason, t.confidence, t.reasoning,
             t.opened_at.isoformat(), t.closed_at.isoformat()),
        )
        self._conn.commit()

    # ── reads ─────────────────────────────────────────────────────────
    def recent(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def realised_pnl_since(self, since: datetime) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(pnl),0) AS total FROM trades WHERE closed_at >= ?",
            (since.isoformat(),),
        ).fetchone()
        return float(row["total"])

    def daily_pnl(self) -> float:
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.realised_pnl_since(start)

    def weekly_pnl(self) -> float:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.realised_pnl_since(start)

    def consecutive_losses(self) -> int:
        rows = self._conn.execute(
            "SELECT pnl FROM trades ORDER BY closed_at DESC LIMIT 50"
        ).fetchall()
        streak = 0
        for r in rows:
            if r["pnl"] < 0:
                streak += 1
            else:
                break
        return streak

    def stats(self) -> dict:
        rows = self._conn.execute("SELECT pnl, strategy, market_key FROM trades").fetchall()
        n = len(rows)
        if n == 0:
            return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                    "total_pnl": 0.0, "wins": 0, "losses": 0}
        wins = [r["pnl"] for r in rows if r["pnl"] > 0]
        losses = [r["pnl"] for r in rows if r["pnl"] < 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        return {
            "trades": n,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(100.0 * len(wins) / n, 1),
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else float("inf"),
            "total_pnl": round(sum(r["pnl"] for r in rows), 2),
        }

    def daily_history(self, days: int = 120) -> list[dict]:
        """Realised P&L grouped by calendar day (for the calendar heatmap)."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT substr(closed_at,1,10) AS d, SUM(pnl) AS pnl, COUNT(*) AS n "
            "FROM trades WHERE closed_at >= ? GROUP BY d ORDER BY d",
            (since,),
        ).fetchall()
        return [{"date": r["d"], "pnl": round(float(r["pnl"]), 2), "trades": int(r["n"])} for r in rows]

    def equity_curve(self, starting_balance: float = 10_000.0) -> list[dict]:
        rows = self._conn.execute(
            "SELECT closed_at, pnl FROM trades ORDER BY closed_at ASC"
        ).fetchall()
        equity = starting_balance
        curve = []
        for r in rows:
            equity += r["pnl"]
            curve.append({"time": r["closed_at"], "equity": round(equity, 2)})
        return curve

    def close(self) -> None:
        self._conn.close()

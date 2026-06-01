"""SharedState — the single object the heartbeat writes and the state server reads.

It is updated from the asyncio event loop (heartbeat tiers) and read from FastAPI
request handlers running in a threadpool, so writes are guarded by a lock and the
public ``snapshot()`` returns a plain, JSON-serialisable dict.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from apex.logging_setup import recent_logs
from apex.models import AccountSnapshot, IndicatorSnapshot, Position


class SharedState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.status: str = "STARTING"            # STARTING | LIVE | DEMO | PAPER | HALTED
        self.mode: str = "PAPER"
        self.trading_enabled: bool = True
        self.account: AccountSnapshot = AccountSnapshot()
        self.positions: list[Position] = []
        self.snapshots: dict[str, IndicatorSnapshot] = {}
        self.daily_pnl: float = 0.0
        self.weekly_pnl: float = 0.0
        self.daily_pnl_pct: float = 0.0
        self.weekly_pnl_pct: float = 0.0
        self.stats: dict[str, Any] = {}
        self.breakers: dict[str, bool] = {}      # name -> tripped?
        self.prop: dict[str, Any] = {}           # prop-firm guard telemetry
        self.broker_error: str = ""              # last broker-connection error (shown in UI)
        self.last_heartbeat: datetime = datetime.now(timezone.utc)
        self.api_calls: dict[str, int] = {"ig": 0, "claude": 0}
        self.portfolio_health: int = 100

    def update(self, **fields: Any) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self, key, value)
            self.last_heartbeat = datetime.now(timezone.utc)

    def bump_api(self, name: str, n: int = 1) -> None:
        with self._lock:
            self.api_calls[name] = self.api_calls.get(name, 0) + n

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable view for the dashboard."""
        with self._lock:
            return {
                "status": self.status,
                "mode": self.mode,
                "trading_enabled": self.trading_enabled,
                "account": self.account.model_dump(mode="json"),
                "positions": [self._position_view(p) for p in self.positions],
                "indicators": {k: v.model_dump(mode="json") for k, v in self.snapshots.items()},
                "pnl": {
                    "daily": round(self.daily_pnl, 2),
                    "weekly": round(self.weekly_pnl, 2),
                    "daily_pct": round(self.daily_pnl_pct, 2),
                    "weekly_pct": round(self.weekly_pnl_pct, 2),
                },
                "stats": self.stats,
                "breakers": self.breakers,
                "prop": self.prop,
                "broker_error": self.broker_error,
                "portfolio_health": self.portfolio_health,
                "api_calls": self.api_calls,
                "last_heartbeat": self.last_heartbeat.isoformat(),
                "logs": recent_logs(50),
                "server_time": datetime.now(timezone.utc).isoformat(),
            }

    @staticmethod
    def _position_view(p: Position) -> dict[str, Any]:
        base = p.model_dump(mode="json")
        base.update(
            unrealised_pnl=round(p.unrealised_pnl, 2),
            unrealised_points=round(p.unrealised_points, 1),
            stop_distance_remaining=round(p.stop_distance_remaining, 1),
            target_distance_remaining=round(p.target_distance_remaining, 1),
        )
        return base


# Process-wide singleton consumed by the state server.
STATE = SharedState()

"""Shared backtest request handler — used by the cloud relay (heartbeat) and the
local state-server endpoint. Fetches historical candles via the broker, then runs
the pure engine.
"""

from __future__ import annotations

from loguru import logger

from apex.backtest.engine import run_backtest
from apex.config import MARKETS, Settings
from apex.ig.client import Broker


def run_request(broker: Broker, settings: Settings, req: dict) -> dict:
    try:
        key = str(req.get("market", "US500")).upper()
        market = MARKETS.get(key)
        if market is None:
            return {"error": f"Unknown market '{key}'."}
        minutes = int(req.get("minutes", settings.heartbeat.candle_minutes_default))
        bars = max(80, min(int(req.get("bars", 500)), 1000))
        candles = broker.candles(market.epic, minutes, bars)
        if len(candles) < 80:
            return {"error": "Not enough historical data returned by the broker."}
        result = run_backtest(
            candles, market,
            starting_equity=float(req.get("starting_equity", settings.starting_equity or 100_000.0)),
            risk_pct=float(req.get("risk_pct", settings.risk.max_risk_per_trade_pct)),
            atr_stop_mult=settings.risk.atr_stop_multiplier,
            params=settings.strategy,
            target_pct=float(req.get("target_pct", 10.0)),
            total_limit_pct=float(req.get("total_limit_pct", 10.0)),
        )
        data = result.to_dict()
        data["mode"] = broker.mode          # IG = real data, PAPER = synthetic
        data["minutes"] = minutes
        return data
    except Exception as exc:
        logger.exception("Backtest failed: {}", exc)
        return {"error": str(exc) or exc.__class__.__name__}

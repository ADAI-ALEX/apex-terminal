"""Shared backtest request handler — used by the cloud relay (heartbeat) and the
local state-server endpoint.

To avoid burning IG's limited historical-data allowance (which raises
``ApiExceededException``), it prefers candles the engine already holds in memory
(streamed for the active markets) before making a fresh broker request.
"""

from __future__ import annotations

from loguru import logger

from apex.backtest.engine import run_backtest
from apex.config import MARKETS, Settings
from apex.ig.client import Broker
from apex.models import Candle


def run_request(
    broker: Broker, settings: Settings, req: dict, history: dict[str, list[Candle]] | None = None
) -> dict:
    try:
        key = str(req.get("market", "US500")).upper()
        market = MARKETS.get(key)
        if market is None:
            return {"error": f"Unknown market '{key}'."}
        minutes = int(req.get("minutes", settings.heartbeat.candle_minutes_default))
        bars = max(80, min(int(req.get("bars", 500)), 1000))

        from apex.backtest.cache import load_candles, save_candles

        # 1) Reuse in-memory candles the engine already streams (no IG allowance cost).
        candles: list[Candle] = list((history or {}).get(key, []))
        source = "live cache"
        # 2) Otherwise load from the on-disk cache (persisted real data, no IG cost).
        if len(candles) < 80:
            candles = load_candles(key, minutes)
            source = "disk cache"
        # 3) Last resort: fetch from the broker, handling the IG allowance gracefully.
        if len(candles) < 80:
            try:
                candles = broker.candles(market.epic, minutes, bars)
                source = "broker"
            except Exception as exc:
                if "ApiException" in type(exc).__name__ or "exceeded" in str(exc).lower():
                    return {"error": (
                        "IG's historical-data allowance is exhausted (ApiExceededException). "
                        "It resets weekly. Tip: backtest an instrument your engine is already "
                        "streaming — those candles are cached and reused for free."
                    )}
                return {"error": str(exc) or exc.__class__.__name__}

        if len(candles) < 80:
            return {"error": "Not enough historical data yet — let the engine stream for a bit, then retry."}

        save_candles(key, minutes, candles)  # refresh the disk cache for next time

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
        data["source"] = source
        return data
    except Exception as exc:
        logger.exception("Backtest failed: {}", exc)
        return {"error": str(exc) or exc.__class__.__name__}

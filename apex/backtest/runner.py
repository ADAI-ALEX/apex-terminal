"""Shared backtest request handler — used by the cloud relay (heartbeat) and the
local state-server endpoint.

Two data sources:

* **Local (offline)** — the committed 20-year daily CSVs in ``apex/backtest/data/``
  (``apex.backtest.dataset``). Used whenever ``source == "local"`` or a custom /
  default strategy is selected. **No network is touched**, satisfying the
  "no Yahoo API calls during a backtest" rule. Carries the niche exogenous series
  (fear_greed / vix / sentiment) custom strategies can read.
* **Live** — the original path (Yahoo → in-memory stream cache → disk cache →
  broker), preferred for intraday timeframes on the running engine. To avoid
  burning IG's limited historical-data allowance it favours candles the engine
  already holds before making a fresh broker request.

The selected strategy is resolved from :mod:`apex.strategies.store`; the built-in
``book`` replays the live multi-strategy engine, anything else runs the user's
snippet via the custom evaluator.
"""

from __future__ import annotations

from loguru import logger

from apex.backtest.engine import run_backtest
from apex.config import MARKETS, Settings
from apex.ig.client import Broker
from apex.models import Candle
from apex.strategies import store as strategy_store


def run_request(
    broker: Broker, settings: Settings, req: dict, history: dict[str, list[Candle]] | None = None
) -> dict:
    try:
        key = str(req.get("market", "US500")).upper()
        market = MARKETS.get(key)
        if market is None:
            return {"error": f"Unknown market '{key}'."}

        # Resolve the selected strategy (built-in "book" by default).
        strat_name = str(req.get("strategy", "book"))
        strat = strategy_store.get(strat_name)
        if strat is None:
            return {"error": f"Unknown strategy '{strat_name}'."}
        is_custom = strat.kind in ("custom", "default")

        minutes = int(req.get("minutes", settings.heartbeat.candle_minutes_default))
        bars = max(80, min(int(req.get("bars", 500)), 6000))

        # Local/offline is the source for custom strategies and when asked for.
        use_local = str(req.get("source", "")).lower() == "local" or is_custom

        exo: dict[str, list[float]] | None = None
        if use_local:
            from apex.backtest import dataset

            if not dataset.has_local(key):
                avail = ", ".join(dataset.available()) or "none"
                return {"error": (
                    f"No local history for {key}. Offline backtests are available for: "
                    f"{avail}. Run scripts/seed_historical.py to add more, or switch the "
                    f"data source to Live."
                )}
            series = dataset.load(key, bars)
            candles = series.candles
            exo = series.exo
            minutes = 1440  # local store is daily (D1)
            source = "local"
        else:
            candles, source = _live_candles(broker, settings, key, market.epic, minutes, bars, history)
            if isinstance(candles, dict):  # an error payload bubbled up
                return candles

        if len(candles) < 80:
            return {"error": "Not enough historical data — let the engine stream a bit, or seed local data."}

        result = run_backtest(
            candles, market,
            starting_equity=float(req.get("starting_equity", settings.starting_equity or 100_000.0)),
            risk_pct=float(req.get("risk_pct", settings.risk.max_risk_per_trade_pct)),
            atr_stop_mult=settings.risk.atr_stop_multiplier,
            params=settings.strategy,
            target_pct=float(req.get("target_pct", 10.0)),
            total_limit_pct=float(req.get("total_limit_pct", 10.0)),
            rr=settings.risk.default_rr,
            strategy={"name": strat.name, "kind": strat.kind, "code": strat.code},
            exo=exo,
        )
        data = result.to_dict()
        data["mode"] = "LOCAL" if use_local else broker.mode  # LOCAL = offline seed data
        data["minutes"] = minutes
        data["source"] = source
        data["strategy_label"] = strat.label
        return data
    except ValueError as exc:  # e.g. a custom strategy failed validation
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Backtest failed: {}", exc)
        return {"error": str(exc) or exc.__class__.__name__}


def _live_candles(
    broker: Broker, settings: Settings, key: str, epic: str, minutes: int, bars: int,
    history: dict[str, list[Candle]] | None,
) -> tuple[list[Candle], str] | tuple[dict, str]:
    """Original live data path: Yahoo → memory stream → disk cache → broker."""
    from apex.backtest import yahoo
    from apex.backtest.cache import load_candles, save_candles

    candles: list[Candle] = yahoo.fetch(key, minutes, bars)
    source = "yahoo"
    if len(candles) < 80:
        candles = list((history or {}).get(key, []))
        source = "live cache"
    if len(candles) < 80:
        candles = load_candles(key, minutes)
        source = "disk cache"
    if len(candles) < 80:
        try:
            candles = broker.candles(epic, minutes, bars)
            source = "broker"
        except Exception as exc:
            if "ApiException" in type(exc).__name__ or "exceeded" in str(exc).lower():
                return ({"error": (
                    "IG's historical-data allowance is exhausted (ApiExceededException). "
                    "It resets weekly. Tip: use the Local (offline) data source, or backtest "
                    "an instrument your engine is already streaming."
                )}, source)
            return ({"error": str(exc) or exc.__class__.__name__}, source)

    if candles and source != "live cache":
        save_candles(key, minutes, candles)  # refresh the disk cache for next time
    return candles, source

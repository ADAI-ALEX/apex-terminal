"""Yahoo Finance candle fetcher for backtesting (free, no key, deep history).

Lets backtests run on far more bars than IG's allowance permits, for any mapped
instrument. Mirrors the dashboard's /api/prices symbol map.
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests
from loguru import logger

from apex.models import Candle

SYMBOLS = {
    "US500": "^GSPC", "SPX": "^GSPC", "NAS100": "^NDX",
    "FTSE100": "^FTSE", "DAX40": "^GDAXI",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X",
}
_INTERVAL = {1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "60m", 1440: "1d"}
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _range_for(interval: str) -> str:
    # Deepest range Yahoo serves per interval (intraday is capped at ~60 days).
    if interval == "1m":
        return "5d"
    if interval in ("5m", "15m", "30m"):
        return "1mo"
    if interval == "60m":
        return "2y"
    return "10y"  # 1d → deep history for big backtests


def fetch(key: str, minutes: int, bars: int) -> list[Candle]:
    sym = SYMBOLS.get(key.upper())
    if not sym:
        return []
    interval = _INTERVAL.get(minutes, "15m")
    rng = _range_for(interval)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={interval}&range={rng}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        ts = res.get("timestamp") or []
        q = res["indicators"]["quote"][0]
        vol = q.get("volume") or [0] * len(ts)
        out: list[Candle] = []
        for i, t in enumerate(ts):
            o, h, lo, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            if None in (o, h, lo, c):
                continue
            out.append(Candle(
                time=datetime.fromtimestamp(t, tz=timezone.utc),
                open=o, high=h, low=lo, close=c, volume=vol[i] or 0,
            ))
        logger.info("Yahoo backtest data: {} {} bars ({} {})", len(out), key, interval, rng)
        return out[-bars:] if bars and bars < len(out) else out
    except Exception as exc:
        logger.warning("Yahoo fetch failed for {}: {}", key, exc)
        return []

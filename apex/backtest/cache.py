"""On-disk candle cache for backtesting.

Lets backtests run on saved data instead of re-hitting IG's limited historical API.
The engine refreshes the cache from the candles it already streams; backtests then
load instantly from disk, even across restarts and for non-streamed instruments.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from loguru import logger

from apex.models import Candle

_DIR = Path(os.getenv("APEX_DATA_DIR", "data")) / "candle_cache"


def _path(key: str, minutes: int) -> Path:
    return _DIR / f"{key}_{minutes}m.json"


def save_candles(key: str, minutes: int, candles: list[Candle]) -> None:
    if not candles:
        return
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        rows = [
            {"t": c.time.isoformat(), "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}
            for c in candles
        ]
        _path(key, minutes).write_text(json.dumps(rows))
    except Exception as exc:  # caching must never break a backtest
        logger.debug("candle cache save failed: {}", exc)


def load_candles(key: str, minutes: int) -> list[Candle]:
    try:
        p = _path(key, minutes)
        if not p.exists():
            return []
        rows = json.loads(p.read_text())
        return [
            Candle(time=datetime.fromisoformat(r["t"]), open=r["o"], high=r["h"],
                   low=r["l"], close=r["c"], volume=r.get("v", 0))
            for r in rows
        ]
    except Exception as exc:
        logger.debug("candle cache load failed: {}", exc)
        return []

"""Local historical dataset loader for the **offline** backtester.

Reads the committed 20-year daily CSVs in ``apex/backtest/data/`` (seeded by
``scripts/seed_historical.py``) and returns aligned candles plus the exogenous
"niche" series the custom-strategy engine exposes (``fear_greed``, ``vix``,
``sentiment``). **No network is touched here** — this is the data source that lets
a backtest run fully offline, satisfying the "no Yahoo API calls during a
backtest" rule.

Derived indicators (sma/ema/rsi/macd/atr/bollinger/adx) are *not* stored: they are
computed on the fly from OHLCV by :mod:`apex.indicators.engine`. Only the
exogenous series that cannot be derived from price live in the CSV.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from apex.models import Candle

DATA_DIR = Path(__file__).resolve().parent / "data"

#: Exogenous (non-price) columns the dataset carries, exposed to custom strategies.
#: ``delta`` is the per-bar taker-flow volume delta (aggressive buys − sells, base
#: units) carried by the Binance perp seeds — REAL order flow, not a proxy.
EXO_FIELDS: tuple[str, ...] = ("fear_greed", "vix", "sentiment", "delta", "macro", "macro_slow")

#: Candle-minutes → on-disk file suffix. Daily is the deep (20y) series; intraday
#: depth varies per instrument (crypto perp seeds reach 2020 on 1h/15m; 240m is
#: resampled from the 1h seeds by ``scripts/seed_4h_resample.py``).
TF_SUFFIX: dict[int, str] = {1440: "D1", 240: "240m", 60: "60m", 15: "15m", 5: "5m", 1: "1m"}


def suffix_for(minutes: int) -> str:
    return TF_SUFFIX.get(int(minutes), "D1")


@dataclass
class HistoricalSeries:
    """Aligned candles + exogenous series for one instrument (daily bars)."""

    key: str
    candles: list[Candle] = field(default_factory=list)
    #: name -> list[float], each aligned 1:1 with ``candles`` by index.
    exo: dict[str, list[float]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.candles)

    def slice(self, bars: int) -> HistoricalSeries:
        """Return the most recent ``bars`` candles (with exo aligned)."""
        if bars <= 0 or bars >= len(self.candles):
            return self
        return HistoricalSeries(
            key=self.key,
            candles=self.candles[-bars:],
            exo={name: vals[-bars:] for name, vals in self.exo.items()},
        )


def _path(key: str, timeframe: str = "D1") -> Path:
    return DATA_DIR / f"{key.upper()}_{timeframe}.csv"


def available(timeframe: str = "D1") -> list[str]:
    """Instrument keys that have a local CSV for ``timeframe`` on disk."""
    if not DATA_DIR.exists():
        return []
    return sorted(p.stem.replace(f"_{timeframe}", "") for p in DATA_DIR.glob(f"*_{timeframe}.csv"))


def has_local(key: str, timeframe: str = "D1") -> bool:
    return _path(key, timeframe).exists()


def load(key: str, bars: int = 0, timeframe: str = "D1") -> HistoricalSeries:
    """Load the local ``timeframe`` series for ``key``. Returns empty if absent.

    ``bars`` (>0) trims to the most recent N bars.
    """
    path = _path(key, timeframe)
    if not path.exists():
        logger.debug("No local dataset for {} at {}", key, path)
        return HistoricalSeries(key=key.upper())

    candles: list[Candle] = []
    exo: dict[str, list[float]] = {name: [] for name in EXO_FIELDS}
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    dt = datetime.fromisoformat(row["date"]).replace(tzinfo=timezone.utc)
                    candles.append(Candle(
                        time=dt,
                        open=float(row["open"]), high=float(row["high"]),
                        low=float(row["low"]), close=float(row["close"]),
                        volume=float(row.get("volume") or 0.0),
                    ))
                    for name in EXO_FIELDS:
                        exo[name].append(float(row.get(name) or 0.0))
                except (ValueError, KeyError):
                    continue  # skip a malformed row, never abort the load
    except Exception as exc:  # noqa: BLE001 - loading must never crash a backtest
        logger.warning("Failed reading local dataset {}: {}", path, exc)
        return HistoricalSeries(key=key.upper())

    series = HistoricalSeries(key=key.upper(), candles=candles, exo=exo)
    logger.info("Loaded local dataset {} {}: {} bars.", key, timeframe, len(candles))
    return series.slice(bars) if bars else series
